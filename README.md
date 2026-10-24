# OnePress

**One press per letter.** Type on a phone keypad, a radio or any small keyboard by pressing each
key once per letter (2 = abc, 3 = def, ...). A small word model reads the whole sentence and picks
the letters, so `66 0 69 0 929 0 4663` becomes "On my way home".

**[Try the demo →](https://jamesdavid.github.io/OnePress-Keyboard/)** It runs entirely in your
browser, and a short tutorial starts on your first visit.

- **Whole-sentence context.** Each new word can fix the ones before it: `4663` alone is "good",
  after "on my way" it's "home".
- **Small enough for microcontrollers.** One C99 file, no memory allocation, about 11 KB of code
  and 6–24 KB of RAM. The model is read straight from flash.
- **Three model sizes** from 238 KB to 1.7 MB, for radios up to phones.
- **Learns from you.** Names, slang and call signs you spell once are guessed from their keys
  after that, and your own word habits and punctuation get more likely.
- **Numbers, money and times.** Hold a number key for its digit: `# 6 # 000 # 00` gives
  "$6,000.00", and "at 5 # 30" gives "at 5:30".
- **Exact spelling** (multi-tap) for anything else, mixed freely with predicted words.
- **Identical decoders** in C and JavaScript, checked against each other on 11,000 inputs.

## Keys

| Key | Tap | Hold |
|---|---|---|
| `2`–`9` | a letter on that key | the digit |
| `0` | space | the digit 0 |
| `#` | punctuation (the model picks `. , ? !`); between letters, an apostrophe | exact spelling on/off |
| `*` | next guess for the selected word | finish the word |
| `1` | delete | the digit 1 |

Apostrophes are optional ("dont" gives "don't").

## Accuracy

Measured on real text messages from people the model never saw (NUS SMS corpus, US/Canada
users, `node tests/eval.js`):

| Model | Words | Size | Words right | Ambiguous words right | For |
|---|---|---|---|---|---|
| `onepress.bin` | 45k | 1.69 MB | 93.7% | 91.5% | phones, web |
| `onepress-m.bin` | 20k | 806 KB | 92.5% | 90.9% | ESP32, Meshtastic |
| `onepress-s.bin` | 5k | 238 KB | 88.2% | 90.9% | radios, nRF52 |

With learning, replaying each person's messages in order (`node tests/learn_eval.js`): words go
from 90.0% to 93.0%, and punctuation from 57.5% to 65.5%.

## Use it in your project

Copy `c/onepress.h`, `c/onepress.c` and a model, then:

```c
#include "onepress.h"

static op_model model;
static op_decoder dec;

op_model_open(&model, blob, blob_size);             /* blob: the .bin, 4-byte aligned, e.g. in flash */
op_decode(&dec, &model, "66069092904663", 8, NULL, NULL, 0);
char out[256];
op_render(&dec, &model, NULL, out, sizeof out);     /* "On my way home" */
```

Or in JavaScript, with `web/decoder.js`:

```js
const m = buildModel(new Uint8Array(await (await fetch('onepress.bin')).arrayBuffer()));
const r = decode(m, '66069092904663', {}, 8, 1);
render(m, r, r.hyps[0]).map(p => p.text).join('');   // "On my way home"
```

**[llm.txt](llm.txt)** is a step-by-step integration guide for iOS keyboard extensions, Android
input methods, the web, ESP32 (Meshtastic) and other microcontrollers. It's written so you can
hand it to a coding assistant.

## How it works

A key string such as `66069092904663` is split into words. Each word's keys match a handful of
dictionary words (`4663`: good, home, gone, hood, ...). A beam search over the sentence scores
each choice with word-pair probabilities (a bigram model with backoff), so every word is chosen
in the context of its neighbours. Punctuation is chosen the same way, with a few rules about
questions. The model is a single binary file (KPD2) with sorted key indexes, so lookups are
binary searches straight from flash. See [SPEC.md](SPEC.md) for the details.

## Repository

| Path | What |
|---|---|
| `c/` | C99 decoder (`onepress.h`, `onepress.c`) and a command-line test driver |
| `web/decoder.js` | JavaScript decoder (the reference) |
| `web/page.template.html` | Demo page source; `web/keypad.html` is the built page |
| `model/` | Model build pipeline and the three `.bin` models |
| `tests/` | Accuracy, learning and C/JS parity tests |
| `python/` | An experimental version that uses a large language model |
| `SPEC.md` | Full specification |
| `llm.txt` | Integration guide |

## Build and test

```bash
gcc -std=c99 -O2 -Wall -Wextra -o build/opdecode c/onepress.c c/opdecode.c
node tests/parity.js              # C and JS give identical output
node tests/parity.js --learn      # ... while learning
node tests/eval.js                # held-out accuracy (needs the corpora: model/fetch_corpora.sh)
cd model && ./build.sh            # rebuild the models and the demo page (pip install wordfreq)
```

## Data

The vocabulary and word frequencies come from [wordfreq](https://github.com/rspeer/wordfreq). Word
pairs are counted from NLTK corpora (Brown, webtext, Gutenberg, movie reviews, names), the
[NUS SMS Corpus](https://github.com/kite1988/nus-sms-corpus) (Tao Chen and Min-Yen Kan, 2013) and a
small set of hand-written everyday messages. The corpora are downloaded by
`model/fetch_corpora.sh` and are not stored in this repository; each has its own terms of use.

## License

No license has been chosen yet.
