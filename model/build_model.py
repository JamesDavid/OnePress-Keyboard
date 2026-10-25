"""Build the word model (model.json) that export_bin.py turns into KPD2 files.

Usage: python build_model.py corpora model.json data/messages.txt data/proper.txt [path:weight[:cased] ...]
       python build_model.py corpora model-es.json - - corpora/es/train.txt:1:cased --lang es

--lang (default en): the wordfreq language. Other languages take no English extras (Gutenberg,
movie reviews, names, messages.txt; give - for the two files) and allow accented letters.

- Vocabulary and unigram frequencies: wordfreq (data CC BY-SA 4.0), plus curated proper nouns
  (data/proper.txt) and first names from the NLTK names corpus.
- Word pairs and triples: Project Gutenberg selections and the Pang & Lee movie reviews from
  NLTK, the hand-written messages (data/messages.txt, weighted x25), and the corpora given on
  the command line: the NUS SMS training split and the chat corpora from prep_chat.py.
- Casing: from the cased corpora (Gutenberg and the ones marked :cased): a word's usual casing
  mid-sentence, and the previous words after which that flips (in May / I may).
"""
import json, math, os, re, sys
from collections import Counter
from wordfreq import top_n_list, word_frequency

LANG = "en"
if "--lang" in sys.argv:
    i = sys.argv.index("--lang")
    LANG = sys.argv[i + 1]
    del sys.argv[i:i + 2]
EN = LANG == "en"
ROOT = sys.argv[1]
OUT = sys.argv[2]
VOCAB_N = 45000
L = "a-z" if EN else "a-z\u00df-\u00f6\u00f8-\u00ff"            # lowercase letters of a word
WORD_RE = re.compile(f"^[{L}]+(?:'[{L}]+)?$")
PUNCT = [".", ",", "!", "?"]
TRI_CTX_MIN = 12    # count word triples only after word pairs seen at least this often (weighted)

# ---- vocabulary from wordfreq ----
vocab = [w for w in top_n_list(LANG, 60000) if WORD_RE.match(w)][:VOCAB_N]
freqs = [word_frequency(w, LANG) for w in vocab]

# ---- proper nouns: curated brands/places + first names ----
curated = {}
for line in (open(sys.argv[4], encoding="utf-8") if sys.argv[4] != "-" else []):
    if line.startswith("#"): continue
    for w in line.split():
        if WORD_RE.match(w.lower()): curated[w.lower()] = w
names = set()
for f in ["male.txt", "female.txt"] if EN else []:
    for line in open(os.path.join(ROOT, "names", f), encoding="latin-1"):
        n = line.strip()
        if n and WORD_RE.match(n.lower()) and word_frequency(n.lower(), "en") > 3e-7:
            names.add(n.lower())

vidx = {w: i for i, w in enumerate(vocab)}
added = 0
for w in list(curated) + sorted(names):
    if w not in vidx:
        vidx[w] = len(vocab); vocab.append(w)
        freqs.append(max(word_frequency(w, LANG), 3e-7)); added += 1

# ---- text streams: (text, weight, cased) ----
tok_re = re.compile(f"[{L}]+(?:'[{L}]+)?|[.,!?]")
def tokens(text):
    return tok_re.findall(text.lower().replace("’", "'").replace("‘", "'"))

streams = []
gdir = os.path.join(ROOT, "gutenberg")
for f in ["austen-emma.txt", "austen-persuasion.txt", "austen-sense.txt", "bryant-stories.txt",
          "burgess-busterbrown.txt", "carroll-alice.txt", "chesterton-ball.txt", "chesterton-brown.txt",
          "chesterton-thursday.txt", "edgeworth-parents.txt", "melville-moby_dick.txt"] if EN else []:
    for para in open(os.path.join(gdir, f), encoding="latin-1").read().split("\n\n"):
        streams.append((para.replace("\n", " "), 1, True))
for sub in ["pos", "neg"] if EN else []:
    d = os.path.join(ROOT, "movie_reviews", sub)
    for f in os.listdir(d):
        for line in open(os.path.join(d, f), encoding="latin-1"):
            streams.append((line, 1, False))          # lowercased: no casing
# Hand-written everyday messages, weighted up so casual phrasing is represented.
for line in (open(sys.argv[3], encoding="utf-8") if sys.argv[3] != "-" else []):
    if line.strip():
        streams.append((line, 25, False))
# One-message-per-line corpora given as path:weight[:cased].
for spec in sys.argv[5:]:
    parts = spec.split(":")
    p, wt, cased = parts[0], int(parts[1]), len(parts) > 2 and parts[2] == "cased"
    if not os.path.exists(p):
        print("skipping missing corpus", p); continue
    for line in open(p, encoding="utf-8"):
        if line.strip():
            streams.append((line, wt, cased))

P0 = len(vocab)  # punctuation ids follow words
ids = dict(vidx)
for i, p in enumerate(PUNCT):
    ids[p] = P0 + i
BOS = P0 + len(PUNCT)
SENT_END = {".", "!", "?"}

def walk(toks):
    """(p2, p1, cur) for each in-vocabulary token: p1 is BOS at a sentence start, -1 after an
    unknown word (the chain breaks); p2 is -1 when there is no token before p1."""
    p2, p1 = -1, BOS
    for t in toks:
        cur = ids.get(t)
        if cur is None:
            p2 = p1 = -1
            continue
        yield p2, p1, cur
        if t in SENT_END: p2, p1 = -1, BOS
        else: p2, p1 = p1, cur

# ---- pass 1: unigrams and pairs ----
uni = Counter()
bi = Counter()
seen = Counter()   # times each pair was actually seen; hand-written messages always count as kept
for text, wt, _ in streams:
    for p2, p1, cur in walk(tokens(text)):
        uni[cur] += wt
        if p1 >= 0:
            bi[(p1, cur)] += wt
            seen[(p1, cur)] += 2 if wt >= 25 else 1

# Prune pairs seen only once. Weighting must not rescue them: one message weighted x3
# shouldn't outvote a pair seen in many places.
bigrams = {k: c for k, c in bi.items() if seen[k] >= 2}
ctx = {}
for (a, b), c in bigrams.items():
    ctx[a] = ctx.get(a, 0) + c

# ---- pass 2: triples, for pairs common enough to be worth a context of their own ----
tri_ctx = {k for k, c in bi.items() if c >= TRI_CTX_MIN and seen[k] >= 2}
tri = Counter()
tseen = Counter()
tctx = Counter()   # every triple counted, so pruned ones back off
for text, wt, _ in streams:
    for p2, p1, cur in walk(tokens(text)):
        if p2 >= 0 and (p2, p1) in tri_ctx:
            k = (p2 << 16 | p1) << 16 | cur
            tri[k] += wt
            tseen[k] += 2 if wt >= 25 else 1
            tctx[p2 << 16 | p1] += wt
trigrams = {k: c for k, c in tri.items() if tseen[k] >= 2}

# Punctuation unigram probs from corpus share of tokens
total_tok = sum(uni.values())
punct_p = [uni[P0 + i] / total_tok for i in range(len(PUNCT))]

packed = {}
for (a, b), c in sorted(bigrams.items()):
    packed.setdefault(a, []).extend([b, c])
tpacked = {}
for k, c in sorted(trigrams.items()):
    a, b, cur = k >> 32, (k >> 16) & 0xFFFF, k & 0xFFFF
    tpacked.setdefault(f"{a},{b}", []).extend([cur, c])

# ---- capitalization from the cased corpora ----
cap = Counter(); low = Counter()
pcap = Counter(); plow = Counter()   # by previous word (lowercase), for words cased both ways
ncap = Counter(); nlow = Counter()   # by next word
def scan_cased(text):
    start, prev = True, None
    toks = re.findall(r"[^\W\d_]+(?:'[^\W\d_]+)?|[.!?,]", text.replace("’", "'"))
    for i, t in enumerate(toks):
        if t in ".!?": start, prev = True, None; continue
        if t == ",": prev = ","; continue
        if not start:
            w = t.lower()
            nxt = toks[i + 1].lower() if i + 1 < len(toks) and toks[i + 1][0].isalpha() else None
            if t[0].isupper() and not t.isupper(): cap[w] += 1; pcap[(prev, w)] += 1; ncap[(w, nxt)] += 1
            elif t.islower(): low[w] += 1; plow[(prev, w)] += 1; nlow[(w, nxt)] += 1
        start, prev = False, t.lower()
for f in os.listdir(gdir) if EN else []:
    scan_cased(open(os.path.join(gdir, f), encoding="latin-1").read())
for text, wt, cased in streams:
    if cased and not text.startswith("\0"):
        scan_cased(text)

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

# Context casing: words written both ways (may/May, will/Will, bill/Bill) take their other form
# after a previous word, or before a next word, that makes it the likelier one ("in May",
# "Will Smith"). The context's counts are pulled toward the word's overall ratio (CASE_PRIOR
# made-up sightings), so a handful of sightings can't flip a word on their own.
CASE_PRIOR, CASE_MIN = 4, 3
cap_flip, cap_next, cap_keep, alt = [], [], [], {}
def flips(cap_c, low_c, key_word, key_ctx, out, keep=None):
    for k in set(cap_c) | set(low_c):
        w, ctx_w = key_word(k), key_ctx(k)
        if w not in vidx or ctx_w is None or (ctx_w != "," and ctx_w not in ids):
            continue
        i = vidx[w]
        c, l = cap[w], low[w]
        if c + l < 20 or not 0.02 < c / (c + l) < 0.98:
            continue                                   # always cased one way: nothing to flip
        n_cap, n_low = cap_c[k], low_c[k]
        if n_cap + n_low < CASE_MIN:
            continue
        p = (n_cap + CASE_PRIOR * c / (c + l)) / (n_cap + n_low + CASE_PRIOR)
        usual_cap = i in display
        if (usual_cap and p < 0.5) or (not usual_cap and p > 0.5):
            out.append([ids[ctx_w], i])
            if i not in alt:
                alt[i] = w if usual_cap else (curated.get(w) or w[0].upper() + w[1:])
        elif keep is not None and n_cap + n_low >= 2 * CASE_MIN:
            keep.append([ids[ctx_w], i])
flips(pcap, plow, lambda k: k[1], lambda k: k[0], cap_flip)
# A next word that keeps the usual casing outvotes the previous word ("like apple pie").
flips(ncap, nlow, lambda k: k[0], lambda k: k[1], cap_next, cap_keep)
flipped = {i for _, i in cap_flip}
cap_flip.sort()
cap_next = sorted([i, nx] for nx, i in cap_next)       # (word, next)
cap_keep = sorted([i, nx] for nx, i in cap_keep if i in flipped)
print("added proper nouns:", added, "capitalized:", len(display),
      "context casing: after", len(cap_flip), "before", len(cap_next), "kept before", len(cap_keep))

model = {
    "lang": LANG,
    "words": vocab,
    "display": {str(k): v for k, v in display.items()},
    "logp": [round(math.log(f), 2) for f in freqs],
    "punct": PUNCT,
    "punctLogp": [round(math.log(p), 2) for p in punct_p],
    "bos": BOS,
    "ctx": {str(k): v for k, v in ctx.items()},
    "bi": {str(k): v for k, v in packed.items()},
    "tctx": {f"{k >> 16},{k & 0xFFFF}": v for k, v in tctx.items()},
    "tri": tpacked,
    "capFlip": cap_flip,
    "capNext": cap_next,
    "capKeep": cap_keep,
    "alt": {str(k): v for k, v in alt.items()},
}
s = json.dumps(model, separators=(",", ":"))
open(OUT, "w", encoding="utf-8", newline="\n").write(s)
print(f"vocab {len(vocab)}, bigrams {len(bigrams)}, trigrams {len(trigrams)} in {len(tpacked)} contexts, bytes {len(s):,}")
