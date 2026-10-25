"""Export model.json to the KPD2 binary model read by every decoder (web, C, firmware).

Usage: python export_bin.py model.json onepress.bin [--vocab N] [--min-count C] [--ambig-only]
                           [--tri-min C] [--tri-contexts N] [--no-context-case] [--no-compounds]
                           [--known-compounds ZIPF] [--no-slips]

Everything is little-endian, every section 4-byte aligned, and the decoder searches the
file in place (from flash or a memory map), so nothing is parsed or allocated on load.
Log-probabilities are int16 in units of 1/SCALE nats, which keeps every decoder on
integer adds and makes the JS and C decoders agree exactly.

Header (16 bytes + section table):
  "KPD2", u16 version, u16 scale, u16 nWords, u16 nPunct, u16 bos, u16 nSections
  nSections x { u32 offset, u32 length }       in the order of SECTIONS below

Token ids: words 0..nWords-1, punctuation nWords..nWords+nPunct-1, BOS = nWords+nPunct.
Scores:    lp(prev, cur) = row entry for cur if present, else bow[prev] + uni[cur].
           A prev with no row (bow 0, no entries) falls back to the unigram.
           With three-word context (p2, p1): if (p2, p1) is a triKey context, the triple's entry
           for cur if present, else triBow[context] + lp(p1, cur); otherwise lp(p1, cur).
Sections after "params" are optional (older files stop there and decoders treat them as empty).
"""
import argparse, bisect, json, math, struct, sys
from collections import Counter

SCALE = 256
SECTIONS = [
    "wordText",   # utf8 words concatenated, no separators
    "wordOff",    # u32[nWords+1] start of each word in wordText
    "keyIdx",     # u16[nWords] word ids sorted by (keypad keys, id); "'" is key '#'
    "stripIdx",   # u16[] ids of words with an apostrophe, sorted by (keys without '#', id)
    "dispId",     # u16[] ids with display casing (iPhone, McDonald's), ascending
    "dispOff",    # u32[len(dispId)+1] into dispText
    "dispText",   # utf8
    "uni",        # i16[nWords+nPunct] log P(token)
    "rowStart",   # u32[bos+2] first entry of each context row (rows 0..bos)
    "bow",        # i16[bos+1] log(1 - lambda) of each row
    "next",       # u16[] next-token ids, ascending within each row
    "lp",         # i16[] interpolated log P(next | row) of each entry
    "qStart",     # u16[] question-opener word ids, ascending
    "punct",      # nPunct ASCII punctuation characters
    "params",     # i16[] decoder constants, see PARAMS
    "qSkip",      # u16[] words skipped when finding a sentence's opener (hello, so, ok), ascending
    "triKey",     # u32[nT] three-word contexts p2 << 16 | p1, ascending
    "triStart",   # u32[nT+1] first entry of each context
    "triBow",     # i16[nT] backoff weight of each context
    "triNext",    # u16[] next-token ids, ascending within each context
    "triLp",      # i16[] log P(next | p2, p1) of each entry
    "capKey",     # u32[] prev << 16 | word: the word takes its other casing after prev (in May)
    "altId",      # u16[] ids with an other casing, ascending
    "altOff",     # u32[len(altId)+1] into altText
    "altText",    # utf8
    "capNextKey", # u32[] word << 16 | next: the word takes its other casing before next (Will Smith)
    "capKeepKey", # u32[] word << 16 | next: the word keeps its usual casing before next, whatever
                  #       the previous word says ("like apple pie")
    "cmpHead",    # i8[nWords] how much likelier than its unigram the word is to start a word run
                  #            together from known words (snow-man), in 1/4 nat; see compound_lifts
    "cmpTail",    # i8[nWords] ... to end one (snow-man)
    "cmpKnown",   # u32[] first << 16 | second, ascending: two words that wordfreq knows written as one
                  #       (lolly + pops: "lollypops"); such a split gets COMPOUND_KNOWN in the decoders
]
# Decoder constants, all in log-prob units. The punctuation ones come from model.json
# punctParams when present (see tune_punct.js).
# slipSub / slipDup (optional: older files stop at "unknown"): the penalty for a word one keypad
# slip away (a neighboring key; a key pressed twice), 0 to leave those out (decoder.js slipCandidates).
# flags (optional, an integer, not a log-prob): 1 capitalizes "i" (English), 2 opens a question or
# exclamation with ¿ / ¡ (Spanish).
PARAMS = ["qQ", "qN", "dQ", "cF", "dB", "cB", "eB", "apostrophe", "completion", "literal", "unknown",
          "slipSub", "slipDup", "flags"]
DEFAULTS = {"qQ": 2.5, "qN": -1.5, "dQ": -1.5, "cF": -3, "dB": 0, "cB": 0, "eB": 0,
            "apostrophe": math.log(0.5), "completion": math.log(0.5), "literal": -14, "unknown": -25,
            "slipSub": -12, "slipDup": -8}
QUESTION_STARTERS = ['what', 'where', 'when', 'why', 'who', 'whom', 'whose', 'which', 'how',
    'can', 'could', 'would', 'should', 'will', 'shall', 'do', 'does', 'did', 'is', 'are', 'was', 'were', 'am',
    "isn't", "aren't", "don't", "doesn't", "didn't", "can't", "won't", "wouldn't", "shouldn't", "couldn't",
    'have', 'has', 'may', 'might', 'want', 'wanna', 'need', 'got', 'any', 'anyone', 'anybody', 'anything',
    'ready', 'free', 'you', 'u']
# Greetings and fillers before the real opener: "hello how are you" is still a question.
QUESTION_SKIP = ['hello', 'hi', 'hey', 'hiya', 'yo', 'ok', 'okay', 'oh', 'well', 'so', 'and', 'but',
    'also', 'anyway', 'btw', 'dear', 'dude', 'babe', 'guys', 'lol', 'haha', 'hmm', 'um', 'uh', 'ah',
    'yeah', 'sorry', 'thanks', 'wow']
# Per language (model.json "lang", from build_model.py --lang): question openers, words skipped
# before them, and the flags param.
LANGS = {
    "en": (QUESTION_STARTERS, QUESTION_SKIP, 1),
    "es": (["qué", "que", "cómo", "como", "dónde", "donde", "adónde", "cuándo", "cuando", "cuál", "cuáles",
            "quién", "quiénes", "cuánto", "cuánta", "cuántos", "cuántas", "puedes", "puede", "podrías",
            "podemos", "tienes", "tiene", "hay", "estás", "está", "eres", "es", "vas", "vamos", "quieres",
            "sabes", "has", "te", "me", "hiciste", "viste", "fuiste", "crees", "verdad"],
           ["hola", "bueno", "oye", "pues", "y", "pero", "entonces", "vale", "ok", "mira", "ah", "eh", "oh",
            "jaja", "gracias", "perdón", "disculpa", "bien", "sí", "no", "ya", "también"], 2),
    "de": (["was", "wie", "wo", "wann", "warum", "wer", "wen", "wem", "wessen", "welche", "welcher", "welches",
            "wieso", "weshalb", "woher", "wohin", "kannst", "können", "könnten", "könntest", "hast", "hat", "habt",
            "haben", "bist", "ist", "sind", "seid", "gibt", "willst", "möchtest", "magst", "darf", "soll",
            "weißt", "kommst", "gehst", "machst"],
           ["hallo", "hi", "hey", "also", "ok", "okay", "na", "ja", "nein", "gut", "danke", "und", "aber", "oh",
            "ach", "sag", "mal", "übrigens"], 0),
    "fr": (["pourquoi", "comment", "où", "quand", "quel", "quelle", "quels", "quelles", "qui", "combien", "quoi",
            "qu'", "est", "as", "avez", "peux", "pouvez", "veux", "voulez", "sais", "savez", "es", "êtes", "vas",
            "allez", "aimes", "aimez", "connais", "connaissez", "ai", "dois", "devons", "pourrais", "pourriez"],
           ["salut", "bonjour", "bonsoir", "coucou", "alors", "bon", "ok", "oh", "ah", "eh", "et", "mais", "donc",
            "merci", "oui", "non", "bref", "dis", "écoute", "tiens"], 0),
    "pt": (["que", "quê", "como", "onde", "aonde", "quando", "porque", "qual", "quais", "quem", "quanto", "quanta",
            "quantos", "quantas", "você", "vocês", "pode", "podes", "podemos", "tem", "tens", "vai", "vais", "vamos",
            "está", "estás", "é", "há", "sabe", "sabes", "quer", "queres", "posso"],
           ["olá", "oi", "bem", "então", "e", "mas", "ok", "ah", "eh", "obrigado", "obrigada", "sim", "não", "bom",
            "olha", "ei"], 0),
}
LAMBDA_K = 40   # lambda = c / (c + LAMBDA_K), Witten-Bell style
TRI_K = int(__import__("os").environ.get("TRI_K", 40))      # the same for three-word contexts

KEYMAP = {c: k for k, letters in {"2": "abc", "3": "def", "4": "ghi", "5": "jkl", "6": "mno",
          "7": "pqrs", "8": "tuv", "9": "wxyz", "#": "'"}.items() for c in letters}
# Accented letters U+00C0-U+00FF take their base letter's key (decoder.js FOLD).
FOLD = "aaaaaaaceeeeiiiidnooooo\0ouuuuyts" "aaaaaaaceeeeiiiidnooooo\0ouuuuyty"
for x in range(0xC0, 0x100):
    if FOLD[x - 0xC0] != "\0":
        KEYMAP[chr(x)] = KEYMAP[FOLD[x - 0xC0]]

def keys(w):
    return "".join(KEYMAP[c] for c in w)

def q(x):
    v = round(x * SCALE)
    assert -32768 <= v <= 32767, x
    return v

def reduce(M, vocab=0, min_count=0, ambig_only=False, tri_min=0, tri_contexts=65000):
    """Shrink the model for small devices.

    vocab:      keep only the `vocab` most frequent words.
    min_count:  drop word pairs whose (weighted) count is below this.
    ambig_only: drop pairs that can't change the decoded text: a pair matters only when one
                of its words shares its keys with another word, or is punctuation/BOS (the
                punctuation key is always a choice). Dropped pairs back off to the unigram.
    tri_min:    keep word triples with at least this (weighted) count; 0 drops three-word context.
    tri_contexts: at most this many three-word contexts (ids must fit the decoders' u16 state).
    """
    words, n, nP = M["words"], len(M["words"]), len(M["punct"])
    keep = sorted(sorted(range(n), key=lambda i: (-M["logp"][i], i))[:vocab]) if 0 < vocab < n else list(range(n))
    new = {old: i for i, old in enumerate(keep)}
    for p in range(nP + 1):
        new[n + p] = len(keep) + p
    groups = Counter()
    for i in keep:
        groups[keys(words[i])] += 1
        if "'" in words[i]:
            groups[keys(words[i].replace("'", ""))] += 1
    def ambiguous(i):
        if i >= n:
            return True
        w = words[i]
        return groups[keys(w)] > 1 or ("'" in w and groups[keys(w.replace("'", ""))] > 1)
    bi, ctx = {}, {}
    for k, arr in M["bi"].items():
        a = int(k)
        if a not in new:
            continue
        row = []
        for b, c in zip(arr[0::2], arr[1::2]):
            if b in new and c >= min_count and (not ambig_only or ambiguous(a) or ambiguous(b)):
                row += [new[b], c]
        ctx[str(new[a])] = M["ctx"][k]      # the original total, so dropped pairs back off
        if row:
            bi[str(new[a])] = row
    tri, tctx = {}, {}
    for k, arr in M.get("tri", {}).items():
        a, b = map(int, k.split(","))
        if a not in new or b not in new:
            continue
        row = []
        for c, cnt in zip(arr[0::2], arr[1::2]):
            if c in new and cnt >= tri_min and (not ambig_only or ambiguous(a) or ambiguous(b) or ambiguous(c)):
                row += [new[c], cnt]
        if row:
            nk = f"{new[a]},{new[b]}"
            tri[nk] = row
            tctx[nk] = M["tctx"][k]
    if tri_contexts and len(tri) > tri_contexts:      # keep the most used contexts
        top = sorted(tri, key=lambda k: -tctx[k])[:tri_contexts]
        tri = {k: tri[k] for k in top}
    return dict(M, words=[words[i] for i in keep], logp=[M["logp"][i] for i in keep],
                display={str(new[int(k)]): v for k, v in M.get("display", {}).items() if int(k) in new},
                alt={str(new[int(k)]): v for k, v in M.get("alt", {}).items() if int(k) in new},
                capFlip=[[new[a], new[b]] for a, b in M.get("capFlip", []) if a in new and b in new],
                capNext=[[new[a], new[b]] for a, b in M.get("capNext", []) if a in new and b in new],
                capKeep=[[new[a], new[b]] for a, b in M.get("capKeep", []) if a in new and b in new],
                bi=bi, ctx=ctx, tri=tri if tri_min else {}, tctx=tctx, bos=len(keep) + nP)

# Words run together (lollypops = lolly + pops): how often each word starts or ends one, from
# every wordfreq word outside the vocabulary that splits into two vocabulary words (parts of at
# least 2 letters), weighted by its zipf frequency - 1 and shared among its splits. P(start | w)
# is smoothed toward the unigram: (count + K * P(w) * total) / (total * (1 + K)); stored is its
# log over the unigram's, in 1/4 nat. Tuned on held-out wordfreq compounds: the right word first
# 37% of the time (unigram and word pairs alone: 21%), in the 6 offered 68% (50%).
COMPOUND_K = 0.03
def compound_lifts(words, logp, lang="en", known_zipf=None):
    """(head lifts, tail lifts, known pairs): the pairs are every split of a wordfreq word of zipf
    frequency >= known_zipf (None: none) into two vocabulary words."""
    import re, wordfreq
    vocab = {w: i for i, w in enumerate(words)}
    head, tail, known = Counter(), Counter(), set()
    letters = "a-z" if lang == "en" else "a-z\u00df-\u00f6\u00f8-\u00ff"
    for w in wordfreq.get_frequency_dict(lang, "large"):
        if not re.fullmatch(f"[{letters}]{{4,24}}", w) or w in vocab:
            continue
        splits = [(w[:i], w[i:]) for i in range(2, len(w) - 1) if w[:i] in vocab and w[i:] in vocab]
        if not splits:
            continue
        z = wordfreq.zipf_frequency(w, lang, "large")
        wt = max(z - 1, 0.05) / len(splits)
        for a, b in splits:
            head[vocab[a]] += wt
            tail[vocab[b]] += wt
            if known_zipf is not None and z >= known_zipf:
                known.add(vocab[a] << 16 | vocab[b])
    def lift(cnt):
        tot = sum(cnt.values())
        return [max(-128, min(127, round(4 * (math.log((cnt[i] + COMPOUND_K * math.exp(lp) * tot) / (tot * (1 + COMPOUND_K))) - lp))))
                for i, lp in enumerate(logp)]
    return lift(head), lift(tail), sorted(known)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("model_json")
    ap.add_argument("out")
    ap.add_argument("--vocab", type=int, default=0)
    ap.add_argument("--min-count", type=int, default=0)
    ap.add_argument("--ambig-only", action="store_true")
    ap.add_argument("--tri-min", type=int, default=0)
    ap.add_argument("--tri-contexts", type=int, default=65000)
    ap.add_argument("--no-context-case", action="store_true", help="leave out the context casing tables (in May)")
    ap.add_argument("--no-compounds", action="store_true", help="leave out the run-together word tables")
    ap.add_argument("--known-compounds", type=float, default=None, metavar="ZIPF",
                    help="list the words wordfreq knows as two vocabulary words run together, down to this zipf frequency")
    ap.add_argument("--no-slips", action="store_true", help="no words one keypad slip away")
    a = ap.parse_args()
    no_compounds, no_slips, known_zipf = a.no_compounds, a.no_slips, a.known_compounds      # (a is reused below)
    M = reduce(json.load(open(a.model_json, encoding="utf-8")), a.vocab, a.min_count, a.ambig_only,
               a.tri_min, min(a.tri_contexts, 65000))
    if a.no_context_case:
        M = dict(M, capFlip=[], capNext=[], capKeep=[], alt={})
    out = a.out
    words, P, bos = M["words"], M["punct"], M["bos"]
    n = len(words)
    assert bos == n + len(P) and bos < 0xFFFF, "token ids must fit in u16"
    rank = {w: i for i, w in enumerate(words)}
    lang = M.get("lang", "en")
    starters, skip_words, flags = LANGS[lang]

    sec = {}
    text = [w.encode() for w in words]
    off = [0]
    for t in text:
        off.append(off[-1] + len(t))
    sec["wordText"] = b"".join(text)
    sec["wordOff"] = struct.pack(f"<{n + 1}I", *off)
    sec["keyIdx"] = u16(sorted(range(n), key=lambda i: (keys(words[i]), i)))
    sec["stripIdx"] = u16(sorted((i for i in range(n) if "'" in words[i]),
                                 key=lambda i: (keys(words[i].replace("'", "")), i)))
    disp = sorted((int(k), v) for k, v in M.get("display", {}).items())
    dtext = [v.encode() for _, v in disp]
    doff = [0]
    for t in dtext:
        doff.append(doff[-1] + len(t))
    sec["dispId"] = u16([i for i, _ in disp])
    sec["dispOff"] = struct.pack(f"<{len(disp) + 1}I", *doff)
    sec["dispText"] = b"".join(dtext)

    uni = [math.exp(x) for x in M["logp"]] + [math.exp(x) for x in M["punctLogp"]]
    sec["uni"] = i16([q(math.log(p)) for p in uni])

    bi = {int(k): v for k, v in M["bi"].items()}
    ctx = {int(k): v for k, v in M["ctx"].items()}
    rows, bow, nxt, lps = [0], [], [], []
    for r in range(bos + 1):
        c = ctx.get(r, 0)
        arr = bi.get(r, [])
        if c:
            # Interpolated P(next | r) for the stored pairs; every other next token gets
            # bow * P(next), with bow chosen so the row still sums to one. Without pruning
            # that is exactly 1 - lambda.
            lam = c / (c + LAMBDA_K)
            p_sum = u_sum = 0.0
            for a, cnt in sorted(zip(arr[0::2], arr[1::2])):
                p = lam * cnt / c + (1 - lam) * uni[a]
                p_sum += p
                u_sum += uni[a]
                nxt.append(a)
                lps.append(q(math.log(p)))
            bow.append(q(math.log(max(1 - p_sum, 1e-12) / (1 - u_sum))))
        else:
            bow.append(0)
        rows.append(len(nxt))
    # Three-word contexts mix their counts with the stored pair model, as decoded (quantized).
    S = SCALE
    uq = [q(math.log(p)) for p in uni]
    def p2(b, c):
        lo, hi = rows[b], rows[b + 1]
        j = bisect.bisect_left(nxt, c, lo, hi)
        return math.exp((lps[j] if j < hi and nxt[j] == c else bow[b] + uq[c]) / S)
    tri = sorted(((tuple(map(int, k.split(","))), v) for k, v in M.get("tri", {}).items()))
    tkey, tstart, tbow, tnext, tlp = [], [0], [], [], []
    for (a, b), arr in tri:
        c_ab = M["tctx"][f"{a},{b}"]
        lam = c_ab / (c_ab + TRI_K)
        p_sum = b_sum = 0.0
        for c, cnt in sorted(zip(arr[0::2], arr[1::2])):
            pb = p2(b, c)
            pt = lam * cnt / c_ab + (1 - lam) * pb
            p_sum += pt
            b_sum += pb
            tnext.append(c)
            tlp.append(q(math.log(pt)))
        tkey.append(a << 16 | b)
        tbow.append(q(math.log(max(1 - p_sum, 1e-9) / max(1 - b_sum, 1e-9))))
        tstart.append(len(tnext))
    sec["qSkip"] = u16(sorted(rank[w] for w in skip_words if w in rank))
    sec["triKey"] = struct.pack(f"<{len(tkey)}I", *tkey)
    sec["triStart"] = struct.pack(f"<{len(tstart)}I", *tstart)
    sec["triBow"] = i16(tbow)
    sec["triNext"] = u16(tnext)
    sec["triLp"] = i16(tlp)
    sec["capKey"] = struct.pack(f"<{len(M.get('capFlip', []))}I", *sorted(a << 16 | b for a, b in M.get("capFlip", [])))
    sec["capNextKey"] = struct.pack(f"<{len(M.get('capNext', []))}I", *sorted(a << 16 | b for a, b in M.get("capNext", [])))
    sec["capKeepKey"] = struct.pack(f"<{len(M.get('capKeep', []))}I", *sorted(a << 16 | b for a, b in M.get("capKeep", [])))
    alts = sorted((int(k), v) for k, v in M.get("alt", {}).items())
    atext = [v.encode() for _, v in alts]
    aoff = [0]
    for t in atext:
        aoff.append(aoff[-1] + len(t))
    sec["altId"] = u16([i for i, _ in alts])
    sec["altOff"] = struct.pack(f"<{len(alts) + 1}I", *aoff)
    sec["altText"] = b"".join(atext)
    ch, ct, kn = ([], [], []) if no_compounds else compound_lifts(words, M["logp"], lang, known_zipf)
    sec["cmpKnown"] = struct.pack(f"<{len(kn)}I", *kn)
    sec["cmpHead"] = struct.pack(f"<{len(ch)}b", *ch)
    sec["cmpTail"] = struct.pack(f"<{len(ct)}b", *ct)

    sec["rowStart"] = struct.pack(f"<{len(rows)}I", *rows)
    sec["bow"] = i16(bow)
    sec["next"] = u16(nxt)
    sec["lp"] = i16(lps)
    sec["qStart"] = u16(sorted(rank[w] for w in starters if w in rank))
    sec["punct"] = "".join(P).encode()
    params = dict(DEFAULTS, **M.get("punctParams", {}))
    if no_slips:
        params.update(slipSub=0, slipDup=0)
    params["flags"] = flags / SCALE           # q() scales it back to the integer
    sec["params"] = i16([q(params[k]) for k in PARAMS])

    head = b"KPD2" + struct.pack("<HHHHHH", 1, SCALE, n, len(P), bos, len(SECTIONS))
    body_start = len(head) + 8 * len(SECTIONS)
    table, body = b"", b""
    for name in SECTIONS:
        body += b"\0" * (-(body_start + len(body)) % 4)
        table += struct.pack("<II", body_start + len(body), len(sec[name]))
        body += sec[name]
    data = head + table + body
    open(out, "wb").write(data)
    print(f"KPD2: {n} words, {len(nxt)} pairs, {len(tnext)} triples in {len(tkey)} contexts, {len(data):,} bytes")

def u16(xs):
    return struct.pack(f"<{len(xs)}H", *xs)

def i16(xs):
    return struct.pack(f"<{len(xs)}h", *xs)

if __name__ == "__main__":
    main()
