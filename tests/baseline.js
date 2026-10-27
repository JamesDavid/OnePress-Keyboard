// The classic one-word-at-a-time keypad, for comparison: each word's keys become the most
// frequent dictionary word with those keys (no context), every mark is '.', and a word the model
// lacks stays as written (exact spelling). Writes one line per message for tests/eval.js --hyp.
//   node tests/baseline.js test.txt model.bin out.txt
//   node tests/eval.js test.txt --oov-exact --model model.bin --hyp out.txt
const fs = require('fs'), path = require('path');
const D = require(path.join(__dirname, '../web/decoder.js'));
const [testFile, modelFile, outFile] = process.argv.slice(2);
const m = D.buildModel(fs.readFileSync(modelFile));
// Chinese (model flag 32; lines "characters<TAB>pinyin", model/prep_zh.py): each word's pinyin keys
// become the most frequent word with those keys, shown as its characters; one word per space.
if (m.params.flags & 32) {
  const split = s => s.match(/[^\s.,!?]+|[.,!?]/g) || [], shown = new Set(m.display.filter(Boolean));
  const lines = fs.readFileSync(testFile, 'utf8').split('\n').filter(Boolean).map(l => {
    const [a, b] = l.split('\t'), ref = split(a);
    return split(b).map((p, j) => {
      if (/^[.,!?]$/.test(p)) return '.';
      const ids = D.exactMatches(m, [...p].map(c => D.wordKeys(c)).join(''));
      return ids.length && shown.has(ref[j]) ? m.display[ids[0]] : ref[j];
    }).join(' ');
  });
  fs.writeFileSync(outFile, lines.join('\n') + '\n');
  process.exit(0);
}
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
