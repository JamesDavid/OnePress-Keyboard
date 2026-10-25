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
"$PY" export_bin.py model.json onepress.bin --ambig-only --min-count 3 --tri-min 6 --known-compounds 1.1
"$PY" export_bin.py model.json onepress-m.bin --vocab 20000 --ambig-only --min-count 6 --known-compounds 2
"$PY" export_bin.py model.json onepress-s.bin --vocab 5000 --ambig-only --min-count 20 --no-context-case
[ -f corpora/chat/tc_test_freq.json ] && "$PY" prep_chat_test.py model.json corpora/chat   # second test set
# Other languages: wordfreq + Tatoeba, phone size (Spanish also ESP32 and radio sizes)
for c in es de pt fr; do
  [ -f corpora/$c/train.txt ] || continue
  "$PY" build_model.py corpora model-$c.json - - corpora/$c/train.txt:1:cased --lang $c
  "$PY" export_bin.py model-$c.json onepress-$c.bin --ambig-only --min-count 3 --tri-min 6
done
if [ -f model-es.json ]; then
  "$PY" export_bin.py model-es.json onepress-es-m.bin --vocab 20000 --ambig-only --min-count 6
  "$PY" export_bin.py model-es.json onepress-es-s.bin --vocab 5000 --ambig-only --min-count 20 --no-context-case
fi
"$PY" ../web/build_page.py
echo "built model.json, onepress{,-m,-s}.bin, onepress-{es,es-m,es-s,de,pt,fr}.bin, web/keypad.html"
