#!/usr/bin/env bash
# Builds the non-English models from wordfreq + Tatoeba (corpora/<lang>/, fetch_corpora.sh), in
# three sizes like English: onepress-<lang>.bin (phones, web), -m (ESP32), -s (radios, nRF52).
#   ./build_langs.sh [lang ...]      (default: all of them)
set -euo pipefail
cd "$(dirname "$0")"
PY="${PYTHON:-$(command -v python || command -v python3)}"
LANGS="${*:-es de pt fr it nl sv pl cs tr ru el}"
for c in $LANGS; do
  [ -f corpora/$c/train.txt ] || { echo "no corpora/$c/train.txt (run fetch_corpora.sh)"; continue; }
  "$PY" build_model.py corpora model-$c.json - - corpora/$c/train.txt:1:cased --lang $c
  "$PY" export_bin.py model-$c.json onepress-$c.bin --ambig-only --min-count 3 --tri-min 6
  "$PY" export_bin.py model-$c.json onepress-$c-m.bin --vocab 20000 --ambig-only --min-count 6
  "$PY" export_bin.py model-$c.json onepress-$c-s.bin --vocab 5000 --ambig-only --min-count 20 --no-context-case
done
