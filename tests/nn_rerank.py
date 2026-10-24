"""Does a neural language model help? Rescore the decoder's alternatives (tests/nn_export.js).

For each word slot, each alternative sentence (that slot changed, the rest as the decoder put
it) is scored by the word model (its beam score) plus weight * the neural model's log
probability of the whole sentence; the best per slot is kept. Word accuracy is counted like
tests/eval.js.

  build/nnenv/Scripts/python tests/nn_rerank.py build/nn/dev_na.jsonl --lm distilgpt2 --weights 0,0.5,1,2
"""
import argparse, json, math, re
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

ap = argparse.ArgumentParser()
ap.add_argument("data")
ap.add_argument("--lm", default="distilgpt2")
ap.add_argument("--weights", default="0,0.25,0.5,1,2")
ap.add_argument("--limit", type=int, default=0)
ap.add_argument("--selfnorm", action="store_true", help="GRU: score without the softmax normalizer")
a = ap.parse_args()

TOK = re.compile(r"[a-z]+(?:'[a-z]+)?|[.,!?]")
toks = lambda s: TOK.findall(s.lower())
rows = [json.loads(l) for l in open(a.data, encoding="utf-8")]
if a.limit:
    rows = rows[:a.limit]

dev = "cuda" if torch.cuda.is_available() else "cpu"
cache = {}
if a.lm.endswith(".pt"):
    # Our own GRU word model (model/train_nn.py): tokens like the decoder's, self-normalized.
    import sys, os
    ck = torch.load(a.lm, map_location=dev)
    M = json.load(open(os.path.join(os.path.dirname(__file__), "../model/model.json"), encoding="utf-8"))
    ids = {w: i for i, w in enumerate(M["words"])}
    for i, p in enumerate(M["punct"]):
        ids[p] = len(M["words"]) + i
    emb = ck["state"]["emb.weight"]
    gru = torch.nn.GRU(ck["embed"], ck["hidden"], batch_first=True).to(dev)
    gru.load_state_dict({k[4:]: v for k, v in ck["state"].items() if k.startswith("gru.")})
    proj = torch.nn.Linear(ck["hidden"], ck["embed"]).to(dev)
    proj.load_state_dict({k[5:]: v for k, v in ck["state"].items() if k.startswith("proj.")})
    bias = ck["state"]["bias"]
    params = sum(v.numel() for v in ck["state"].values())
    @torch.no_grad()
    def score(sentences):
        todo = [s for s in dict.fromkeys(sentences) if s not in cache]
        for s in todo:
            t = [ck["BOS"]] + [ids.get(x, ck["UNK"]) for x in toks(s)]
            x = torch.tensor([t], device=dev)
            y, _ = gru(emb[x])
            logits = proj(y[0, :-1]) @ emb.T + bias
            raw = logits.gather(-1, x[0, 1:, None])[:, 0]
            cache[s] = (raw - (torch.logsumexp(logits, -1) if not a.selfnorm else 0)).sum().item()
        return [cache[s] for s in sentences]
else:
  tok = AutoTokenizer.from_pretrained(a.lm)
  lm = AutoModelForCausalLM.from_pretrained(a.lm, dtype=torch.float16 if dev == "cuda" else torch.float32).to(dev).eval()
  bos = tok.bos_token_id if tok.bos_token_id is not None else tok.eos_token_id
  params = sum(p.numel() for p in lm.parameters())

@torch.no_grad()
def score_hf(sentences):
    """Natural-log probability of each sentence (from the start of text)."""
    todo = [s for s in dict.fromkeys(sentences) if s not in cache]
    for i in range(0, len(todo), 64):
        batch = todo[i:i + 64]
        enc = [[bos] + tok(s, add_special_tokens=False)["input_ids"] for s in batch]
        n = max(map(len, enc))
        ids = torch.full((len(enc), n), tok.eos_token_id if tok.eos_token_id is not None else 0)
        mask = torch.zeros((len(enc), n))
        for j, e in enumerate(enc):
            ids[j, :len(e)] = torch.tensor(e); mask[j, :len(e)] = 1
        ids, mask = ids.to(dev), mask.to(dev)
        logits = lm(input_ids=ids, attention_mask=mask).logits.float()
        lp = torch.log_softmax(logits[:, :-1], -1).gather(-1, ids[:, 1:, None])[..., 0] * mask[:, 1:]
        for s, v in zip(batch, lp.sum(-1).tolist()):
            cache[s] = v
    return [cache[s] for s in sentences]

if not a.lm.endswith(".pt"):
    score = score_hf

# Score everything once.
for r in rows:
    score([r["best"]] + [x["sentence"] for s in r["slots"] for x in s["alts"]])

def accuracy(w):
    ok = tot = 0
    for r in rows:
        words = toks(r["best"])
        base = r["score"] / 256 + w * cache[r["best"]]
        for s in r["slots"]:
            choice, top = None, base
            for x in s["alts"]:
                v = x["score"] / 256 + w * cache[x["sentence"]]
                if v > top + 1e-9:
                    choice, top = x, v
            if choice is not None:
                # the slot's word in the alternative sentence replaces the one in best
                alt = toks(choice["sentence"])
                if len(alt) == len(words):
                    for i, (p, q) in enumerate(zip(words, alt)):
                        if p != q and i < len(words):
                            pass
                    diff = [i for i, (p, q) in enumerate(zip(toks(r["best"]), alt)) if p != q]
                    for i in diff:
                        words[i] = alt[i]
        ref = toks(r["ref"])
        for i, x in enumerate(ref):
            if x in ".,!?":
                continue
            tot += 1
            ok += i < len(words) and words[i] == x
    return ok / tot

print(f"{a.lm} ({params / 1e6:.0f}M parameters), {len(rows)} messages")
for w in map(float, a.weights.split(",")):
    print(f"  weight {w:<5}  words {100 * accuracy(w):.2f}%")
