#!/usr/bin/env bash
# Builds the non-English models from wordfreq + Tatoeba (corpora/<lang>/, fetch_corpora.sh), in
# three sizes like English: onepress-<lang>.bin (phones, web), -m (ESP32), -s (radios, nRF52).
# Chinese (zh: corpora/zh from prep_zh.py, needs pypinyin) has no -s: 5,000 words leave too many to spell.
#   ./build_langs.sh [lang ...]      (default: all of them)
set -euo pipefail
cd "$(dirname "$0")"
PY="${PYTHON:-$(command -v python || command -v python3)}"
LANGS="${*:-es de pt fr it nl sv pl cs tr ru el ar zh}"
for c in $LANGS; do
  [ -f corpora/$c/train.txt ] || { echo "no corpora/$c/train.txt (run fetch_corpora.sh)"; continue; }
  if [ $c = zh ]; then
    # Chinese: a small corpus, so every pair seen once is kept (as Arabic) and pairs are smoothed
    # more (--lambda-k 320: +0.4 points of characters on dev spaced, +0.6 unspaced); words are pinyin.
    # Plus Common Voice's conversational Mandarin sentences (train_cv_chat.txt, prep_zh.py --extra).
    cv=""; [ -f corpora/zh/train_cv_chat.txt ] && cv="corpora/zh/train_cv_chat.txt:1"
    "$PY" build_model.py corpora model-zh.json - - corpora/zh/train.txt:1 $cv --lang zh --pairs-seen 1
    "$PY" export_bin.py model-zh.json onepress-zh.bin --ambig-only --min-count 1 --tri-min 2 --no-compounds --lambda-k 320
    "$PY" export_bin.py model-zh.json onepress-zh-m.bin --vocab 20000 --ambig-only --min-count 1 --tri-min 2 --no-compounds --lambda-k 320
    continue
  fi
  # Arabic: keys far more ambiguous than the others' and little text, so it keeps every pair
  if [ $c = ar ]; then extra="--pairs-seen 1"; min=1; tri=2; mm=2; ms=6; else extra=""; min=3; tri=6; mm=6; ms=20; fi
  "$PY" build_model.py corpora model-$c.json - - corpora/$c/train.txt:1:cased --lang $c $extra
  "$PY" export_bin.py model-$c.json onepress-$c.bin --ambig-only --min-count $min --tri-min $tri
  "$PY" export_bin.py model-$c.json onepress-$c-m.bin --vocab 20000 --ambig-only --min-count $mm
  "$PY" export_bin.py model-$c.json onepress-$c-s.bin --vocab 5000 --ambig-only --min-count $ms --no-context-case
done
