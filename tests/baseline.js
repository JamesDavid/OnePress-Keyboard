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
const L = '\\p{L}', TOK = new RegExp(`[${L}]+(?:'[${L}]+)?(?:-[${L}]+)*|[.,!?]`, 'gu');
const out = fs.readFileSync(testFile, 'utf8').split('\n').filter(Boolean).map(s => (lower(s).match(TOK) || []).map(t => {
  if (/[.,!?]/.test(t)) return '.';
  const top = w => { const ids = D.exactMatches(m, D.wordKeys(w)); return ids.length ? m.words[ids[0]] : null; };
  const whole = top(t.replace(/'/g, ''));
  if (whole || !/['-]/.test(t)) return whole || t;
  // split as the decoder does: l' + homme, tom + 'a, est + -ce; each part its most frequent word
  const ps = [];
  for (const x of t.split(/(?=-)/)) {
    if (!x.includes("'") || top(x)) { ps.push(x); continue; }
    const i = x.indexOf("'");
    ps.push(top(x.slice(0, i + 1)) ? x.slice(0, i + 1) : x.slice(0, i), top(x.slice(0, i + 1)) ? x.slice(i + 1) : x.slice(i));
  }
  const ws = ps.map(top);
  return ws.every(Boolean) ? ws.join('') : t;
}).join(' '));
fs.writeFileSync(outFile, out.join('\n') + '\n');
