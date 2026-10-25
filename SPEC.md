# OnePress — Spec

**OnePress** is one-press-per-letter text entry. The user presses each phone-keypad key once per letter (2 = abc, 3 = def, …) and a language model decides which letters were meant, using sentence context. The same decoder sits behind a phone keypad, a QWERTY keyboard that only sends each letter's keypad number, and (later) physical keypads such as handheld radios.

## Name and branding

- **Product name:** OnePress. Use it for the app display name, the keyboard name in Settings, Xcode targets (`OnePress` app, `OnePressKeyboard` extension), and Swift module names.
- **Bundle IDs:** `$(BASE_BUNDLE_ID)` for the app and `$(BASE_BUNDLE_ID).keyboard` for the extension, with `BASE_BUNDLE_ID = com.CHANGEME.onepress` set once in `project.yml`. The user replaces `CHANGEME` with something unique, since free Apple IDs need globally unique bundle IDs.
- **Never use "T9"** in any user-facing name, string, icon or App Store text. It's a registered trademark. "Predictive keypad" or "one press per letter" describe the feature fine. Internal identifiers that still say `t9` should be renamed when touched.
- **Fallback names** if OnePress collides (it's common for WordPress plugins and print shops): Monotap, Oneshot. Run a trademark check (class 9) and an App Store name check before any public release.

This file is the hand-off for Claude Code. Read it first, then `web/decoder.js` (the reference implementation) and `c/onepress.c` (the portable port that must match it).

---

## 1. Current state

| Piece | Path | Status |
|---|---|---|
| Web app (working) | `web/keypad.html` | Done. Self-contained page (decoder + the three models base64-inlined) that works offline, even opened as a file. The GitHub Pages `index.html` (`web/build_page.py --lazy`, ~95 KB) has only the decoder and fetches each model when first picked, and the network only for the Phone model with Neural on. |
| Web source | `web/page.template.html`, `web/decoder.js` | Template has `__DECODER__`, `__MODEL_*__`, `__SIZE_*__` and `__WORDS_*__` placeholders; `web/build_page.py` (run by `model/build.sh`) fills them. `decoder.js` is the reference decoder. |
| C decoder | `c/onepress.h`, `c/onepress.c` | Done. C99, no allocation, reads the model in place. Output identical to `decoder.js` (`tests/parity.js`). For iOS (call from Swift), Android (NDK) and firmware. |
| Model pipeline | `model/` | Done. `build.sh` builds `model.json` (counts) and three KPD2 models: `onepress.bin` (45k words, three-word context, phones/web), `onepress-m.bin` (20k, ESP32), `onepress-s.bin` (5k, radios/nRF52). Data and licenses: `DATA.md`. |
| Held-out evaluation | `tests/eval.js`, `model/prep_nus.py`, `model/prep_chat_test.py` | NUS SMS corpus split by user into train/dev/test (texting, with its shorthand). Tune on dev, report US/Canada test. Second test set: Topical-Chat's official test splits (modern written chat, `test_chat.txt`, 15,653 messages), which nothing trains on; its validation splits are `dev_chat.txt`. Unlike the NUS files it keeps words the model lacks; `--oov-exact` spells those in exact mode and scores the rest. |
| Python LLM decoder | `python/keypad_decode.py` | Written, logic tested with a toy LM. **Never run against a real Hugging Face model.** |
| iOS keyboard extension, container app, Xcode project | — | **Not started.** Needs a Mac. Use the C decoder (the old Swift port was removed). |
| Android keyboard | — | Not started. Buildable on Windows; would use the C decoder via the NDK. |
| Regression test | `tests/decoder_test.js` | Small sanity set (16/20); overlaps `messages.txt`, so not a score. |

---

## 2. Input encoding

Keypad: `2 abc · 3 def · 4 ghi · 5 jkl · 6 mno · 7 pqrs · 8 tuv · 9 wxyz`

| Key | Meaning |
|---|---|
| `2`–`9` | One press per letter (predictive). |
| `0` | Space. |
| `#` | Punctuation; the model picks `. , ! ?`. **Between two word characters it is an apostrophe** (`366#8` → don't). |
| `1` | Delete (UI action, never stored). |
| `*` | Tap: swap the selected word for the next guess. Hold: autocomplete the current word and add a space. |
| Hold `#` | Toggle exact (multi-tap) spelling mode. |
| Hold `0`–`9` | Type that digit (stored as `A`–`J`). Hold `1` gives "1"; a tap still deletes. |

Apostrophes are optional: `3668` also yields "don't". A stripped-apostrophe match gets a `log(0.5)` penalty so "in" beats "I'm" for `46` when context is neutral.

### Internal key string

All input is stored as one string; the decoder re-tokenizes it on every change. Characters:

- `2`–`9`, `0`, `#` — predictive presses as above.
- From exact mode or a held number key: literal `a`–`z`, `'`, `.`, `,`, `?`, `!`, `:`, and `A`–`J` for the digits 0–9.

Tokenizer rules (`tokenize` in decoder.js):
- Letter characters: `2`–`9`, `a`–`z`, `'`. Consecutive letter characters form one word token with `keys` (the keypad digits) and `lit[]` (the exact character per position, or null).
- `0` → space token. Literal `. , ? !` → punctuation token with a fixed value. A literal `:` outside a number is shown as typed.
- Predictive `#` → apostrophe if the previous token is a word and the next character is a letter character, else a punctuation token.
- Digits (`A`–`J`) end a word and start a **number** token, so "4" + `3837` is "4ever" and the letters are decoded on their own. A number continues through more digits and through `#`, `.`, `,` or `:` followed by a digit. A predictive `#` right before a number (at the start, after a space or after punctuation) is `$`.
- A predictive separator `#` inside a number becomes `,` when the groups read as thousands (first group 1–3 digits, then groups of 3, optionally a last group of another length), else `.`: `#6#000#00` → "$6,000.00", `1#500` → "1,500", `3#14` → "3.14", `192#168#1#1` → "192.168.1.1". Literal `.` and `,` stay as typed.
- Digits stay inside a word when they follow an exactly spelled letter, and pure digits followed by an exactly spelled letter become one word, so call signs typed in exact mode work: `ke7aqa`, `2e0abc`, "90's".
- A number scores 0. One that reads as a time (`H#MM`, H ≤ 24, MM ≤ 59) has two candidates, "H.MM" and "H:MM", so both are offered: the time gets +2 nats after at, by, until, til, till, around, before, after, from or since, and −2 otherwise; "am"/"pm" right after a number or time get +8 nats. So "at 5:30", "5:30pm" and "9:45 am", but "5.30" alone, with 5:30 one tap away. An exactly typed `.` makes the time only an alternative (−14 more); an exactly typed `:` makes it a time.

### Exact (multi-tap) mode

Repeated presses of one key within 900 ms cycle: `2` → a, b, c, 2; `7` → p, q, r, s, 7; `0` → space, 0; `#` → `. , ? ! ' :`. A pause or a different key starts the next character. On QWERTY, exact mode types the tapped letter literally. Exact and predicted words mix freely. A partly-exact word only matches dictionary words that agree with the exact letters. A fully exact word not in the dictionary is offered as typed with a fixed score of −14.

---

## 3. Model

Word unigram + bigram (+ trigram on the phone model), about 45,000 words.

- **Vocabulary:** top English words from `wordfreq` (regex `^[a-z]+('[a-z]+)?$`), plus curated proper nouns (`model/data/proper.txt`: brands, apps, stores, places, days, months) and first names from the NLTK names corpus.
- **Bigrams:** counted from chat text (Topical-Chat, Taskmaster-1, Synthetic-Persona-Chat; `model/prep_chat.py`), Gutenberg prose and movie_reviews from NLTK, the NUS SMS training split (×3, US/Canada ×10), and `model/data/messages.txt` (hand-written everyday texts, ×25). Pruned to pairs seen at least twice. Punctuation `. , ! ?` are tokens; after `. ! ?` the context resets to BOS. (Brown and webtext were dropped for their terms; see `DATA.md`.)
- **Trigrams (phone model):** word triples for word pairs seen at least 12 times, kept when seen twice and with a weighted count ≥ 6, at most 65,000 contexts. `P(c|a,b) = λ·n(a,b,c)/n(a,b) + (1−λ)·P(c|b)` with the stored pair model as `P(c|b)` and `λ = n/(n+40)`, plus a backoff weight per context. The beam state includes the three-word context, so hypotheses merge only when it's the same.
- **Capitalization (`display`):** curated casing wins (iPhone, McDonald's, YouTube) unless the word is mostly lowercase in the cased corpora (target, chase, switch stay lowercase). Otherwise a word is capitalized if it's capitalized more than 75% of the time mid-sentence. "mcdonalds" (no apostrophe) displays as McDonald's.
- **Context casing:** for words written both ways (may/May, will/Will, bill/Bill), pairs after which (`capKey`, "in May") or before which (`capNextKey`, "Will Smith") the other casing is likelier, from counts pulled toward the word's overall ratio by 4 made-up sightings; and pairs before which the usual casing wins whatever the previous word says (`capKeepKey`, "like apple pie"). Not in the radio model.
- **Call signs** (1–2 letters, a digit, 1–4 letters; or digit, letter, digit, 1–3 letters) are shown in capitals: KE7AQA, 2E0ABC.
- **Scoring:** `log P(cur|prev) = log(λ·c(prev,cur)/c(prev) + (1−λ)·P_uni(cur))`, with `λ = c(prev)/(c(prev)+40)`.
- **Punctuation heuristic:** if the sentence's or clause's first word is a question opener (`QUESTION_STARTERS`), `?` gets +2.5 and `.` gets −1.5. Otherwise `?` gets −1.5. A final `,` gets −3. Greetings and fillers (`QUESTION_SKIP`: hello, hi, hey, ok, so, well, lol, …) are skipped when finding the first word, so "Hello how are you" is a question.
- **Search:** beam search over slots (words and punctuation), width 8. The last word in progress also gets up to 12 prefix completions, penalized `log(0.5)` and shown as ghost text.
- **Finished sentences are frozen:** at a punctuation slot with more typed after it, the decoder takes what it showed when the keys stopped there (the end-of-message comma penalty included). If that ended the sentence (`. ! ?`), only hypotheses with those words continue; the mark itself stays open, so a later word can still turn it into a comma. Words before a sentence end could only change through that choice anyway, so accuracy is unchanged.
- **Context from the text before (`start.before`):** the text already in the field, or the last few messages one per line. Its last words are the starting context (word pair and triple), it decides capitalization, it carries an unfinished sentence's opener (for `?`), and words in its last 32 words get +3 nats unless they're among the most common (log P above −9). A line break ends a sentence. Replaying NUS users with their previous 3 messages: +0.4 points of words without learning, +0.06 with it (their own words are already favored by learning).
- **Keypad slips:** a keypad word of 3+ keys (no exact letters or QWERTY taps) that no dictionary or learned word matches gets the words one slip away: one press replaced by a neighboring letter key on the keypad grid (2: 3 5; 5: 2 4 6 8; …), penalty `slipSub` (−12 nats), or one doubled press removed, `slipDup` (−8 nats); the 8 best by unigram plus penalty. Both are optional model params (0 leaves that kind out; older files get the defaults). Only when nothing matches: offered next to real matches, slips to common words beat the right rarer ones, which cost 0.9 points of the learning replay. Words that still match nothing go on to words run together. NUS test, words right with 3% of presses on a neighboring key / pressed twice, before → now: phone 82.3% → 87.2% / 81.3% → 88.9%, ESP32 81.6% → 86.7% / 80.7% → 89.1%, radio 78.4% → 84.1% / 77.5% → 86.1% (`tests/eval.js --slip 0.03`, `--double 0.03`). Accurate typing: phone unchanged, ESP32 −0.07, radio −0.18 points (a slip word now and then takes the place of words run together).
- **Words run together:** when no word matches a word token (and its letters aren't all known from exact spelling or QWERTY), it's tried as 2 or 3 known words written as one: every split into parts of at least 2 keys, each part one of the 5 most frequent words for its keys that agree with any exact letters. Each part scores how likely it is to start (all but the last part) and to end (all but the first) such a word: its unigram plus the model's `cmpHead` / `cmpTail` lift. Two parts that form a known word pair also get 2 × the lift that pair gives the second word over its unigram (never negative: ice cream, football game). −2 nats per split. Two parts that wordfreq knows written as one get +10 nats: every split of a wordfreq word outside the vocabulary into two vocabulary words, down to a zipf frequency (`export_bin.py --known-compounds ZIPF`), stored as a Bloom filter (`cmpBloom`: about 10 bits a pair, 7 hashes, under 1% false positives, which only ever add the bonus to a split of a word nothing else matches; older files have the sorted list `cmpKnown`). The phone and ESP32 models list them down to zipf 1.1 (158k pairs, 197 KB on the phone model). `--compound-parts ZIPF` keeps, in a model cut to `--vocab` words, the words that make up those compounds too, as plain words with no word pairs: the ESP32 model keeps 9,434 ("lolly" among them), 29,434 words in all. Up to 6 distinct spellings are offered, best first ("lollypops": lollypops, lollyross, jollyross, … on the phone and ESP32 models; without the list lollyross came first), each scored like an unknown word in the beam, shown lowercase, and learned as one word on Send. Tokens of 4–24 keys only. C ids `OP_COMPOUND_ID` + rank (kind `OP_COMPOUND`); the parts are recomputed from the token when rendering.
  - `cmpHead` / `cmpTail` (int8 per word, 1/4 nat; `export_bin.py compound_lifts`): from every wordfreq word outside the model's vocabulary that splits into two vocabulary words, weighted by its zipf frequency − 1 and shared among its splits, P(starts one | word) smoothed toward the unigram with K = 0.03, stored as its log over the unigram. Files without them score parts by the unigram alone.
  - Tuned on held-out wordfreq compounds (6,981; the right word first / among the 6 offered): unigram + word pairs 20.8% / 49.7%, head/tail 37.3% / 67.9%. On 1,500 common two-word phrases typed without the space: 97.6% / 99.5% with word pairs only, 91.7% / 99.7% now (head/tail alone: 69.1%).
  - Effect on NUS test: phone model unchanged (94.14%), ESP32 model 92.77% → 93.17%, radio model 88.28% → 89.18% (words outside the smaller vocabularies rebuilt from pieces). Cost: 2 bytes per word (phone model +91 KB, ESP32 +40 KB, radio +10 KB).
- **Letter keyboards (`start.hint`, `start.layout`):** a QWERTY (or any letter) keyboard sends keypad digits and passes the letters tapped, in any script (one per press, lowercased through the letter table), and its layout: the letter rows, top to bottom, `|` between them (default English QWERTY; German `qwertzuiopü|asdfghjklöä|yxcvbnm`, French AZERTY, Russian `йцукенгшщзхъ|фывапролджэ|ячсмитьбю`, ...). Row r is shifted right by r/2 key; two keys neighbor when they are one apart in a row or touch in the next row (for English QWERTY that is exactly the old hand-made table). A word token where every press has its letter (up to 32) is matched letter by letter: each tapped letter may stand for itself or a neighboring key, so the candidates are the words whose digits fit (found by walking the digits each tap allows, dropping prefixes no word starts with), each penalized −8 nats per letter on a neighboring key and −24 nats per letter only on the same keypad key; a plain tapped letter matches its accented forms free (e on é, α on ά), and a word letter the keyboard has no key for is compared through its plain letter. The 40 best by unigram plus that penalty, and while typing the 12 best completions. Learned words get the same penalty. When no word matches, it's shown with the tapped letters and learned on Send like an exactly spelled word. `tests/qwerty_eval.js [--layout rows]` types each test message on the layout with a given share of letters on a neighboring key: English NUS words right, perfect typing 95.0% → 99.7%, 3% slips 83.6% → 98.7%, 10% slips 65.5% → 96.8% (penalties tuned on dev); other languages in the table below.

### Files

- `model.json` (≈3.2 MB): `words`, `display` {idx: string}, `logp`, `punct`, `punctLogp`, `bos`, `ctx` {row: total}, `bi` {prev: [next, count, …]}. Token ids: words `0..n-1`, punctuation `n..n+3`, BOS `n+4`.
- `onepress.bin` / `-m` / `-s`: the KPD2 binary every decoder reads. The layout is documented at
  the top of `model/export_bin.py`. Log-probs are int16 (1/256 nat) with interpolation and
  backoff precomputed, so decoding is binary searches and integer adds, and JS and C agree exactly.

### Known model weaknesses

The model sees at most the two previous words (one on the smaller models), so some keypad collisions need more context than that; the optional neural model below reaches further. Examples: "keys"/"jews" (fixed via messages.txt), "cat"/"act", "Tempe"/"tense", "Good morning. How" vs ", how". Improving the model is milestone M5.

### Learning from the user

Each person gets a small fixed-size table (`newUser` / `learn` in decoder.js, `op_user` / `op_learn` in C) that decode reads through `start.user`. It is updated from text the person accepts (sent), not from every keystroke.

- **Learned words:** a word spelled exactly, typed on QWERTY with no word matching, or accepted as known words run together (letters, apostrophes and digits, up to 23), that the dictionary lacks is added. It keeps the casing it is given: an app can change it (the web page's Aa), and matching ignores case. From then on it is matched from its keys like a dictionary word, as an exact candidate and as a completion (up to 4 of each per slot).
- **Call signs:** in a learned word a digit 2–9 counts as its own key and 0/1 as the held digit, so `ke7aqa` can be typed `537272` (one press each) or with the 7 held. Holding a digit normally splits the word (`53`, `7`, `272`); a run of word and number tokens with nothing between them that spells a learned word is joined back into that word (the last run may be its beginning, offered as a completion). The exact characters must still agree: a held 7 never matches a p. Learned word k has id `bos + 1 + k`, with base log-prob −10 nats and no bigram row. When the table is full (256 words), the least used word is replaced and its pairs dropped.
- **Counts:** for every accepted token (dictionary word, learned word or punctuation) its own count and the count of the (previous token, token) pair, with the same context rules as decoding (BOS after `. ! ?`; numbers, unknown words and unfinished completions break the chain). Up to 1024 entries, sorted for binary search. When full, every count is halved and zeros dropped.
- **Scoring:** the model score plus `4·ln(1+c)` nats for the token's count and `3·ln(1+c)` for the pair's count (c capped at 15), as integer tables shared by both decoders. Tuned on the NUS dev users.
- **Storage:** about 12 KB in RAM by default, about 3 KB with `-DOP_USER_WORDS=64 -DOP_USER_PAIRS=256`. Saved as bytes by `op_user_save` / `saveUser` (identical in C and JS): `"KPU1"`, u16 version 1, u16 bos, u16 nWords, u16 nPairs, the words NUL-terminated, then each pair as u16 prev, u16 cur, u8 count, little-endian. `op_user_load` / `loadUser` refuse bytes for another model (other `bos`), another version or damaged ones; bytes from a build with larger limits load with the extra words (and their pairs) dropped and extra pairs halved away as learning does.
- **Effect** (`tests/learn_eval.js`, each user's messages replayed in order, unknown words spelled exactly the first time, learning each message as sent): NUS test users, predicted words 90.23% → 93.12% and punctuation 58.6% → 66.8%; US/Canada test users 94.18% → 95.27% and punctuation 49.5% → 62.7%.

### Neural word model (optional; phones and web)

`model/onepress-nn.bin` (KPN1, 6.3 MB): a GRU language model over the phone model's vocabulary (word ids, punctuation, BOS, UNK), embedding 128, hidden 256, output tied to the embeddings and trained to be self-normalized, so a word's log-probability is one dot product plus a bias. 6.2M parameters.

- **Training** (`model/train_nn.py`, PyTorch, ~35 min on an RTX 2070): the chat corpora, Gutenberg and movie reviews (one paragraph per line, `model/corpora/books.txt`), the NUS training split (×3, US/Canada ×6) and `messages.txt` (×20); each message starts at BOS, up to 40 tokens; 3 epochs, Adam, self-normalization penalty 0.1 · (log Z)². `model/export_nn.py` writes KPN1 (format at its top): int8 weights with a power-of-two scale per row, Q12 state, a stored sigmoid table, so the step is integer-only and C and JS agree exactly (`node tests/parity.js --nn model/onepress-nn.bin`).
- **Decoding** (`start.nn`; C `op_nn_open`, `start.nn` + `start.nn_work`): the network reads BOS and the current line of `start.before`; each hypothesis carries its state; every word candidate gets `weight/256 ·` its log-probability (weight 320 = 1.25; numbers, unknown and learned words score as UNK), and each punctuation mark `punctWeight/256 ·` its own (below). Hypotheses are still merged by the word model's state and the best of each keeps its own network state: keeping them all apart crowded the beam and cost accuracy.
- **Cost:** ~0.3M multiply-adds per kept hypothesis per word (beam 8 → ~2.4M), plus one 128-wide dot product per candidate. `op_nn_work` is ~55 KB (16 KB of it the states at the resume point). `-DOP_NO_NN` compiles it out.
- **Effect** (held-out, with the punctuation vote below): NUS US/Canada words 94.14% → 94.98%, ambiguous 92.12% → 93.26%, punctuation 49.8% → 55.4%; all NUS users words 91.84% → 93.07%, punctuation 59.4% → 58.7%; chat words 98.65% → 99.00%, punctuation 67.7% → 70.9%.
- **Small network** (`onepress-nn-s.bin`, 2.5 MB, 2.4M parameters): embedding 48, hidden 192, same training and export. Held-out US/Canada words 94.86%, punctuation 52.7%; chat words 98.94%, punctuation 70.2% (the 6.3 MB one: 94.98%, 55.4%, 99.00%, 70.9%; none: 94.14%, 49.8%, 98.65%, 67.7%). About a third of the work per step.
- **ESP32 network** (`onepress-nn-m.bin`, 1.7 MB, 1.5M parameters): the same small network trained on the ESP32 model's 29,434 words (its ids; `train_nn.py` takes any vocabulary JSON with words, punct and bos). With `onepress-m.bin`: NUS US/Canada words 94.05% → 94.37%, punctuation 47.1% → 49.7%; chat words 98.51% → 98.83%, punctuation 65.1% → 69.2%. About 0.14M multiply-adds per kept hypothesis per word, so a few milliseconds per word on a 240 MHz ESP32; `-DOP_NN_MAX=192` cuts `op_nn_work` to about 40 KB.
- **Where punctuation still goes wrong** (NUS US/Canada test, phone model with the network, 1,164 marks): a comma read as a period 158 times (texters run sentences together with commas), a question read as a statement 88 times (questions with no question word: "ready?", "going out tonight?"), an exclamation read as a period 89 times (mostly the writer's habit). Learning from the person fixes much of the last two (punctuation 58.6% → 66.8% on the NUS test users).
- **Punctuation:** each mark also gets `punctWeight/256 ·` its log-probability (KPN1 header offset 28; 384 = 1.5 in `onepress-nn.bin`, 0 in older files), on top of the punctuation rules. Tuned on NUS dev and chat dev: 0.5 to 1.5 all helped, 3 and above hurt. Held-out US/Canada: punctuation 50.6% → 55.4%, words 95.14% → 94.98% (the marks change the next word's context).
- **Why not a pretrained model:** rescoring the decoder's alternatives with distilgpt2 (82M) or SmolLM2-135M gave similar gains (`tests/nn_export.js`, `tests/nn_rerank.py`), but at 15–20× the size; the 6M network beats distilgpt2 on all NUS users because it saw texting in training.

### Other languages

`build_model.py --lang xx` builds a model for another wordfreq language: no English extras (Gutenberg, movie reviews, names, messages.txt), words may hold accented letters, and the text comes from the corpora given (cased). `export_bin.py` reads the language from model.json for its question openers, the words skipped before them, and the `flags` param. Both decoders read letters beyond a-z in a model's words from one generated table (`model/chartable.py` writes it into decoder.js and onepress.c; export_bin.py imports it): accented Latin (U+00C0–U+024F), Greek and Cyrillic (U+0370–U+045F). Each letter has its keypad key (Latin: its plain letter's, á → 2, ł → 5, ş → 7; Greek 2 αβγ 3 δεζ 4 ηθι 5 κλμ 6 νξο 7 πρσς 8 τυφ 9 χψω; Russian 2 абвг 3 деёжз 4 ийкл 5 мноп 6 рсту 7 фхцч 8 шщъы 9 ьэюя), the plain letter an exact or QWERTY letter matches (Latin only: exact mode has no accents, so `n` matches `ñ`), its capital (a sentence's first letter: é → É, ж → Ж), its small letter, which lowercases the text before the cursor the same way in both decoders (not the locale's rules: İ stays as it is), and for Greek and Cyrillic its plain letter (ά → α, ё → е). Greek words end in ς: wordfreq case-folds it to σ, so `build_model.py` puts it back. `flags`: 1 capitalizes "i" (English; older files), 2 opens a question or exclamation with ¿ / ¡ (Spanish), placed after a leading greeting or filler and its comma ("Hola, ¿qué tal?"), 4 shows the question mark as ; (Greek), 8 puts a narrow no-break space before ? ! : (French).

- **Models** from wordfreq plus Tatoeba's sentences in that language (`prep_tatoeba.py`: split by sentence id, 1 in 20 each to dev and test; `build_langs.sh` builds all three sizes). Held-out test, accents count ("como" for "cómo" is wrong):

  | Language | Phone (45k words) | ESP32 (20k) | Radio (5k) | Phone size | Spelled out (phone) | Punctuation (phone) | Classic keypad | Letter keyboard: accurate / 10% slips |
  |---|---|---|---|---|---|---|---|---|
  | Spanish (`es`) | 97.85% | 97.59% | 97.55% | 1.9 MB | 3.0% | 76.9% | 91.70% | 97.3% / 95.8% |
  | German (`de`) | 97.54% | 96.95% | 96.43% | 2.6 MB | 4.5% | 84.1% | 90.70% | 97.9% / 95.5% |
  | Portuguese (`pt`) | 98.19% | 97.87% | 97.58% | 1.8 MB | 1.9% | 78.8% | 92.82% | 97.4% / 95.6% |
  | French (`fr`) | 97.81% | 97.22% | 96.94% | 2.4 MB | 2.1% | 83.8% | 83.00% | 97.7% / 95.1% |
  | Italian (`it`) | 98.74% | 98.47% | 98.26% | 2.4 MB | 2.4% | 79.8% | 89.12% | 97.5% / 95.6% |
  | Dutch (`nl`) | 97.96% | 97.68% | 97.47% | 1.8 MB | 1.9% | 86.8% | 94.48% | 98.5% / 95.7% |
  | Swedish (`sv`) | 96.77% | 96.43% | 95.75% | 1.2 MB | 2.5% | 89.5% | 92.51% | 97.9% / 94.6% |
  | Polish (`pl`) | 96.61% | 96.30% | 96.10% | 1.4 MB | 6.7% | 84.9% | 91.86% | 94.2% / 91.6% |
  | Czech (`cs`) | 96.12% | 95.99% | 95.82% | 1.3 MB | 5.9% | 84.7% | 91.58% | 93.1% / 89.9% |
  | Turkish (`tr`) | 96.71% | 96.84% | 97.30% | 1.9 MB | 9.7% | 91.2% | 94.07% | 93.2% / 88.6% |
  | Russian (`ru`) | 97.61% | 97.20% | 96.92% | 2.9 MB | 6.2% | 78.4% | 87.26% | 92.4% / 90.9% |
  | Greek (`el`) | 96.98% | 96.70% | 96.31% | 1.5 MB | 4.2% | 74.7% | 94.87% | 92.3% / 90.5% |

  Words right on held-out Tatoeba sentences (`model/corpora/<lang>/test.txt`), the words a model lacks spelled out and not scored; the smaller sizes lack more of them, which is why Turkish's look better. The classic keypad is the phone model's word list, one word at a time (`tests/baseline.js`). The letter keyboard is the phone model on that language's layout (`tests/qwerty_eval.js --layout`), first 5,000 sentences, every word scored: an accented letter the keyboard has no key for is tapped as its plain letter (ą as a, ά as α, ё as е) and has to be restored, which is most of what Polish, Czech, Turkish, Russian and Greek lose there. Swedish and Greek have the least Tatoeba text (50k and 37k sentences); Turkish words come in many forms, so a 45k-word list misses more of them. Tatoeba sentences are short and tidy, so expect less on real chat.

  German nouns are capitalized from Tatoeba's casing.
- **Turkish endings:** a name's case ending follows an apostrophe (Tom'a, Ankara'da). The Turkish model has the endings ('a 'e 'da 'de 'ın 'nin ...) as words, its text is split before them, and both decoders split `tom#a` (no word matching it whole) into a word and an ending that starts with an apostrophe, shown joined.
- **Elision (French, Italian):** wordfreq counts "l'homme" as l + homme, so the French model has the elided words (l' d' j' qu' n' s' c' m' t' jusqu' lorsqu' puisqu' quoiqu' presqu'; Italian l' un' dell' all' c' dov' quest' ...) as words of their own, and `build_model.py` splits its text the same way. Both decoders split a word typed with an apostrophe (`l#homme`) that no dictionary or learned word matches whole into the elided word (a dictionary word ending in an apostrophe whose keys and exact letters fit the part up to the first `#`) and the rest, decoded as two words with no space between and shown joined ("L'homme est là.", "Il m'a dit qu'il viendrait."). Words whole with their apostrophe (aujourd'hui, quelqu'un) stay whole; models without elided words never split. The apostrophe has to be typed in French (it's optional in English, where "dont" finds "don't"). œ is typed and shown as oe.
- **Hyphen words (French, Portuguese):** words that attach with a hyphen (French -ce -je -tu -il -elle -on -nous -vous -moi -t ...: est-ce, a-t-il; Portuguese clitics -me -te -se -lhe -o -a ...: dá-me, chama-se; `model/langdata.py`) are words of their own; `prep_tatoeba.py` keeps a hyphen only before one of them (any other becomes a space) and `build_model.py` splits the text before them. `-` is on the `#` key like the apostrophe, so `est#ce` splits into est + -ce, and `a#t#il` into a + -t + -il, shown joined. Other hyphenated words (peut-être, guarda-chuva) are typed and come out as two words.
- **Exact spelling in any script:** an exactly spelled letter may be any letter of the table (a Russian or Greek multi-tap gives its own letters; accented Latin too), stored as its code point (C: `op_decoder.lits` is `uint16_t`). A plain exact letter matches its accented forms (n matches ñ, α matches ά); an accented one only itself. A word the model lacks, spelled exactly in Cyrillic or Greek, is shown and learned in its own letters (learned words are UTF-8, up to 23 bytes).
- **French spacing:** flag 8 puts a narrow no-break space (U+202F) before ? ! : (French).
- **Not yet:** other hyphenated words come out as two words, since the keypad has no hyphen; scripts beyond U+07FF and without one-letter-per-key typing (Chinese and Japanese are typed through phonetic input and character choice; Indic scripts need conjuncts) are outside this design; Arabic would need its keypad table and right-to-left handling.

### Speed

Decoding is cheap: on a desktop CPU a 212-press, four-sentence message costs under 0.07 ms per press on average (C, beam 8, process start included), so a 64 MHz nRF52, perhaps 100–200 times slower, needs about 5–10 ms per press.

**Resuming after a finished sentence.** Typing one key at a time, each call gets the whole key string again. After a slot that ends a sentence and has a space and more after it, both decoders keep the search state (`m.resume` in JS; `op_decoder.rs`, plus the network states in `op_nn_work`, in C). The next call resumes from there when its keys and QWERTY letters start with the same keys up to that space, and the start (text before, prev, cap, user and its stamp/version, network), the locks up to that slot, the model and the beam are unchanged; the search up to there would come out the same, so the result is identical (`tests/resume_test.js` types messages of several sentences one key at a time and compares every prefix with a decode from scratch, in JS and C, with learning, QWERTY letters and the network). A call that doesn't resume drops the saved state (C reuses its back-pointers). Learning bumps the user's stamp (C, a process-wide counter) or version (JS), so a resumed search never uses an outdated table. C phone model: 0.092 → 0.068 ms per press on that message; JS still builds every slot's candidates (the page shows them), so it gains less.

---

## 4. Web app behavior (reference UI)

`web/keypad.html` is the behavioral reference for any port.

- **LCD-style display:** fixed height, auto-scrolls. Shows the decoded sentence, ghost text for the current completion, and the raw key string.
- **Tap a word** to select it. The chip row shows the alternatives for the selected word (default: the last slot), each ranked by re-decoding the whole sentence with that word locked. Tapping a chip locks it, and a lock survives as long as that slot's keys are unchanged. Completion chips append the remaining keys and lock the full word.
- **Two layouts, toggled and remembered in localStorage:**
  - **Phone keypad:** 3×4. `1` is ⌫, `*` is next/hold-autocomplete, `#` is punctuation/hold-exact.
  - **Letter keyboard:** the selected language's national layout (QWERTY, QWERTZ, AZERTY, Russian, Greek, ...; passed to the decoder as `layout`), arranged like the iOS keyboard: on the last letter row next (`*`, hold: finish the word) where iOS has shift and delete at the end; then 123, space, and the punctuation key where iOS has return. 123 shows the iOS numbers and symbols: digits (typed exactly) and . , ? ! ' : work, the others are shown dimmed. Letters send their digit. The keypad's labels and exact-mode cycles follow the language too (German 2 abcä, Russian 2 абвг), and Example shows sentences in it. Letter keys **scale** (0.78×–1.38×) around their own center by next-letter probability, with z-order by scale. Sizes come from summing `P(word|prev)` over words matching the current keys, or from the bigram row mixed with first-letter frequencies at a word start.
- **Computer keyboard:** letters map to digits, space → 0, punctuation → #, Backspace deletes, Tab autocompletes. In exact mode, letters and digits are typed literally.
- **Exact mode indicator:** accent outline on the display plus the tag "ABC · exact spelling".
- **Send** copies the text, learns from it (not from an untouched example) and clears. What it learned is kept in localStorage per model (`user-l`, `user-m`, `user-s`; a loaded file's isn't saved). A line under the model picker shows it, with **Forget** to clear it. The last 3 sent messages are passed as `start.before` (kept in localStorage `sent`, cleared by Forget too).
- **Aa chip:** shown when the selected word is a learned one; it switches its stored casing (keturah / Keturah).
- **Neural:** the page fetches `onepress-nn.bin` (next to it on GitHub Pages, else `../model/`) and uses it with the Phone model; the Neural checkbox turns it off (remembered).
- **Model names:** each model is named for the hardware it stands for (Phone / web, ESP32 / Meshtastic, nRF52 / radio), so people can try what each device would do.
- **Number chips:** a number that can be a time shows 5.30 and 5:30.
- **Tutorial:** seven steps, each checked against the display, started on the first visit and from the Tutorial link. During it only the tutorial card, display, keypad and buttons show (guesses only on the step that uses them).
- **One screen:** keyboard and tutorial fit without scrolling down to 360×640 (spacing and key sizes follow the viewport height). `tests/fit.html` (serve the repo root, open it in a browser) checks every tutorial step at several sizes.

---

## 5. Python LLM decoder (`python/keypad_decode.py`)

This version uses token-level constrained beam search with any Hugging Face causal LM. Every vocabulary token is pre-encoded to keys, and at each key position only tokens whose keys match the next digits are allowed. Hypotheses are compared only against others that consumed the same number of keys. The default model is `Qwen/Qwen2.5-1.5B`; `--model` takes any other.

**Outdated mapping:** it still uses `1` = apostrophe and `#` = punctuation only. Update it to match section 2: `#` between letters is an apostrophe, and apostrophes are optional.

The target machine is the user's local inference box (two RTX 3090s), so 7B models are fine there.

---

## 6. iOS keyboard (main work item)

### Constraints

- **No paid developer account.** It's built with Xcode and a free Apple ID (Personal Team), which means:
  - The app expires after 7 days on device, and re-running from Xcode re-installs it.
  - App Groups are not available on a free team, so **the keyboard must not depend on sharing data with the container app.** Bundle the model inside the extension and keep settings in the extension's own `UserDefaults.standard`.
  - Bundle IDs must be globally unique; use one configurable prefix.
- **Keyboard extension memory limit:** keep resident memory well under about 40 MB. The bigram model fits (about 3 MB on disk). Don't load anything large.
- `RequestsOpenAccess = false`. No network.
- **Required by Apple:** a globe key when `needsInputModeSwitchKey` is true. `advanceToNextInputMode()` on tap is acceptable.

### Project layout

Use XcodeGen (`brew install xcodegen`, then `xcodegen` in `ios/`) so the project file is generated rather than hand-edited.

```
ios/
  project.yml                 # OnePress app + OnePressKeyboard extension, iOS 16+, BASE_BUNDLE_ID setting
  App/                        # SwiftUI container app: setup steps + a test text field
  Keyboard/
    (decoder)                 # c/onepress.{h,c} via a bridging header
    KeyboardState.swift       # composition, input handling, suggestions (ObservableObject)
    KeyboardView.swift        # SwiftUI drawing + UIKit multi-touch layer
    KeyboardViewController.swift
    Resources/onepress.bin    # copy of model/onepress.bin
```

Extension Info.plist `NSExtension`:
- `CFBundleDisplayName = OnePress` (app and extension)
- `NSExtensionPointIdentifier = com.apple.keyboard-service`
- `NSExtensionPrincipalClass = $(PRODUCT_MODULE_NAME).KeyboardViewController`
- `NSExtensionAttributes`: `IsASCIICapable = false`, `PrefersRightToLeft = false`, `PrimaryLanguage = en-US`, `RequestsOpenAccess = false`

### Text handling: the composition model

The decoder can change earlier words as more keys arrive, so the keyboard owns a **composition**: the key string since the last commit, plus the exact text it last inserted.

1. On every change, decode and render the new text. Find the common prefix with the previously inserted text, call `deleteBackward()` once for each character after it, then `insertText` the new tail.
2. Before each keypress, check that `documentContextBeforeInput` still ends with the inserted text. If it doesn't (the cursor moved or the app edited text), drop the composition without deleting anything and start fresh. Compare the shorter string as a suffix when context is truncated.
3. **Commit** (clear the composition and keep the text) after sentence-ending punctuation followed by a space, on Return, before inserting anything from the 123 or #+= pages, and when switching apps or keyboards.
4. **Start context** comes from `documentContextBeforeInput`:
   - Empty, or ending in `. ! ? \n` → BOS with first-word capitalization.
   - Ending in `,` → the comma's punctuation id.
   - Otherwise → the last word's id (or −1 if it's unknown), with no capitalization.
   
   `Decoder.decode` takes this as `StartContext`.
5. Delete with an empty composition calls `deleteBackward()` on the host.

### Keys and layouts

- **Letters (QWERTY):**
  - Row 1: `q w e r t y u i o p`
  - Row 2: `a s d f g h j k l` (centered)
  - Row 3: `⇧ z x c v b n m ⌫`
  - Row 4: `123 🌐 next space . , ' ? return`

  The 🌐 key appears only if needed. Each letter shows its digit in the corner, and letter keys scale as in the web app.
- **Phone keypad:** a 3×4 grid (`1`=⌫, `2`–`9`, `*`=next, `0`=space, `#`=punct) plus a fourth column: `⇧`, `123`, `🌐` (or blank), `return`.
- **Mode toggle:** a button at the left of the suggestion bar switches QWERTY and keypad, persisted in `UserDefaults.standard`.
- **123 page:**
  - Row 1: `1 2 3 4 5 6 7 8 9 0`
  - Row 2: `- / : ; ( ) $ & @ "`
  - Row 3: `#+= . , ? ! ' ⌫`
  - Row 4: `ABC 🌐 space return`
- **#+= page:**
  - Row 1: `[ ] { } # % ^ * + =`
  - Row 2: `_ \ | ~ < > € £ ¥ •`
  - Row 3: `123 . , ? ! ' ⌫`
  
  These pages insert characters literally after committing the composition.
- **Shift:**
  - One tap → the next word starts with a capital.
  - Double tap within 0.35 s → caps lock (whole words uppercase).
  
  Case is stored per word ordinal in the composition (`[Int: WordCase]`) and applied at render. Pruned on delete.
- **Return:** commit, then `insertText("\n")`.
- **Holds:** next (420 ms) → autocomplete. Punctuation key (420 ms) → toggle exact mode. Keypad layout digit keys (420 ms) → the digit itself, including `1`. QWERTY delete → repeat every 80 ms after 450 ms.
- **Suggestion bar** (about 40 pt): mode toggle, alternatives chips for the last slot (or the selected slot), and an "ABC" badge while exact mode is on.
- **Touch handling:** use a UIKit overlay view with `isMultipleTouchEnabled = true` so fast rollover typing works. Keep per-touch state, and hit-test against **scaled** key rects: the highest scale wins; otherwise pick the nearest key center. Act on touch-up, except holds and repeats.
- **Height:** about 260 pt total. Pin with a height constraint at priority 999.
- **Colors:** dynamic light/dark (`UIColor { traitCollection in … }`) close to the system keyboard: letter keys white or dark gray, function keys a darker tint.

### Milestones

1. **M1 — Compile.** Generate the project, add `c/onepress.c` through a bridging header, and add a unit test target that decodes the `tests/decoder_test.js` sentences. Results must match the JS output exactly.
2. **M2 — Minimal keyboard.** QWERTY sending digits, space, delete, return, globe, and the composition model working in Notes and Messages.
3. **M3 — Full UI.** Keypad layout, 123 and #+= pages, shift and caps lock, suggestion chips, next/autocomplete, exact mode, key scaling.
4. **M4 — Polish.** Key press popups, input clicks (`UIInputViewAudioFeedback`), and a load-time check (model load under 300 ms on device, cached in a static).
5. **M5 — Better model.** Options, roughly in order of payoff:
   - A trigram or pruned 4-gram (KenLM-style).
   - Learn from the user's own typing, stored locally.
   - Add `UILexicon` names and text shortcuts (available without full access).
   - A small on-device neural LM (Core ML, under ~30 MB) for re-ranking the top beam hypotheses.

   Measure each change with the regression test plus a held-out set of real messages.

### Acceptance checks

- Typing "can you pick up the kids after school" in Messages produces "Can you pick up the kids after school" with no leftover characters as earlier words change.
- Moving the cursor mid-composition and typing doesn't delete or alter text outside the cursor area.
- Memory stays under 40 MB in Xcode's debug gauge while typing quickly.
- Works in light and dark mode, and in both portrait and landscape.

---

## 7. Other targets (later)

- **Handheld radios** (DM-32UV, TIDRADIO H3 and similar): first confirm the MCU and free flash under the community firmwares (OpenDM32 / RA4FHE research for the DM-32UV; NicSure firmware for the TD-H3/H8). The decoder is cheap. Storage is the constraint: about 100 KB for a word list without pairs, a few hundred KB for a pruned bigram (`onepress-s.bin` is 238 KB), or external SPI flash for the full model. DMR text messaging is the natural use.
- **ESP32 or other embedded keypad devices:** the same binary format works from flash.

---

## 8. Rebuild and test

```bash
cd model && ./build.sh            # fetch corpora (first run), rebuild model.json, onepress{,-m,-s}.bin, web/keypad.html
node tests/eval.js                # held-out accuracy (NUS SMS, US/Canada users)
node tests/eval.js --slip 0.03    # ... with 3% of presses on a neighboring key (--double: pressed twice)
node tests/qwerty_eval.js --miss 0.1   # QWERTY, 10% of letters on a neighboring key
node tests/learn_eval.js model/corpora/nus/users_test.tsv   # learning from the user
gcc -std=c99 -O2 -o build/opdecode c/onepress.c c/opdecode.c && node tests/parity.js   # C matches JS
node tests/parity.js --learn      # C matches JS while learning
node tests/decoder_test.js        # small sanity set
python3 python/keypad_decode.py --model Qwen/Qwen2.5-7B   # LLM version (needs torch/transformers)
```
