#!/usr/bin/env bash
# Downloads the corpora the model is built from into model/corpora/ (not stored in git; see
# DATA.md for each one's terms).
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p corpora
# NLTK: Project Gutenberg selections (public domain), Pang & Lee movie reviews (CC BY 4.0) and
# the Kantrowitz names corpus (free with credit; its README is kept in corpora/names).
for c in gutenberg movie_reviews names; do
  curl -sSfL -o "/tmp/$c.zip" "https://raw.githubusercontent.com/nltk/nltk_data/gh-pages/packages/corpora/$c.zip"
  unzip -qo "/tmp/$c.zip" -d corpora
done
# NUS SMS Corpus (Chen & Kan 2013, public domain): real text messages, split into
# train/dev/test by prep_nus.py.
mkdir -p corpora/nus
curl -sSfL -o corpora/nus/en.zip "https://raw.githubusercontent.com/kite1988/nus-sms-corpus/master/smsCorpus_en_xml_2015.03.09_all.zip"
unzip -qo corpora/nus/en.zip -d corpora/nus
# Chat text, one message per line after prep_chat.py:
#   Topical-Chat (Amazon, CDLA-Sharing-1.0), Taskmaster-1 self-dialogs (Google, CC BY 4.0),
#   Synthetic-Persona-Chat (Google, CC BY 4.0).
mkdir -p corpora/chat
curl -sSfL -o corpora/chat/tc.json "https://raw.githubusercontent.com/alexa/Topical-Chat/master/conversations/train.json"
curl -sSfL -o corpora/chat/tm1.json "https://raw.githubusercontent.com/google-research-datasets/Taskmaster/master/TM-1-2019/self-dialogs.json"
curl -sSfL -o corpora/chat/spc.csv "https://huggingface.co/datasets/google/Synthetic-Persona-Chat/resolve/main/data/Synthetic-Persona-Chat_train.csv"
"${PYTHON:-$(command -v python || command -v python3)}" prep_chat.py corpora/chat
echo "corpora ready in model/corpora"
