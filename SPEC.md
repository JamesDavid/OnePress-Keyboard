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
| Web app (working) | `web/keypad.html` | Done. Single self-contained page: decoder + base64 model inlined. |
| Web source | `web/page.template.html`, `web/decoder.js` | Template has `__MODEL__` and `__DECODER__` placeholders; `model/build.sh` inlines them. `decoder.js` is the reference decoder. |
| C decoder | `c/onepress.h`, `c/onepress.c` | Done. C99, no allocation, reads the model in place. Output identical to `decoder.js` (`tests/parity.js`). For iOS (call from Swift), Android (NDK) and firmware. |
| Model pipeline | `model/` | Done. `build.sh` builds `model.json` (counts) and three KPD2 models: `onepress.bin` (45k words, phones/web), `onepress-m.bin` (20k, ESP32), `onepress-s.bin` (5k, radios/nRF52). |
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
- From exact mode: literal `a`–`z`, `'`, `.`, `,`, `?`, `!`, and `A`–`J` for the digits 0–9.

Tokenizer rules (`tokenize` in decoder.js):
- Word characters: `2`–`9`, `a`–`z`, `'`, `A`–`J`. Consecutive word characters form one word token with `keys` (the keypad digits) and `lit[]` (the exact character per position, or null).
- `0` → space token. Literal `. , ? !` → punctuation token with a fixed value.
- Predictive `#` → apostrophe if the previous token is a word and the next character is a word character, else a punctuation token.

### Exact (multi-tap) mode

Repeated presses of one key within 900 ms cycle: `2` → a, b, c, 2; `7` → p, q, r, s, 7; `0` → space, 0; `#` → `. , ? ! '`. A pause or a different key starts the next character. On QWERTY, exact mode types the tapped letter literally. Exact and predicted words mix freely. A partly-exact word only matches dictionary words that agree with the exact letters. A fully exact word not in the dictionary is offered as typed with a fixed score of −14.

---

## 3. Model

Word unigram + bigram, about 45,000 words.

- **Vocabulary:** top English words from `wordfreq` (regex `^[a-z]+('[a-z]+)?$`), plus curated proper nouns (`model/data/proper.txt`: brands, apps, stores, places, days, months) and first names from the NLTK names corpus.
- **Bigrams:** counted from NLTK Brown, webtext (minus nps_chat, which was excluded for content), Gutenberg prose, and movie_reviews, plus `model/data/messages.txt` (hand-written everyday texts, weighted ×25). Pruned to count ≥ 2. Punctuation `. , ! ?` are tokens; after `. ! ?` the context resets to BOS.
- **Capitalization (`display`):** curated casing wins (iPhone, McDonald's, YouTube) unless the word is mostly lowercase in the cased corpora (target, chase, switch stay lowercase). Otherwise a word is capitalized if it's capitalized more than 75% of the time mid-sentence. "mcdonalds" (no apostrophe) displays as McDonald's.
- **Scoring:** `log P(cur|prev) = log(λ·c(prev,cur)/c(prev) + (1−λ)·P_uni(cur))`, with `λ = c(prev)/(c(prev)+40)`.
- **Punctuation heuristic:** if the sentence's or clause's first word is a question opener (`QUESTION_STARTERS`), `?` gets +2.5 and `.` gets −1.5. Otherwise `?` gets −1.5. A final `,` gets −3.
- **Search:** beam search over slots (words and punctuation), width 40. The last word in progress also gets up to 12 prefix completions, penalized `log(0.5)` and shown as ghost text.

### Files

- `model.json` (≈3.2 MB): `words`, `display` {idx: string}, `logp`, `punct`, `punctLogp`, `bos`, `ctx` {row: total}, `bi` {prev: [next, count, …]}. Token ids: words `0..n-1`, punctuation `n..n+3`, BOS `n+4`.
- `onepress.bin` / `-m` / `-s`: the KPD2 binary every decoder reads. The layout is documented at
  the top of `model/export_bin.py`. Log-probs are int16 (1/256 nat) with interpolation and
  backoff precomputed, so decoding is binary searches and integer adds, and JS and C agree exactly.

### Known model weaknesses

The model only sees the previous word, so some keypad collisions need more context than that. Examples: "keys"/"jews" (fixed via messages.txt), "cat"/"act", "Tempe"/"tense", "Good morning. How" vs ", how". Improving the model is milestone M5.

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

- **Handheld radios** (DM-32UV, TIDRADIO H3 and similar): first confirm the MCU and free flash under the community firmwares (OpenDM32 / RA4FHE research for the DM-32UV; NicSure firmware for the TD-H3/H8). The decoder is cheap. Storage is the constraint: about 100 KB for unigram-only T9, a few hundred KB for a pruned bigram, or external SPI flash for the full model. DMR text messaging is the natural use.
- **ESP32 or other embedded keypad devices:** the same binary format works from flash.

---

## 8. Rebuild and test

```bash
cd model && ./build.sh            # fetch corpora (first run), rebuild model.json, onepress{,-m,-s}.bin, web/keypad.html
node tests/eval.js                # held-out accuracy (NUS SMS, US/Canada users)
gcc -std=c99 -O2 -o build/opdecode c/onepress.c c/opdecode.c && node tests/parity.js   # C matches JS
node tests/decoder_test.js        # small sanity set
python3 python/keypad_decode.py --model Qwen/Qwen2.5-7B   # LLM version (needs torch/transformers)
```
