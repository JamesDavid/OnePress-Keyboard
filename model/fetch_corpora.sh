#!/usr/bin/env bash
# Downloads the public NLTK corpora and the NUS SMS corpus used to build the word-pair model into model/corpora/.
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p corpora
for c in brown webtext gutenberg movie_reviews names; do
  curl -sSfL -o "/tmp/$c.zip" "https://raw.githubusercontent.com/nltk/nltk_data/gh-pages/packages/corpora/$c.zip"
  unzip -qo "/tmp/$c.zip" -d corpora
done
# NUS SMS Corpus (Chen & Kan 2013): real text messages, split into train/dev/test by prep_nus.py.
mkdir -p corpora/nus
curl -sSfL -o corpora/nus/en.zip "https://raw.githubusercontent.com/kite1988/nus-sms-corpus/master/smsCorpus_en_xml_2015.03.09_all.zip"
unzip -qo corpora/nus/en.zip -d corpora/nus
echo "corpora ready in model/corpora"
