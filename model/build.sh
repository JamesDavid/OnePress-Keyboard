#!/usr/bin/env bash
# Rebuilds model.json (web) and model.bin (iOS), then re-inlines the web page.
set -euo pipefail
cd "$(dirname "$0")"
python3 -m pip install --quiet wordfreq
[ -d corpora/brown ] || ./fetch_corpora.sh
python3 build_model.py corpora model.json data/messages.txt data/proper.txt
python3 export_bin.py model.json ../ios/Keyboard/Resources/model.bin
python3 - <<'PY'
t = open("../web/page.template.html").read()
d = open("../web/decoder.js").read(); m = open("model.json").read()
open("../web/keypad.html", "w").write(t.replace("__DECODER__", d).replace("__MODEL__", m))
PY
echo "built model.json, model.bin, web/keypad.html"
