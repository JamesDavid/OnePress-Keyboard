#!/usr/bin/env bash
# Rebuilds model.json (web) and model.bin (iOS), then re-inlines the web page.
set -euo pipefail
cd "$(dirname "$0")"
PY="${PYTHON:-$(command -v python || command -v python3)}"
"$PY" -m pip install --quiet wordfreq
[ -d corpora/nus ] || ./fetch_corpora.sh
NUS=corpora/nus/smsCorpus_en_2015.03.09_all.xml
if [ ! -f corpora/nus/train.txt ]; then
  # The SMS splits are filtered to the vocabulary, so build once without them first.
  [ -f model.json ] || "$PY" build_model.py corpora model.json data/messages.txt data/proper.txt
  "$PY" prep_nus.py "$NUS" model.json corpora/nus
fi
"$PY" build_model.py corpora model.json data/messages.txt data/proper.txt corpora/nus/train.txt:3 corpora/nus/train_na.txt:10
"$PY" export_bin.py model.json ../ios/Keyboard/Resources/model.bin
"$PY" - <<'PY'
t = open("../web/page.template.html", encoding="utf-8").read()
d = open("../web/decoder.js", encoding="utf-8").read(); m = open("model.json", encoding="utf-8").read()
open("../web/keypad.html", "w", encoding="utf-8", newline="\n").write(t.replace("__DECODER__", d).replace("__MODEL__", m))
PY
echo "built model.json, model.bin, web/keypad.html"
