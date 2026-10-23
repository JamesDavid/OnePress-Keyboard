"""Clean the NUS SMS corpus into train/test splits for the keypad model.

Usage: python prep_nus.py corpora/nus/smsCorpus_en_2015.03.09_all.xml model.json corpora/nus

Keeps messages whose words are all in the vocabulary, normalizes punctuation so it
tokenizes like keypad input, and splits by user (about 1 user in 4 goes to test) so no
one's writing style appears in both halves. Writes train.txt, test.txt and test_na.txt
(the US/Canada users in test). The output stays under corpora/ and out of git.
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

def is_test(uid):
    return hashlib.md5(uid.encode()).digest()[0] < 64

root = ET.parse(XML).getroot()
seen = set()
train, test, test_na = [], [], []
total = 0
for m in root.iter("message"):
    total += 1
    s = clean(m.findtext("text") or "")
    if not s or s in seen:
        continue
    seen.add(s)
    p = m.find("source/userProfile")
    uid = p.findtext("userID") or ""
    if is_test(uid):
        test.append(s)
        if (p.findtext("country") or "").strip().lower() in NA:
            test_na.append(s)
    else:
        train.append(s)

os.makedirs(OUT, exist_ok=True)
for name, rows in [("train.txt", train), ("test.txt", test), ("test_na.txt", test_na)]:
    open(os.path.join(OUT, name), "w", encoding="utf-8").write("\n".join(rows) + "\n")
print(f"{total} messages -> train {len(train)}, test {len(test)} (US/Canada {len(test_na)})")
