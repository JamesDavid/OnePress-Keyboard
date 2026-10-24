#!/usr/bin/env bash
# Rebuilds model.json (counts) and onepress.bin (the KPD2 model every decoder reads),
# then re-inlines the web page.
set -euo pipefail
cd "$(dirname "$0")"
PY="${PYTHON:-$(command -v python || command -v python3)}"
"$PY" -m pip install --quiet wordfreq
[ -d corpora/nus ] && [ -d corpora/chat ] || ./fetch_corpora.sh
NUS=corpora/nus/smsCorpus_en_2015.03.09_all.xml
if [ ! -f corpora/nus/train.txt ]; then
  # The SMS splits are filtered to the vocabulary, so build once without them first.
  [ -f model.json ] || "$PY" build_model.py corpora model.json data/messages.txt data/proper.txt
  "$PY" prep_nus.py "$NUS" model.json corpora/nus
fi
# Weights chosen on the NUS dev split; :cased marks corpora used for capitalization.
"$PY" build_model.py corpora model.json data/messages.txt data/proper.txt corpora/nus/train.txt:3 corpora/nus/train_na.txt:10   corpora/chat/topical_chat.txt:1:cased corpora/chat/taskmaster.txt:1:cased corpora/chat/persona.txt:1:cased
# Three sizes, cutoffs chosen on the NUS dev split (see CLAUDE.md for accuracy):
#   onepress.bin    phones, web    45k words, three-word context
#   onepress-m.bin  ESP32 nodes    20k words
#   onepress-s.bin  radios, nRF52   5k words, no context casing (in May)
"$PY" export_bin.py model.json onepress.bin --ambig-only --min-count 3 --tri-min 6
"$PY" export_bin.py model.json onepress-m.bin --vocab 20000 --ambig-only --min-count 6
"$PY" export_bin.py model.json onepress-s.bin --vocab 5000 --ambig-only --min-count 20 --no-context-case
"$PY" - <<'PY'
import base64
t = open("../web/page.template.html", encoding="utf-8").read()
t = t.replace("__DECODER__", open("../web/decoder.js", encoding="utf-8").read())
for tag, f in [("L", "onepress.bin"), ("M", "onepress-m.bin"), ("S", "onepress-s.bin")]:
    t = t.replace(f"__MODEL_{tag}__", base64.b64encode(open(f, "rb").read()).decode())
open("../web/keypad.html", "w", encoding="utf-8", newline="\n").write(t)
PY
echo "built model.json, onepress{,-m,-s}.bin, web/keypad.html"
