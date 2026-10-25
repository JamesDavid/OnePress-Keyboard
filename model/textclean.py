"""Clean a message so it tokenizes like keypad input (used for the NUS and chat test sets).

make_clean(model.json) returns clean(text, oov=False): the message normalized ("?!" -> "?",
"ok ." -> "ok.", "dont" -> "don't" where the contraction is far more common), or None if it has
digits or symbols, fewer than 3 or more than 30 words, or (unless oov) a word the vocabulary lacks.
"""
import json, re

TOK = re.compile(r"[a-z]+(?:'[a-z]+)?|[.,!?]")

def make_clean(model_json):
    M = json.load(open(model_json, encoding="utf-8"))
    words = M["words"]
    rank = {w: i for i, w in enumerate(words)}   # vocab is frequency-ordered
    logp = M["logp"]

    # "dont" -> "don't" when the apostrophe form is far more common; keep real words like "were", "its".
    fix = {}
    for w in words:
        if "'" in w:
            bare = w.replace("'", "")
            if bare not in rank or logp[rank[bare]] < logp[rank[w]] - 2.3:
                fix[bare] = w
    # Texters drop apostrophes; these bare forms almost always mean the contraction. Bare forms
    # that are common words of their own (were, its, ill, well, hell, shell, wed, shed, id) stay.
    for w in ["let's", "i'm", "i've", "that's", "what's", "you're", "they're", "how's", "where's",
              "there's", "here's", "who's", "isn't", "aren't", "wasn't", "weren't", "don't", "doesn't",
              "didn't", "can't", "won't", "wouldn't", "shouldn't", "couldn't", "haven't", "hasn't",
              "hadn't", "you'll", "you've", "you'd", "they'll", "they've", "we've", "she's", "he's"]:
        if w in rank:
            fix[w.replace("'", "")] = w


    def clean(text, oov=False):
        t = text.replace("’", "'").replace("‘", "'")
        t = re.sub(r"\s+", " ", t).strip()
        if re.search(r"[^A-Za-z' .,!?]", t):
            return None                                # digits, emoticons, symbols: skip
        t = re.sub(r"[.!?]*\?[.!?]*", "?", t)          # "?!" / "??" -> "?"
        t = re.sub(r"!+[.!]*", "!", t)
        t = re.sub(r"\.+", ".", t)
        t = re.sub(r",+", ",", t)
        t = re.sub(r"\s+([.,!?])", r"\1", t)           # "ok ." -> "ok."
        t = re.sub(r"([.,!?])(?=[A-Za-z])", r"\1 ", t) # "ok.see" -> "ok. see"
        t = re.sub(r"^[.,!?\s]+", "", t)
        t = re.sub(r",$", "", t).strip()
        toks = TOK.findall(t.lower())
        ws = [x for x in toks if x not in ".,!?"]
        if not 3 <= len(ws) <= 30:
            return None
        out = []
        for x in toks:
            if x in ".,!?":
                out.append(x); continue
            x = fix.get(x, x)
            if x not in rank and not oov:
                return None
            out.append(x)
        s = ""
        for x in out:
            s += x if x in ".,!?" or not s else " " + x
        return s
    return clean
