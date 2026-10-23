"""Build a compact word unigram+bigram model for the keypad artifact."""
import json, math, os, re, sys
from collections import Counter
from wordfreq import top_n_list, word_frequency

ROOT = sys.argv[1]
OUT = sys.argv[2]
VOCAB_N = 45000
WORD_RE = re.compile(r"^[a-z]+(?:'[a-z]+)?$")
PUNCT = [".", ",", "!", "?"]

# ---- vocabulary from wordfreq ----
vocab = [w for w in top_n_list("en", 60000) if WORD_RE.match(w)][:VOCAB_N]
freqs = [word_frequency(w, "en") for w in vocab]

# ---- proper nouns: curated brands/places + first names ----
curated = {}
for line in open(sys.argv[4], encoding="utf-8"):
    if line.startswith("#"): continue
    for w in line.split():
        if WORD_RE.match(w.lower()): curated[w.lower()] = w
names = set()
for f in ["male.txt", "female.txt"]:
    for line in open(os.path.join(ROOT, "names", f), encoding="latin-1"):
        n = line.strip()
        if n and WORD_RE.match(n.lower()) and word_frequency(n.lower(), "en") > 3e-7:
            names.add(n.lower())

vidx = {w: i for i, w in enumerate(vocab)}
added = 0
for w in list(curated) + sorted(names):
    if w not in vidx:
        vidx[w] = len(vocab); vocab.append(w)
        freqs.append(max(word_frequency(w, "en"), 3e-7)); added += 1

# ---- token streams from corpora ----
tok_re = re.compile(r"[a-z]+(?:'[a-z]+)?|[.,!?]")
def sentences_from_text(text):
    text = text.lower().replace("’", "'").replace("’", "'")
    yield tok_re.findall(text)

streams = []
bdir = os.path.join(ROOT, "brown")
for f in sorted(os.listdir(bdir)):
    if not re.match(r"^c[a-r]\d\d$", f):
        continue
    for para in open(os.path.join(bdir, f), encoding="utf-8").read().split("\n\n"):
        words = [t.rsplit("/", 1)[0] for t in para.split() if "/" in t]
        streams.append((" ".join(words), 1))
wdir = os.path.join(ROOT, "webtext")
for f in ["overheard.txt", "firefox.txt", "grail.txt", "pirates.txt", "singles.txt", "wine.txt"]:
    for line in open(os.path.join(wdir, f), encoding="latin-1"):
        streams.append((line, 1))
gdir = os.path.join(ROOT, "gutenberg")
for f in ["austen-emma.txt", "austen-persuasion.txt", "austen-sense.txt", "bryant-stories.txt",
          "burgess-busterbrown.txt", "carroll-alice.txt", "chesterton-ball.txt", "chesterton-brown.txt",
          "chesterton-thursday.txt", "edgeworth-parents.txt", "melville-moby_dick.txt"]:
    for para in open(os.path.join(gdir, f), encoding="latin-1").read().split("\n\n"):
        streams.append((para.replace("\n", " "), 1))
for sub in ["pos", "neg"]:
    d = os.path.join(ROOT, "movie_reviews", sub)
    for f in os.listdir(d):
        for line in open(os.path.join(d, f), encoding="latin-1"):
            streams.append((line, 1))
# Hand-written everyday messages, weighted up so casual phrasing is represented.
for line in open(sys.argv[3], encoding="utf-8"):
    if line.strip():
        streams.append((line, 25))

vset = {w: i for i, w in enumerate(vocab)}
P0 = len(vocab)  # punctuation ids follow words
ids = dict(vset)
for i, p in enumerate(PUNCT):
    ids[p] = P0 + i
BOS = P0 + len(PUNCT)

uni = Counter()
bi = Counter()
for text, wt in streams:
    for toks in sentences_from_text(text):
        prev = BOS
        for t in toks:
            cur = ids.get(t)
            if cur is None:          # out-of-vocabulary word: break the chain
                prev = -1
                continue
            uni[cur] += wt
            if prev >= 0:
                bi[(prev, cur)] += wt
                uni[("ctx", prev)] += wt
            prev = BOS if t in (".", "!", "?") else cur

# prune
bigrams = {k: c for k, c in bi.items() if c >= 2}
ctx = {}
for (a, b), c in bigrams.items():
    ctx[a] = ctx.get(a, 0) + c

# Punctuation unigram probs from corpus share of tokens
total_tok = sum(v for k, v in uni.items() if not isinstance(k, tuple))
punct_p = [uni[P0 + i] / total_tok for i in range(len(PUNCT))]

# Pack bigrams: {prev: [next, count, next, count, ...]}
packed = {}
for (a, b), c in sorted(bigrams.items()):
    packed.setdefault(a, []).extend([b, c])

# ---- capitalization from cased corpora ----
cap = Counter(); low = Counter()
def scan_cased(text):
    toks = re.findall(r"[A-Za-z]+(?:'[A-Za-z]+)?|[.!?]", text)
    start = True
    for t in toks:
        if t in ".!?": start = True; continue
        if not start:
            if t[0].isupper() and not t.isupper(): cap[t.lower()] += 1
            elif t.islower(): low[t] += 1
        start = False
for f in sorted(os.listdir(bdir)):
    if re.match(r"^c[a-r]\d\d$", f):
        scan_cased(" ".join(t.rsplit("/", 1)[0] for t in open(os.path.join(bdir, f), encoding="utf-8").read().split() if "/" in t))
for f in os.listdir(gdir):
    scan_cased(open(os.path.join(gdir, f), encoding="latin-1").read())
for f in ["overheard.txt", "wine.txt"]:
    scan_cased(open(os.path.join(wdir, f), encoding="latin-1").read())

display = {}
for i, w in enumerate(vocab):
    c, l = cap[w], low[w]
    if w in curated:
        # Brands that are also everyday words (target, chase, switch) stay lowercase.
        if l >= 5 and c / (c + l) < 0.5:
            continue
        if curated[w] != w: display[i] = curated[w]
        continue
    if (c + l >= 3 and c / (c + l) > 0.75) or (c + l < 3 and w in names):
        display[i] = w[0].upper() + w[1:]
# "mcdonalds" typed without the apostrophe should still show as McDonald's
for w, shown in curated.items():
    if "'" in w and w.replace("'", "") in vidx:
        display[vidx[w.replace("'", "")]] = shown
print("added proper nouns:", added, "capitalized:", len(display))

model = {
    "words": vocab,
    "display": {str(k): v for k, v in display.items()},
    "logp": [round(math.log(f), 2) for f in freqs],
    "punct": PUNCT,
    "punctLogp": [round(math.log(p), 2) for p in punct_p],
    "bos": BOS,
    "ctx": {str(k): v for k, v in ctx.items()},
    "bi": {str(k): v for k, v in packed.items()},
}
s = json.dumps(model, separators=(",", ":"))
open(OUT, "w").write(s)
print(f"vocab {len(vocab)}, bigrams {len(bigrams)}, bytes {len(s):,}")
