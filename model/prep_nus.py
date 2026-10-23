"""Clean the NUS SMS corpus into train/test splits for the keypad model.

Usage: python prep_nus.py corpora/nus/smsCorpus_en_2015.03.09_all.xml model.json corpora/nus

Keeps messages whose words are all in the vocabulary, normalizes punctuation so it
tokenizes like keypad input, and splits by user (1 in 4 to test, 1 in 8 to dev for tuning)
so no one's writing style appears in two splits. Writes train.txt, train_na.txt, dev.txt,
test.txt and test_na.txt (the _na files hold the US/Canada users). The output stays under
corpora/ and out of git.
"""
import hashlib, json, os, re, sys
import xml.etree.ElementTree as ET

XML, MODEL, OUT = sys.argv[1], sys.argv[2], sys.argv[3]
M = json.load(open(MODEL))
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

NA = {"united states", "usa", "us", "canada"}
TOK = re.compile(r"[a-z]+(?:'[a-z]+)?|[.,!?]")

def clean(text):
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
        if x not in rank:
            return None
        out.append(x)
    s = ""
    for x in out:
        s += x if x in ".,!?" or not s else " " + x
    return s

def split_of(uid):
    b = hashlib.md5(uid.encode()).digest()[0]
    return "test" if b < 64 else "dev" if b < 96 else "train"

root = ET.parse(XML).getroot()
seen = set()
train, train_na, dev, test, test_na = [], [], [], [], []
total = 0
for m in root.iter("message"):
    total += 1
    s = clean(m.findtext("text") or "")
    if not s or s in seen:
        continue
    seen.add(s)
    p = m.find("source/userProfile")
    uid = p.findtext("userID") or ""
    split = split_of(uid)
    na = (p.findtext("country") or "").strip().lower() in NA
    if split == "test":
        (test_na if na else test).append(s)
    elif split == "dev":
        dev.append(s)
    else:
        (train_na if na else train).append(s)

os.makedirs(OUT, exist_ok=True)
# test.txt is every test user; test_na.txt is the US/Canada subset. train.txt excludes train_na.txt.
test = test + test_na
for name, rows in [("train.txt", train), ("train_na.txt", train_na), ("dev.txt", dev), ("test.txt", test), ("test_na.txt", test_na)]:
    open(os.path.join(OUT, name), "w", encoding="utf-8", newline="\n").write("\n".join(rows) + "\n")
print(f"{total} messages -> train {len(train)} + {len(train_na)} US/Canada, dev {len(dev)}, test {len(test)} (US/Canada {len(test_na)})")
