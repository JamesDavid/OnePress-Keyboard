"""Tatoeba Mandarin sentences, in Simplified characters, split into words, for the Chinese model.

Usage: python prep_zh.py corpora/zh/cmn_sentences.tsv.bz2 corpora/zh
       python prep_zh.py --extra corpora/zh/train_cv.txt corpora/zh/cv/*.txt

Needs jieba and pypinyin (pip install jieba pypinyin, both MIT). Tatoeba (tatoeba.org, CC BY 2.0
FR) mixes Simplified and Traditional; wordfreq's table makes everything Simplified. Keeps
sentences of 2-30 words made of Chinese characters and the marks ， 。 ？ ！ (、 ； ： count as
commas; quotes and book-title marks are dropped; anything else, Latin letters or digits
included, skips the sentence). Words come from wordfreq's tokenizer (jieba with wordfreq's
dictionary), the same words as the model's vocabulary. Written one sentence per line, words
separated by spaces, marks as . , ? ! after their word ("我们 明天 去 北京 吧."); dev.txt and
test.txt add a tab and the pinyin a person would type for each word, toneless with ü as v
("women mingtian qu beijing ba."). That pinyin is read from the whole sentence (pypinyin), so
a character read differently in context (长大 zhang, 银行 hang) is typed that way. Split by
sentence id as prep_tatoeba.py: 1 in 20 to test.txt, 1 in 20 to dev.txt, the rest to train.txt.

--extra: more training text, one sentence per line (Common Voice's Mandarin sentences, CC0),
cleaned and split the same way into one file, without any sentence of dev.txt or test.txt (in
the output's folder; run the Tatoeba step first).
"""
import bz2, hashlib, os, re, sys
from pypinyin import lazy_pinyin
from wordfreq import tokenize
from wordfreq.chinese import simplify_chinese

EXTRA = sys.argv[1] == "--extra"
src, out = (None, sys.argv[2]) if EXTRA else (sys.argv[1], sys.argv[2])
HAN = "㐀-䶿一-鿿"
MARKS = {"，": ",", "。": ".", "？": "?", "！": "!", "、": ",", "；": ",", "：": ",",
         ",": ",", ".": ".", "?": "?", "!": "!"}
DROP = "“”‘’「」『』《》〈〉\"' 　"

def clean(t):
    t = simplify_chinese(t)
    t = "".join(c for c in t if c not in DROP)
    t = re.sub("…+|\\.\\.\\.+", "。", t)
    if not t or any(c not in MARKS and not re.match(f"[{HAN}]", c) for c in t):
        return None
    t = "".join(MARKS.get(c, c) for c in t)
    t = re.sub(r"[.!?]*\?[.!?]*", "?", t)
    t = re.sub(r"!+[.!]*", "!", t)
    t = re.sub(r"\.+", ".", t)
    t = re.sub(r",+", ",", t)
    t = re.sub(r"^[.,!?]+", "", t)
    words, marks = [], []           # marks[i]: the marks after words[i]
    for chunk, mark in re.findall(f"([{HAN}]*)([.,!?]*)", t):
        if chunk:
            words.extend(tokenize(chunk, "zh"))
            marks.extend([""] * (len(words) - len(marks)))
        if mark and marks:
            marks[-1] += mark
    if not 2 <= len(words) <= 30 or "".join(words) != re.sub("[.,!?]", "", t):
        return None
    syl = lazy_pinyin("".join(words))
    pin, k = [], 0
    for w in words:
        p = "".join(syl[k:k + len(w)])
        k += len(w)
        if not re.fullmatch("[a-z]+", p):
            return None
        pin.append(p)
    return (" ".join(w + m for w, m in zip(words, marks)), " ".join(p + m for p, m in zip(pin, marks)))

if EXTRA:
    held = set()
    for name in ("dev", "test"):
        for line in open(os.path.join(os.path.dirname(out), name + ".txt"), encoding="utf-8"):
            held.add(line.split("\t")[0].replace(" ", ""))
    rows, seen = [], set()
    for path in sys.argv[3:]:
        for line in open(path, encoding="utf-8"):
            s = clean(line.strip())
            if s and s[0] not in seen and s[0].replace(" ", "") not in held:
                seen.add(s[0])
                rows.append(s[0])
    open(out, "w", encoding="utf-8", newline="\n").write("\n".join(rows) + "\n")
    print(f"{len(rows)} sentences in {out}")
    sys.exit()

splits = {"train": [], "dev": [], "test": []}
seen = set()
with bz2.open(src, "rt", encoding="utf-8") as f:
    for line in f:
        parts = line.rstrip("\n").split("\t")
        if len(parts) < 3:
            continue
        s = clean(parts[2])
        if not s or s[0] in seen:
            continue
        seen.add(s[0])
        b = hashlib.md5(parts[0].encode()).digest()[0]
        name = "test" if b < 13 else "dev" if b < 26 else "train"
        splits[name].append(s[0] if name == "train" else "\t".join(s))
for name, rows in splits.items():
    open(os.path.join(out, name + ".txt"), "w", encoding="utf-8", newline="\n").write("\n".join(rows) + "\n")
print({k: len(v) for k, v in splits.items()})
