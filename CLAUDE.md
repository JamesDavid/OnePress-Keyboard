# OnePress

One-press-per-letter keypad text entry. A word n-gram model picks the letters; an optional small
neural network helps on phones and the web.

- Read `SPEC.md` first. `web/decoder.js` is the reference decoder; `c/onepress.c` is the portable C
  decoder for phones and firmware and must match it exactly. Change both together, then run
  `gcc -std=c99 -O2 -Wall -Wextra -o build/opdecode c/onepress.c c/opdecode.c && node tests/parity.js`,
  plus `node tests/parity.js --learn` for anything touching learning and
  `node tests/parity.js --nn model/onepress-nn.bin` for anything touching the network.
- Held-out accuracy: `node tests/eval.js` (NUS SMS, US/Canada users; `model/prep_nus.py` builds the
  splits; tune on `dev.txt`, report on test). Report it for every model or decoder change. Current:

  | Model | Words | Size | Words acc. | Ambiguous acc. | Punctuation | Target |
  |---|---|---|---|---|---|---|
  | `onepress.bin` + `onepress-nn.bin` | 45k | 3.33 MB + 6.3 MB | 95.14% | 93.48% | 50.6% | phones, web |
  | `onepress.bin` | 45k | 3.33 MB | 94.14% | 92.12% | 49.8% | phones, web |
  | `onepress-m.bin` | 20k | 1.06 MB | 93.17% | 91.24% | 47.2% | ESP32 Meshtastic |
  | `onepress-s.bin` | 5k | 239 KB | 89.18% | 91.16% | 46.7% | radios, nRF52 |

  `node tests/eval.js --nn model/onepress-nn.bin` for the network.
- Learning from the user (SPEC.md §3): `node tests/learn_eval.js [users_test.tsv] [--before 3]`
  replays each NUS user's messages in order. Tune on `users_dev.tsv`. Current, test users:
  predicted words 90.23% → 93.12%, punctuation 58.6% → 66.8% (US/Canada: 94.18% → 95.27%,
  49.5% → 62.7%).
- Small regression set: `node tests/decoder_test.js` (17/20). It overlaps `messages.txt`, so it is a
  sanity check, not a score.
- Rebuild model + web page: `cd model && ./build.sh` (needs `pip install wordfreq`; downloads the
  corpora on first run). The network: `model/train_nn.py` then `model/export_nn.py` (needs PyTorch;
  a CUDA GPU makes training take minutes instead of hours).
- Data terms: `DATA.md`. Code is PolyForm Noncommercial 1.0.0 (commercial use needs a separate license); model files
  are CC BY-SA 4.0 (wordfreq). Don't add corpora
  with non-commercial or unclear terms; never add anything containing NUS messages (the UCI SMS
  Spam Collection does) since NUS is the test set.
- `model/onepress.bin` (KPD2, documented in `model/export_bin.py`) is the word model every decoder
  reads; sections after `params` are optional so older files and decoders keep working.
  Generated files (`model/model.json`, `model/*.bin`, `web/keypad.html`) are rebuilt by
  `build.sh`; edit `web/page.template.html` and `web/decoder.js`, not `keypad.html`.
- `tests/fit.html` (serve the repo root) checks that the keyboard and every tutorial step fit
  without scrolling down to 360×640. Run it after layout changes.
- Targets range from phones down to microcontrollers (Meshtastic nRF52/ESP32 nodes, handheld
  radios such as TIDRADIO TD-H3 and Baofeng DM-32UV). Keep the decoder allocation-light and the
  model format readable straight from flash.
- The repo is public (github.com/JamesDavid/OnePress-Keyboard); pushing to master redeploys the
  GitHub Pages demo. Commits use the repo's git config (GitHub noreply email), never a personal
  address.
- Never use "T9" in user-facing text (trademark).
- Dev machine is Windows: no Xcode. Use Git Bash for the `.sh` scripts.
