# OnePress

One-press-per-letter keypad text entry. A word n-gram model picks the letters.

- Read `SPEC.md` first. `web/decoder.js` is the reference decoder; `c/onepress.c` is the portable C
  decoder for phones and firmware and must match it exactly. Change both together, then run
  `gcc -std=c99 -O2 -Wall -Wextra -o build/opdecode c/onepress.c c/opdecode.c && node tests/parity.js`.
- Held-out accuracy: `node tests/eval.js` (NUS SMS, US/Canada users; `model/prep_nus.py` builds the
  splits; tune on `dev.txt`, report on test). Report it for every model or decoder change. Current:

  | Model | Words | Size | Words acc. | Ambiguous acc. | Target |
  |---|---|---|---|---|---|
  | `onepress.bin` | 45k | 1.69 MB | 93.67% | 91.49% | phones, web |
  | `onepress-m.bin` | 20k | 806 KB | 92.54% | 90.87% | ESP32 Meshtastic |
  | `onepress-s.bin` | 5k | 238 KB | 88.19% | 90.93% | radios, nRF52 |

  Punctuation is ~44% everywhere: people punctuate texts inconsistently, so a global tuning
  didn't transfer between users; plan to learn it per user.
- Small regression set: `node tests/decoder_test.js` (16/20). It overlaps `messages.txt`, so it is a
  sanity check, not a score.
- Rebuild model + web page: `cd model && ./build.sh` (needs `pip install wordfreq`).
- `model/onepress.bin` (KPD2 format, documented in `model/export_bin.py`) is the one model every
  decoder reads. Generated files (`model/model.json`, `model/onepress.bin`, `web/keypad.html`) are
  rebuilt by `build.sh`; edit `web/page.template.html` and `web/decoder.js`, not `keypad.html`.
- Targets range from phones down to microcontrollers (Meshtastic nRF52/ESP32 nodes, handheld
  radios such as TIDRADIO TD-H3 and Baofeng DM-32UV). Keep the decoder allocation-light and the
  model format readable straight from flash.
- Never use "T9" in user-facing text (trademark).
- Dev machine is Windows: no Xcode. Use Git Bash for the `.sh` scripts.
