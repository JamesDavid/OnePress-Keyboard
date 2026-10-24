"""Train the small neural word model (a GRU over the phone model's vocabulary).

Usage: python train_nn.py model.json nn.pt [corpus.txt ...] [--hidden 256 --embed 128 --epochs 3]

Token ids are the KPD2 ids of onepress.bin (words, then . , ! ?), plus BOS and UNK, so the
decoder can feed its own candidates. Each message starts from BOS. The output layer shares the
input embeddings, and training also pushes each softmax's log-normalizer toward 0 ("self-
normalized"), so the decoder can score a word with one dot product instead of a full softmax.
"""
import argparse, json, math, os, random, re, time
import torch, torch.nn as nn

ap = argparse.ArgumentParser()
ap.add_argument("model_json")
ap.add_argument("out")
ap.add_argument("corpora", nargs="*")
ap.add_argument("--hidden", type=int, default=256)
ap.add_argument("--embed", type=int, default=128)
ap.add_argument("--epochs", type=int, default=3)
ap.add_argument("--batch", type=int, default=128)
ap.add_argument("--maxlen", type=int, default=40)
ap.add_argument("--selfnorm", type=float, default=0.1)
ap.add_argument("--dev", default="corpora/nus/dev.txt")
a = ap.parse_args()

M = json.load(open(a.model_json, encoding="utf-8"))
words, punct = M["words"], M["punct"]
ids = {w: i for i, w in enumerate(words)}
for i, p in enumerate(punct):
    ids[p] = len(words) + i
BOS = len(words) + len(punct)          # the model's BOS id
UNK = BOS + 1
V = BOS + 2
TOK = re.compile(r"[a-z]+(?:'[a-z]+)?|[.,!?]")

def encode(line):
    t = [ids.get(x, UNK) for x in TOK.findall(line.lower().replace("’", "'"))]
    return [BOS] + t[:a.maxlen] if t else None

def load(paths):
    seqs = []
    for p in paths:
        spec = p.split(":")
        path, reps = spec[0], int(spec[1]) if len(spec) > 1 else 1
        n = 0
        for line in open(path, encoding="utf-8", errors="replace"):
            s = encode(line)
            if s and len(s) > 2:
                seqs.extend([s] * reps); n += 1
        print(f"{path}: {n:,} messages x{reps}")
    return seqs

train = load(a.corpora)
dev = load([a.dev])
dev_tokens = sum(len(s) - 1 for s in dev)
print(f"train {len(train):,} sequences, {sum(len(s) for s in train):,} tokens; vocab {V:,}")

class LM(nn.Module):
    def __init__(self):
        super().__init__()
        self.emb = nn.Embedding(V, a.embed)
        self.gru = nn.GRU(a.embed, a.hidden, batch_first=True)
        self.proj = nn.Linear(a.hidden, a.embed)
        self.bias = nn.Parameter(torch.zeros(V))
    def forward(self, x, h=None):
        y, h = self.gru(self.emb(x), h)
        return self.proj(y) @ self.emb.weight.T + self.bias, h

dev_ = "cuda" if torch.cuda.is_available() else "cpu"
lm = LM().to(dev_)
print(f"{sum(p.numel() for p in lm.parameters()) / 1e6:.1f}M parameters")
opt = torch.optim.Adam(lm.parameters(), lr=2e-3)

def batches(seqs, shuffle):
    order = list(range(len(seqs)))
    if shuffle: random.shuffle(order)
    order.sort(key=lambda i: len(seqs[i]) // 4 + (random.random() if shuffle else 0))   # similar lengths together
    for i in range(0, len(order), a.batch):
        b = [seqs[j] for j in order[i:i + a.batch]]
        n = max(map(len, b))
        x = torch.full((len(b), n), BOS, dtype=torch.long)
        m = torch.zeros((len(b), n - 1))
        for k, s in enumerate(b):
            x[k, :len(s)] = torch.tensor(s); m[k, :len(s) - 1] = 1
        yield x.to(dev_), m.to(dev_)

def run(seqs, train_mode):
    lm.train(train_mode)
    tot = cnt = zsum = 0.0
    for x, m in batches(seqs, train_mode):
        logits, _ = lm(x[:, :-1])
        logz = torch.logsumexp(logits, -1)
        nll = (logz - logits.gather(-1, x[:, 1:, None])[..., 0]) * m
        loss = (nll.sum() + a.selfnorm * (logz ** 2 * m).sum()) / m.sum()
        if train_mode:
            opt.zero_grad(); loss.backward()
            nn.utils.clip_grad_norm_(lm.parameters(), 1.0)
            opt.step()
        tot += nll.sum().item(); cnt += m.sum().item(); zsum += (logz.abs() * m).sum().item()
    return math.exp(tot / cnt), zsum / cnt

for ep in range(a.epochs):
    t0 = time.time()
    ppl, z = run(train, True)
    with torch.no_grad():
        dppl, dz = run(dev, False)
    for g in opt.param_groups: g["lr"] *= 0.5
    print(f"epoch {ep + 1}: train ppl {ppl:.1f}, dev ppl {dppl:.1f}, dev |log Z| {dz:.2f}, {time.time() - t0:.0f}s")
torch.save({"state": lm.state_dict(), "V": V, "BOS": BOS, "UNK": UNK, "embed": a.embed, "hidden": a.hidden}, a.out)
print("saved", a.out)
