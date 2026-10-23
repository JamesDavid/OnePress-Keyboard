"""Export model.json to the KPD2 binary model read by every decoder (web, C, firmware).

Usage: python export_bin.py model.json onepress.bin

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
"""
import json, math, struct, sys

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
]
# Decoder constants, all in log-prob units. The punctuation ones come from model.json
# punctParams when present (see tune_punct.js).
PARAMS = ["qQ", "qN", "dQ", "cF", "dB", "cB", "eB", "apostrophe", "completion", "literal", "unknown"]
DEFAULTS = {"qQ": 2.5, "qN": -1.5, "dQ": -1.5, "cF": -3, "dB": 0, "cB": 0, "eB": 0,
            "apostrophe": math.log(0.5), "completion": math.log(0.5), "literal": -14, "unknown": -25}
QUESTION_STARTERS = ['what', 'where', 'when', 'why', 'who', 'whom', 'whose', 'which', 'how',
    'can', 'could', 'would', 'should', 'will', 'shall', 'do', 'does', 'did', 'is', 'are', 'was', 'were', 'am',
    "isn't", "aren't", "don't", "doesn't", "didn't", "can't", "won't", "wouldn't", "shouldn't", "couldn't",
    'have', 'has', 'may', 'might', 'want', 'wanna', 'need', 'got', 'any', 'anyone', 'anybody', 'anything',
    'ready', 'free', 'you', 'u']
LAMBDA_K = 40   # lambda = c / (c + LAMBDA_K), Witten-Bell style

KEYMAP = {c: k for k, letters in {"2": "abc", "3": "def", "4": "ghi", "5": "jkl", "6": "mno",
          "7": "pqrs", "8": "tuv", "9": "wxyz", "#": "'"}.items() for c in letters}

def keys(w):
    return "".join(KEYMAP[c] for c in w)

def q(x):
    v = round(x * SCALE)
    assert -32768 <= v <= 32767, x
    return v

def main():
    M = json.load(open(sys.argv[1], encoding="utf-8"))
    out = sys.argv[2]
    words, P, bos = M["words"], M["punct"], M["bos"]
    n = len(words)
    assert bos == n + len(P) and bos < 0xFFFF, "token ids must fit in u16"
    rank = {w: i for i, w in enumerate(words)}

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
            lam = c / (c + LAMBDA_K)
            for a, cnt in sorted(zip(arr[0::2], arr[1::2])):
                nxt.append(a)
                lps.append(q(math.log(lam * cnt / c + (1 - lam) * uni[a])))
            bow.append(q(math.log(1 - lam)))
        else:
            bow.append(0)
        rows.append(len(nxt))
    sec["rowStart"] = struct.pack(f"<{len(rows)}I", *rows)
    sec["bow"] = i16(bow)
    sec["next"] = u16(nxt)
    sec["lp"] = i16(lps)
    sec["qStart"] = u16(sorted(rank[w] for w in QUESTION_STARTERS if w in rank))
    sec["punct"] = "".join(P).encode()
    params = dict(DEFAULTS, **M.get("punctParams", {}))
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
    print(f"KPD2: {n} words, {len(nxt)} pairs, {len(data):,} bytes")

def u16(xs):
    return struct.pack(f"<{len(xs)}H", *xs)

def i16(xs):
    return struct.pack(f"<{len(xs)}h", *xs)

if __name__ == "__main__":
    main()
