# OnePress

One-press-per-letter keypad text entry. A word n-gram model picks the letters.

- Read `SPEC.md` first. `web/decoder.js` is the reference decoder every port must match.
- Regression test: `node tests/decoder_test.js` (baseline 17/20 sentences, 97.6% words).
- Rebuild model + web page: `cd model && ./build.sh` (needs `pip install wordfreq`).
- Generated files (`model/model.json`, `ios/Keyboard/Resources/model.bin`, `web/keypad.html`) are
  rebuilt by `build.sh`; edit `web/page.template.html` and `web/decoder.js`, not `keypad.html`.
- Targets range from phones down to microcontrollers (Meshtastic nRF52/ESP32 nodes, handheld
  radios such as TIDRADIO TD-H3 and Baofeng DM-32UV). Keep the decoder allocation-light and the
  model format readable straight from flash.
- Never use "T9" in user-facing text (trademark).
- Dev machine is Windows: no Xcode. Use Git Bash for the `.sh` scripts.
