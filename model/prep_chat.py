"""Turn the downloaded chat corpora into one message per line for build_model.py.

Usage: python prep_chat.py corpora/chat

Reads (see fetch_corpora.sh):
  tc.json    Topical-Chat (Amazon), CDLA-Sharing-1.0: text chats between crowd workers
  tm1.json   Taskmaster-1 self-dialogs (Google), CC BY 4.0: written two-sided dialogs
  spc.csv    Synthetic-Persona-Chat (Google), CC BY 4.0: generated small talk
Writes topical_chat.txt, taskmaster.txt and persona.txt next to them, keeping the casing
(build_model.py lowercases for counting and reads casing for capitalization).
"""
import csv, json, os, re, sys

d = sys.argv[1]
csv.field_size_limit(1 << 30)

def clean(t):
    t = t.replace("’", "'").replace("‘", "'")
    return " ".join(t.split())

def write(name, lines):
    n = 0
    with open(os.path.join(d, name), "w", encoding="utf-8", newline="\n") as f:
        for t in lines:
            if "[" in t:                        # [user 1's name] placeholders: drop the line
                continue
            t = clean(t)
            if t:
                f.write(t + "\n"); n += 1
    print(f"{name}: {n:,} messages")

tc = json.load(open(os.path.join(d, "tc.json"), encoding="utf-8"))
write("topical_chat.txt", (m["message"] for conv in tc.values() for m in conv["content"]))

tm = json.load(open(os.path.join(d, "tm1.json"), encoding="utf-8"))
write("taskmaster.txt", (u["text"] for conv in tm for u in conv["utterances"]))

def persona():
    with open(os.path.join(d, "spc.csv"), encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            for line in row["Best Generated Conversation"].split("\n"):
                yield re.sub(r"^\s*User \d+:\s*", "", line)
write("persona.txt", persona())
