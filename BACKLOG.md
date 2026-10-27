# Backlog

## T-Echo Lite + KeyShield: OnePress in Meshtastic

Type Meshtastic messages on the LilyGO T-Echo Lite's KeyShield keypad with one press per letter,
decoded on the node by `c/onepress.c`.

### Hardware (checked 2026-10-27)

| | T-Echo Lite | Notes |
|---|---|---|
| MCU | nRF52840, Cortex-M4F 64 MHz | 1 MB flash, 256 KB RAM |
| External flash | ZD25WQ32 on QSPI | **4 MB** (32 Mbit; LilyGO's "32 MB" is megabits). Meshtastic's `variants/nrf52840/t-echo-lite/variant.h` defines `EXTERNAL_FLASH_USE_QSPI` |
| Display | 1.22" e-paper, 192×176 | Meshtastic builds it with dynamic e-ink, fast refresh limited to 20 in a row |
| Keypad | KeyShield: 5×4, 20 keys, phone-style, backlit | TCA8418 over I2C; also an ES8311 codec, a vibration motor, AW21009 backlight. Sold separately from the base unit |

### Memory budget

- Model in the external flash, read with `-DOP_EXT_MODEL` (the UV-K1 path), or memory-mapped
  through the nRF52840 QSPI XIP window (0x12000000), which would make it a plain pointer and need
  no read cache. XIP depends on Meshtastic not owning the QSPI peripheral; it currently doesn't
  use the external flash (meshtastic/firmware#10139, a QSPI LittleFS, was closed unmerged).
  - `onepress-m.bin` (1.54 MB, 94.05%) fits comfortably and is the default choice.
  - `onepress.bin` (3.53 MB, 94.14%) fits the 4 MB with about 0.5 MB to spare. That's only worth it if nothing else
    wants the chip.
- Decoder: about 21 KB of internal flash without the network and letter keyboards
  (`-DOP_NO_NN -DOP_NO_QWERTY`), about 11 KB of RAM at default limits plus a few KB of stack.
  Measure Meshtastic's free flash on the `t-echo-lite` env first: nRF52 builds are tight.
- The network (`onepress-nn-m.bin`, 1.67 MB) would also fit next to `onepress-m.bin`; speed on a
  64 MHz M4F is unmeasured. Not in the first version.

### Plan

1. Fork meshtastic/firmware and build the `t-echo-lite` env unchanged. Record flash and RAM
   use.
2. KeyShield driver. Meshtastic already has `src/input/TCA8418Keyboard.cpp`, a 3×4 multi-tap phone
   keypad found by the I2C scan (`kbI2cBase.cpp`), plus 4×10 and larger layouts for other boards.
   Add a 5×4 KeyShield map (rows and columns from LilyGO's keyshield example) that sends raw
   keys, not multi-tap letters.
3. Copy `c/onepress.{c,h}` verbatim into the fork (as the UV-K1 port does; a sync check or
   script so they can't drift). A small service: keys → `op_decode` → text, guesses with
   `op_candidates`, held digit = the digit, an `ABC` multi-tap mode for names and call signs.
4. Hook it into the canned-message / free-text compose screen in place of multi-tap. Keep
   multi-tap as a setting.
5. E-paper: fast partial refresh for the compose line, redraw after a short pause rather than on
   every press if fast refreshes run out. A full refresh only when leaving compose.
6. Model upload: over BLE/serial with the Meshtastic admin channel, or a UF2/serial tool like
   `tools/onepress_upload.py`. Sector-compare so re-uploading is cheap.
7. Length: show bytes left against Meshtastic's text limit (about 200 bytes).
8. A PC simulator or a host unit test of the service, like `tools/onepress_sim` in the UV-K1 fork.

### Open questions

- **Licence.** Meshtastic is GPL-3.0, and the decoder is PolyForm Noncommercial. They can't be
  distributed in one binary. Options: license `onepress.{c,h}` (and the model's use) under
  GPL-3.0 for the Meshtastic fork, or keep it a private build. Decide before publishing anything.
- KeyShield key labels: which keys are 2–9, `*`, `#`, the arrows and OK/back.
- Does any Meshtastic build already drive the KeyShield? Search PRs for "keyshield" again before
  starting.
- Upstreaming vs a fork: upstream would need the licence settled and probably a smaller default
  model.

### Done when

- Typing "On my way home" on the KeyShield shows it, and it sends as a normal Meshtastic text.
- Guess cycling, delete, `ABC` and held digits work.
- Worst-case key press latency is measured on the device, along with the stack margin.
- Accuracy numbers come from `tests/eval.js` for the model shipped.

## Chinese (Mandarin, pinyin on the keypad)

Toneless pinyin, one press per letter (`4664` is hong / gong), decoded to characters with the
whole sentence picking the words. Phones once had pinyin keypads that made you pick characters
word by word. OnePress would choose them from the sentence.

### Status (2026-10-27)

Version 1 is in: `model/prep_zh.py`, `build_model.py --lang zh`, `onepress-zh.bin` (45k words) and
`onepress-zh-m.bin` (20k), flag 32 in both decoders (parity), the page's 中文 models, and
`tests/eval.js` / `tests/baseline.js` for Chinese. Held-out: 85.4% of words, 88.2% of characters
(classic pinyin keypad 78.2% / 81.9%). No new model section was needed: a word is stored as its
pinyin and shown as its characters. Next: step 5 (no spaces between words), then more text.

### What's new compared with the other languages

1. **No spaces.** Chinese has no spaces between words, so the decoder has to split the key
   string into words.
   - First version: `0` between words, with the decoder unchanged.
   - Then a search over key positions with word ends, in `web/decoder.js` and `c/onepress.c`
     together (parity, `resume_test`). SPEC.md's split of two words typed without the space is a
     start.
2. **Keys from pinyin, not from the letters.** A word's keys come from its pinyin, and characters
   with several readings (行 xíng / háng) make that per word. That needs a new optional KPD2 section
   holding each word's key string, so older decoders keep working.
   `chartable.py` doesn't cover CJK, and doesn't need to for decoding.
3. **Data** (commercial-OK terms only, see DATA.md):
   - wordfreq `zh` word frequencies (CC BY-SA).
   - Tatoeba Mandarin (`cmn`) sentences for pairs, triples and the test split (CC BY 2.0 FR).
     Simplified and Traditional need separate models or a conversion step.
   - CC-CEDICT for each word's pinyin (CC BY-SA 4.0).
   - Tatoeba's Chinese is small, so look for more permissively licensed text. Never NUS, which
     includes Chinese messages too.
4. **Display.**
   - Phones and the web: nothing new.
   - Microcontrollers: a font in external flash, about 6,700 common characters (GB2312 levels
     1-2), about 120 KB at 12×12 pixels or 215 KB at 16×16.
   - Meshtastic sends UTF-8, so a 200-byte message holds about 66 characters.
   - APRS and CW can't carry characters; send pinyin there.

### Plan

1. `prep_tatoeba.py` for `cmn`, segmenting with wordfreq's tokenizer (jieba). Pinyin per word
   from CC-CEDICT, and drop words without it.
2. `build_model.py --lang zh` with the key strings from pinyin, and `export_bin.py` writing the
   new key-string section.
3. Decoder reads the section (JS and C), version 1 with `0` between words.
4. Evaluate on the Tatoeba `cmn` test split against a classic pinyin keypad
   (`tests/baseline.js` adapted to one word at a time from pinyin).
5. Automatic word splitting, then the page's keypad labels and Example sentences in Chinese.
6. Font and rendering for the radio and Meshtastic ports.

### Open questions

- Accuracy on Tatoeba's small corpus. Is it worth an initial-letters mode (`wmyq` for 我们一起)?
- Simplified first, Traditional after?
- Whether to show pinyin while typing, or only the characters.

## Japanese (kana rows on the keypad)

Japanese phones put one kana row on each key (`1` あ, `2` か, `3` さ, `4` た, `5` な, `6` は, `7` ま,
`8` や, `9` ら, `0` わ) and the user pressed a key up to five times for the vowel. With OnePress one press
per mora is enough: `2` is any of か き く け こ (and が ぎ ぐ げ ご, since the voicing mark is on the same
key), and the model chooses kana and then kanji from the whole sentence. It reuses nearly
everything from Chinese, so do it after Chinese.

### Same as Chinese

- No spaces, so the same word splitting (version 1 could ask for a separator).
- Keys from each word's reading, not its characters: the same key-string section in the model. A
  reading's keys are its kana's rows (small kana ゃ ゅ ょ っ on their full kana's key, ー on its own key).
- A font for microcontrollers: JIS X 0208 (about 6,900 characters) plus kana, about the same size
  as Chinese's.

### Different from Chinese

- **The keypad.** `0` is the わ row and `1` the あ row, so space and punctuation move: `#` for
  punctuation (、。？！), with `*` for next guess. Spaces are rarely typed in Japanese.
- **Kana inside words.** Many words are written partly or wholly in kana (食べる, する, ありがとう).
  Each word's written form comes from the corpus, so the model learns that; a reading with no
  kanji form is shown as kana.
- **Katakana** for loanwords (コーヒー) comes from the written forms in the corpus too.

### Data (commercial-OK terms only)

- Tatoeba `jpn` is large (well over 200k sentences, CC BY 2.0 FR), more than its Chinese.
- wordfreq `ja` frequencies (CC BY-SA). Tokenizing needs MeCab (`wordfreq[mecab]`).
- Readings: UniDic (BSD / GPL / LGPL) through MeCab or fugashi, or JMdict (EDRDG, CC BY-SA 4.0).

### Plan

1. Tokenize Tatoeba `jpn` with readings and map readings to key rows.
2. Build with the Chinese key-string section, then a first version with a separator, evaluated
   on the Tatoeba test split against a classic kana keypad that converts word by word.
3. Word splitting (shared with Chinese), and keypad labels and Example sentences in Japanese.
4. Font and rendering for the radio and Meshtastic ports.
