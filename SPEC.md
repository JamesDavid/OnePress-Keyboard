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
| Held-out evaluation | `tests/eval.js`, `model/prep_nus.py` | NUS SMS corpus split by user into train/dev/test. Tune on dev, report US/Canada test. |
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
- **Words run together:** when no word matches a word token (and its letters aren't all known from exact spelling or QWERTY), it's tried as 2 or 3 known words written as one: every split into parts of at least 2 keys, each part one of the 5 most frequent words for its keys that agree with any exact letters. Each part scores how likely it is to start (all but the last part) and to end (all but the first) such a word: its unigram plus the model's `cmpHead` / `cmpTail` lift. Two parts that form a known word pair also get 2 × the lift that pair gives the second word over its unigram (never negative: ice cream, football game). −2 nats per split. Up to 6 distinct spellings are offered, best first ("lollypops": lollyross, lollypops, jollyross, …), each scored like an unknown word in the beam, shown lowercase, and learned as one word on Send. Tokens of 4–24 keys only. C ids `OP_COMPOUND_ID` + rank (kind `OP_COMPOUND`); the parts are recomputed from the token when rendering.
  - `cmpHead` / `cmpTail` (int8 per word, 1/4 nat; `export_bin.py compound_lifts`): from every wordfreq word outside the model's vocabulary that splits into two vocabulary words, weighted by its zipf frequency − 1 and shared among its splits, P(starts one | word) smoothed toward the unigram with K = 0.03, stored as its log over the unigram. Files without them score parts by the unigram alone.
  - Tuned on held-out wordfreq compounds (6,981; the right word first / among the 6 offered): unigram + word pairs 20.8% / 49.7%, head/tail 37.3% / 67.9%. On 1,500 common two-word phrases typed without the space: 97.6% / 99.5% with word pairs only, 91.7% / 99.7% now (head/tail alone: 69.1%).
  - Effect on NUS test: phone model unchanged (94.14%), ESP32 model 92.77% → 93.17%, radio model 88.28% → 89.18% (words outside the smaller vocabularies rebuilt from pieces). Cost: 2 bytes per word (phone model +91 KB, ESP32 +40 KB, radio +10 KB).
- **QWERTY letters (`start.hint`):** a QWERTY keyboard sends keypad digits and passes the letters tapped. A word token where every press has its letter (up to 32) is matched letter by letter: each tapped letter may stand for itself or a neighboring QWERTY key, so the candidates are the words whose digits fit (found by walking the digits each tap allows, dropping prefixes no word starts with), each penalized −8 nats per letter on a neighboring key and −24 nats per letter only on the same keypad key; the 40 best by unigram plus that penalty, and while typing the 12 best completions. Learned words get the same penalty. When no word matches, it's shown with the tapped letters and learned on Send like an exactly spelled word. `tests/qwerty_eval.js` types each NUS test message with a given share of letters on a neighboring key: words right, before → now, perfect typing 95.0% → 99.6%, 3% slips 83.6% → 98.7%, 10% slips 65.5% → 96.5% (penalties tuned on dev).

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
- **Decoding** (`start.nn`; C `op_nn_open`, `start.nn` + `start.nn_work`): the network reads BOS and the current line of `start.before`; each hypothesis carries its state; every word candidate gets `weight/256 ·` its log-probability (weight 320 = 1.25; numbers, unknown and learned words score as UNK). Punctuation is left to the rules (the network voted worse on NUS texts). Hypotheses are still merged by the word model's state and the best of each keeps its own network state: keeping them all apart crowded the beam and cost accuracy.
- **Cost:** ~0.3M multiply-adds per kept hypothesis per word (beam 8 → ~2.4M), plus one 128-wide dot product per candidate. `op_nn_work` is ~38 KB. `-DOP_NO_NN` compiles it out.
- **Effect** (held-out NUS): US/Canada words 94.14% → 95.14%, ambiguous 92.12% → 93.48%, punctuation 49.8% → 50.6%; all users words 91.84% → 93.16%, punctuation 59.4% → 58.5%. With learning, US/Canada words 95.67%.
- **Why not a pretrained model:** rescoring the decoder's alternatives with distilgpt2 (82M) or SmolLM2-135M gave similar gains (`tests/nn_export.js`, `tests/nn_rerank.py`), but at 15–20× the size; the 6M network beats distilgpt2 on all NUS users because it saw texting in training.

---

## 4. Web app behavior (reference UI)

`web/keypad.html` is the behavioral reference for any port.

- **LCD-style display:** fixed height, auto-scrolls. Shows the decoded sentence, ghost text for the current completion, and the raw key string.
- **Tap a word** to select it. The chip row shows the alternatives for the selected word (default: the last slot), each ranked by re-decoding the whole sentence with that word locked. Tapping a chip locks it, and a lock survives as long as that slot's keys are unchanged. Completion chips append the remaining keys and lock the full word.
- **Two layouts, toggled and remembered in localStorage:**
  - **Phone keypad:** 3×4. `1` is ⌫, `*` is next/hold-autocomplete, `#` is punctuation/hold-exact.
  - **QWERTY:** letters send their digit. Rows end with next (`*`) and the punctuation key on the Z row, and space plus delete on the bottom row. Letter keys **scale** (0.78×–1.38×) around their own center by next-letter probability, with z-order by scale. Sizes come from summing `P(word|prev)` over words matching the current keys, or from the bigram row mixed with first-letter frequencies at a word start.
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
