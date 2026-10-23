#!/usr/bin/env bash
# Downloads the public NLTK corpora used to build the word-pair model into model/corpora/.
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p corpora
for c in brown webtext gutenberg movie_reviews names; do
  curl -sSfL -o "/tmp/$c.zip" "https://raw.githubusercontent.com/nltk/nltk_data/gh-pages/packages/corpora/$c.zip"
  unzip -qo "/tmp/$c.zip" -d corpora
done
echo "corpora ready in model/corpora"
