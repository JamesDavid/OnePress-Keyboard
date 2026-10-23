#!/usr/bin/env python3
"""
keypad_decode.py - one-press-per-letter phone keypad -> text, using a local LLM.

Keys
    2 abc   3 def   4 ghi   5 jkl   6 mno   7 pqrs   8 tuv   9 wxyz
    0 = space
    # = punctuation (the model picks . , ! or ?)
    1 = apostrophe (don't, it's, I'm)

    Example: 41604663#  ->  "I'm home."
             Use --encode to get the keys for any sentence.

How it works
    Any causal language model from Hugging Face is used as-is (no training).
    Every token in its vocabulary is pre-converted to the digits you would press
    to type it. Decoding is a beam search over positions in your digit string:
    from each partial sentence, only tokens whose digits match the next keys
    are allowed, and the model's probabilities rank them. Beams are compared
    only against beams that have consumed the same number of keys, so short
    and long token paths compete fairly.

Install
    pip install torch transformers accelerate

Usage
    python keypad_decode.py                       # interactive
    python keypad_decode.py 4663                  # decode once
    python keypad_decode.py --encode "I'm home!"  # show the keys for a sentence
    python keypad_decode.py --eval sentences.txt  # accuracy on your own text
    python keypad_decode.py --model Qwen/Qwen2.5-7B --beam 24

Interactive commands
    <digits>   decode and list the top guesses
    1-9        (after a decode) accept that guess into the running context
    :reset     clear the context
    :ctx       show the context
    :q         quit
"""

import argparse
import math
import sys
import time

import numpy as np

KEYS = {
    "2": "abc", "3": "def", "4": "ghi", "5": "jkl", "6": "mno",
    "7": "pqrs", "8": "tuv", "9": "wxyz",
    "0": " ", "#": ".,!?", "1": "'",
}
CHAR_TO_KEY = {ch: k for k, chars in KEYS.items() for ch in chars}
# Curly apostrophes show up in some tokenizers; treat them as the 1 key too.
CHAR_TO_KEY["’"] = "1"

DEFAULT_MODEL = "Qwen/Qwen2.5-1.5B"
DEFAULT_PREFIX = "Here is a text message I just typed on my phone:\n\n"


def encode(text):
    """Text -> key string, or None if it contains a character with no key."""
    out = []
    for ch in text.lower():
        k = CHAR_TO_KEY.get(ch)
        if k is None:
            return None
        out.append(k)
    return "".join(out)


def normalize_keys(s):
    """Accept '*' as an alias for '#', and ignore anything that isn't a key."""
    s = s.replace("*", "#")
    return "".join(c for c in s if c in KEYS)


# --------------------------------------------------------------------------
# Language model backends.
# A backend needs: .token_strings (list[str]), .prefix_ids (list[int]),
# .next_logprobs(list_of_id_lists) -> np.ndarray [batch, vocab]
# --------------------------------------------------------------------------

class HFModel:
    def __init__(self, name, device=None, dtype="auto", prefix=DEFAULT_PREFIX):
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        self.torch = torch
        if device is None:
            if torch.cuda.is_available():
                device = "cuda"
            elif getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
                device = "mps"
            else:
                device = "cpu"
        self.device = device

        if dtype == "auto":
            torch_dtype = torch.float16 if device in ("cuda", "mps") else torch.float32
        else:
            torch_dtype = getattr(torch, dtype)

        print(f"Loading {name} on {device} ...", file=sys.stderr)
        self.tok = AutoTokenizer.from_pretrained(name)
        self.model = AutoModelForCausalLM.from_pretrained(name, torch_dtype=torch_dtype)
        self.model.to(device).eval()

        pad = self.tok.pad_token_id
        if pad is None:
            pad = self.tok.eos_token_id if self.tok.eos_token_id is not None else 0
        self.pad_id = pad

        special = set(self.tok.all_special_ids)
        n = len(self.tok)
        strings = []
        for i in range(n):
            if i in special:
                strings.append("")  # empty -> never matches any key
                continue
            strings.append(self.tok.decode([i], clean_up_tokenization_spaces=False))
        self.token_strings = strings

        self.set_prefix(prefix)

    def set_prefix(self, prefix):
        self.prefix_ids = self.tok(prefix, add_special_tokens=True)["input_ids"]

    def ids_for_text(self, text):
        return self.tok(text, add_special_tokens=False)["input_ids"]

    def next_logprobs(self, seqs):
        torch = self.torch
        maxlen = max(len(s) for s in seqs)
        ids = torch.full((len(seqs), maxlen), self.pad_id, dtype=torch.long)
        mask = torch.zeros((len(seqs), maxlen), dtype=torch.long)
        for i, s in enumerate(seqs):  # left-pad so the last column is the next-token slot
            ids[i, maxlen - len(s):] = torch.tensor(s)
            mask[i, maxlen - len(s):] = 1
        ids, mask = ids.to(self.device), mask.to(self.device)
        pos = (mask.cumsum(-1) - 1).clamp(min=0)
        with torch.no_grad():
            out = self.model(input_ids=ids, attention_mask=mask, position_ids=pos)
        logits = out.logits[:, -1, : len(self.token_strings)].float()
        return torch.log_softmax(logits, dim=-1).cpu().numpy()


# --------------------------------------------------------------------------
# Decoder
# --------------------------------------------------------------------------

class KeypadDecoder:
    def __init__(self, lm, beam=16, max_expand=64):
        self.lm = lm
        self.beam = beam
        self.max_expand = max_expand  # candidates kept per beam per step

        # Group vocabulary tokens by the keys that type them.
        by_keys = {}
        max_len = 0
        for tid, s in enumerate(lm.token_strings):
            if not s:
                continue
            k = encode(s)
            if not k:
                continue
            by_keys.setdefault(k, []).append(tid)
            max_len = max(max_len, len(k))
        self.by_keys = {k: np.array(v, dtype=np.int64) for k, v in by_keys.items()}
        self.max_token_keys = max_len

    def decode(self, keys, context_ids=None, n_best=5):
        keys = normalize_keys(keys)
        if not keys:
            return []
        start_ids = list(self.lm.prefix_ids) + list(context_ids or [])
        N = len(keys)

        # frontier[p] = {text: (score, token_ids)} for hypotheses that typed keys[:p]
        frontier = [dict() for _ in range(N + 1)]
        frontier[0][""] = (0.0, [])

        for p in range(N):
            hyps = sorted(frontier[p].items(), key=lambda kv: -kv[1][0])[: self.beam]
            frontier[p] = None  # free memory
            if not hyps:
                continue

            # Which token groups can start at this position?
            groups = []
            for k in range(1, min(self.max_token_keys, N - p) + 1):
                tids = self.by_keys.get(keys[p:p + k])
                if tids is not None:
                    groups.append((k, tids))
            if not groups:
                continue

            logprobs = self.lm.next_logprobs([start_ids + h[1][1] for h in hyps])

            for (text, (score, ids)), lp in zip(hyps, logprobs):
                # Gather all allowed continuations, keep the best few.
                all_tids = np.concatenate([g[1] for g in groups])
                all_lens = np.concatenate([np.full(len(g[1]), g[0]) for g in groups])
                cand_lp = lp[all_tids]
                if len(all_tids) > self.max_expand:
                    top = np.argpartition(-cand_lp, self.max_expand)[: self.max_expand]
                else:
                    top = np.arange(len(all_tids))
                for j in top:
                    tid = int(all_tids[j])
                    q = p + int(all_lens[j])
                    new_text = text + self.lm.token_strings[tid]
                    new_score = score + float(cand_lp[j])
                    prev = frontier[q].get(new_text)
                    # Different token splits can spell the same text; keep the best.
                    if prev is None or new_score > prev[0]:
                        frontier[q][new_text] = (new_score, ids + [tid])

        # Collapse guesses that differ only in capitalization; keep the best-scored casing.
        results, seen = [], set()
        for text, (score, _ids) in sorted(frontier[N].items(), key=lambda kv: -kv[1][0]):
            key = text.lower()
            if key in seen:
                continue
            seen.add(key)
            results.append((text, score))
            if len(results) == n_best:
                break
        return results


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def show(results):
    if not results:
        print("  (no match - check the keys)")
        return
    best = results[0][1]
    for i, (text, score) in enumerate(results, 1):
        rel = math.exp(score - best)
        print(f"  {i}. {text!r:50}  {rel:6.1%}")


def interactive(dec, lm):
    print("Keys: 2-9 letters, 0 space, # punctuation, 1 apostrophe.  :q to quit")
    context = ""
    last = []
    while True:
        try:
            line = input("\nkeys> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not line:
            continue
        if line in (":q", ":quit", ":exit"):
            return
        if line == ":reset":
            context, last = "", []
            print("  context cleared")
            continue
        if line == ":ctx":
            print(f"  {context!r}")
            continue
        if last and line.isdigit() and 1 <= int(line) <= len(last) and len(line) == 1:
            context += last[int(line) - 1][0]
            if not context.endswith(" "):
                context += " "
            print(f"  context: {context!r}")
            last = []
            continue
        ctx_ids = lm.ids_for_text(context) if context else None
        t0 = time.time()
        last = dec.decode(line, context_ids=ctx_ids)
        show(last)
        print(f"  ({time.time() - t0:.2f}s)  enter 1-{len(last)} to keep one as context")


def run_eval(dec, path):
    lines = [l.strip() for l in open(path, encoding="utf-8") if l.strip()]
    exact = 0
    word_ok = word_total = 0
    for line in lines:
        keys = encode(line)
        if keys is None:
            print(f"skip (unsupported characters): {line!r}")
            continue
        res = dec.decode(keys, n_best=1)
        guess = res[0][0] if res else ""
        ok = guess.lower() == line.lower()
        exact += ok
        gw, tw = guess.lower().split(), line.lower().split()
        word_ok += sum(a == b for a, b in zip(gw, tw))
        word_total += len(tw)
        print(f"{'OK ' if ok else 'XX '} {line!r}\n    -> {guess!r}")
    n = len(lines)
    print(f"\nsentences exact (ignoring case): {exact}/{n}")
    if word_total:
        print(f"words correct: {word_ok}/{word_total} ({word_ok / word_total:.1%})")


def main():
    ap = argparse.ArgumentParser(description="Phone keypad (one press per letter) -> text via a local LLM")
    ap.add_argument("keys", nargs="?", help="digit string to decode (omit for interactive mode)")
    ap.add_argument("--model", default=DEFAULT_MODEL, help=f"Hugging Face model id or path (default {DEFAULT_MODEL})")
    ap.add_argument("--device", default=None, help="cuda, mps, or cpu (default: auto)")
    ap.add_argument("--beam", type=int, default=16, help="beam width (higher = slower, more accurate)")
    ap.add_argument("--n", type=int, default=5, help="number of guesses to show")
    ap.add_argument("--prefix", default=DEFAULT_PREFIX, help="text the model sees before your message")
    ap.add_argument("--encode", metavar="TEXT", help="print the keys for TEXT and exit")
    ap.add_argument("--eval", metavar="FILE", help="encode each line of FILE, decode it, report accuracy")
    args = ap.parse_args()

    if args.encode is not None:
        k = encode(args.encode)
        print(k if k is not None else "contains characters with no key (allowed: letters, space, ' . , ! ?)")
        return

    lm = HFModel(args.model, device=args.device, prefix=args.prefix)
    dec = KeypadDecoder(lm, beam=args.beam)

    if args.eval:
        run_eval(dec, args.eval)
    elif args.keys:
        show(dec.decode(args.keys, n_best=args.n))
    else:
        interactive(dec, lm)


if __name__ == "__main__":
    main()
