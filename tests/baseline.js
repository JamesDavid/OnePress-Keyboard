// The classic one-word-at-a-time keypad, for comparison: each word's keys become the most
// frequent dictionary word with those keys (no context), every mark is '.', and a word the model
// lacks stays as written (exact spelling). Writes one line per message for tests/eval.js --hyp.
//   node tests/baseline.js test.txt model.bin out.txt
//   node tests/eval.js test.txt --oov-exact --model model.bin --hyp out.txt
const fs = require('fs'), path = require('path');
const D = require(path.join(__dirname, '../web/decoder.js'));
const [testFile, modelFile, outFile] = process.argv.slice(2);
const m = D.buildModel(fs.readFileSync(modelFile));
const lower = m.words.some(w => w.includes('ı')) ? s => s.replace(/İ/g, 'i').replace(/I/g, 'ı').toLowerCase() : s => s.toLowerCase();
const L = '\\p{L}', TOK = new RegExp(`[${L}]+(?:'[${L}]+)?|[.,!?]`, 'gu');
const out = fs.readFileSync(testFile, 'utf8').split('\n').filter(Boolean).map(s => (lower(s).match(TOK) || []).map(t => {
  if (/[.,!?]/.test(t)) return '.';
  const top = w => { const ids = D.exactMatches(m, D.wordKeys(w)); return ids.length ? m.words[ids[0]] : null; };
  const whole = top(t.replace(/'/g, ''));
  if (whole || !t.includes("'")) return whole || t;
  const a = top(t.split("'")[0] + "'"), b = top(t.slice(t.indexOf("'") + 1));      // elided: l' + homme
  return a && b && a.endsWith("'") ? a + b : t;
}).join(' '));
fs.writeFileSync(outFile, out.join('\n') + '\n');
