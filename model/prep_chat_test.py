"""A second held-out test set: modern written chat, from the Topical-Chat test splits (which no
model trains on: build_model.py and train_nn.py read only its train split), and a dev set from
its validation splits for tuning (model/tune_punct.js).

Usage: python prep_chat_test.py model.json corpora/chat

Reads tc_{test,valid}_{freq,rare}.json (fetch_corpora.sh), cleans each message like the NUS
test set (textclean.py) but keeps words outside the vocabulary, and writes test_chat.txt and
dev_chat.txt (one message per line). tests/eval.js --oov-exact spells those words in exact mode, as a person
would, and scores the predicted words.
"""
import json, os, sys
from textclean import make_clean

model_json, d = sys.argv[1], sys.argv[2]
clean = make_clean(model_json)
for split, out_name in [("test", "test_chat.txt"), ("valid", "dev_chat.txt")]:
    out, seen = [], set()
    for name in [f"tc_{split}_freq.json", f"tc_{split}_rare.json"]:
        if not os.path.exists(os.path.join(d, name)):
            continue
        for conv in json.load(open(os.path.join(d, name), encoding="utf-8")).values():
            for m in conv["content"]:
                s = clean(m["message"], oov=True)
                if s and s not in seen:
                    seen.add(s)
                    out.append(s)
    open(os.path.join(d, out_name), "w", encoding="utf-8", newline="\n").write("\n".join(out) + "\n")
    print(f"{out_name}: {len(out):,} messages")
