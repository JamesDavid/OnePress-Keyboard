"""Tatoeba sentences of one language, cleaned and split for a non-English model.

Usage: python prep_tatoeba.py corpora/es/spa_sentences.tsv.bz2 corpora/es

Tatoeba (tatoeba.org, CC BY 2.0 FR) is short everyday sentences written by volunteers. Keeps
sentences of 2-30 words made of letters (accents included), apostrophes and . , ! ? (the
inverted ¿ ¡ are dropped: the decoder adds them), and splits them by sentence id: 1 in 20 to
test.txt, 1 in 20 to dev.txt, the rest to train.txt (cased, for word pairs and capitalization).
œ and æ (outside Latin-1) become oe and ae, as people often type them; a hyphen between letters
becomes a space (the keypad has no hyphen: "est-ce" is typed, and comes out, as two words).
"""
import bz2, hashlib, os, re, sys

src, out = sys.argv[1], sys.argv[2]
LETTER = "a-zA-ZÀ-ÖØ-öø-ÿ"
BAD = re.compile(f"[^{LETTER}' .,!?]")
WORD = re.compile(f"[{LETTER}]+(?:'[{LETTER}]+)?")

def clean(t):
    t = t.replace("’", "'").replace("‘", "'").replace("¿", "").replace("¡", "")
    t = t.replace("œ", "oe").replace("Œ", "Oe").replace("æ", "ae").replace("Æ", "Ae")
    t = re.sub(f"(?<=[{LETTER}])-(?=[{LETTER}])", " ", t)
    t = t.replace("\u00a0", " ").replace("\u202f", " ")         # French spaces before ? ! :
    t = re.sub(r"\s+", " ", t).strip()
    if BAD.search(t):
        return None                                # digits, quotes, symbols: skip
    t = re.sub(r"[.!?]*\?[.!?]*", "?", t)
    t = re.sub(r"!+[.!]*", "!", t)
    t = re.sub(r"\.+", ".", t)
    t = re.sub(r",+", ",", t)
    t = re.sub(r"\s+([.,!?])", r"\1", t)
    t = re.sub(r"^[.,!?\s]+", "", t)
    return t if 2 <= len(WORD.findall(t)) <= 30 else None

splits = {"train": [], "dev": [], "test": []}
seen = set()
with bz2.open(src, "rt", encoding="utf-8") as f:
    for line in f:
        parts = line.rstrip("\n").split("\t")
        if len(parts) < 3:
            continue
        s = clean(parts[2])
        if not s or s.lower() in seen:
            continue
        seen.add(s.lower())
        b = hashlib.md5(parts[0].encode()).digest()[0]
        splits["test" if b < 13 else "dev" if b < 26 else "train"].append(s)
for name, rows in splits.items():
    open(os.path.join(out, name + ".txt"), "w", encoding="utf-8", newline="\n").write("\n".join(rows) + "\n")
print({k: len(v) for k, v in splits.items()})
