# Question openers from text: for each word that opens a sentence or a clause (after the words in
# export_bin.py's QUESTION_SKIP), how often the sentence ends in "?". Writes the words that open
# questions at least --share of the time, seen at least --min times, one per line with their counts.
#   python question_words.py out.txt file[:weight] ... [--share 0.5] [--min 20]
# A list to review by hand: topic words of one corpus come out too (Taskmaster's "model", "monday").
# English QUESTION_STARTERS has the reviewed ones (share 0.4, min 50).
import argparse, re
from collections import Counter
from export_bin import QUESTION_SKIP

TOK = re.compile(r"[a-z]+(?:'[a-z]+)?|[.,!?]")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("files", nargs="+")
    ap.add_argument("--share", type=float, default=0.5)
    ap.add_argument("--min", type=float, default=20)
    a = ap.parse_args()
    skip = set(QUESTION_SKIP)
    q, n = Counter(), Counter()
    for f in a.files:
        path, _, w = f.partition(":")
        w = float(w or 1)
        for line in open(path, encoding="utf-8"):
            openers = []          # this sentence's sentence and clause openers
            want = True
            for t in TOK.findall(line.lower()):
                if t in ".!?":
                    for o in openers:
                        n[o] += w
                        q[o] += w * (t == "?")
                    openers, want = [], True
                elif t == ",":
                    want = True
                elif want and t not in skip:
                    openers.append(t)
                    want = False
    keep = sorted((x for x in n if n[x] >= a.min and q[x] / n[x] >= a.share), key=lambda x: -n[x])
    with open(a.out, "w", encoding="utf-8", newline="\n") as o:
        for x in keep:
            o.write(f"{x}\t{q[x] / n[x]:.2f}\t{n[x]:.0f}\n")
    print(f"{len(keep)} question openers -> {a.out}")

if __name__ == "__main__":
    main()
