// Held-out accuracy on real messages.
//   node tests/eval.js [test.txt] [--model onepress.bin] [--out decoded.txt] [--hyp decoded.txt] [--limit N]
// Default test set: model/corpora/nus/test_na.txt (built by model/prep_nus.py).
// --hyp scores another decoder's output (one line per test line) instead of running decoder.js.
const fs = require('fs'), path = require('path');
const D = require(path.join(__dirname, '../web/decoder.js'));

const args = process.argv.slice(2);
const opt = (k) => { const i = args.indexOf(k); return i >= 0 ? args.splice(i, 2)[1] : null; };
const outFile = opt('--out'), hypFile = opt('--hyp'), limit = +(opt('--limit') || 0);
const modelFile = opt('--model') || path.join(__dirname, '../model/onepress.bin');
const testFile = args[0] || path.join(__dirname, '../model/corpora/nus/test_na.txt');
let refs = fs.readFileSync(testFile, 'utf8').split('\n').filter(Boolean);
if (limit) refs = refs.slice(0, limit);

const m = D.buildModel(fs.readFileSync(modelFile));
const enc = s => s.toLowerCase().replace(/'/g, '').replace(/[.,!?]/g, '#').replace(/ /g, '0')
  .replace(/[a-z]/g, c => D.wordKeys(c));
const TOK = /[a-z]+(?:'[a-z]+)?|[.,!?]/g;
const toks = s => s.toLowerCase().match(TOK) || [];

let hyps;
const t0 = Date.now();
if (hypFile) hyps = fs.readFileSync(hypFile, 'utf8').split('\n').slice(0, refs.length);
else hyps = refs.map(s => {
  const r = D.decode(m, enc(s));
  return D.render(m, r, r.hyps[0]).map(p => p.text).join('');
});
const ms = Date.now() - t0;
if (outFile) fs.writeFileSync(outFile, hyps.join('\n') + '\n');

const st = { sent: 0, w: 0, wt: 0, a: 0, at: 0, p: 0, pt: 0 };
const errs = new Map();
refs.forEach((ref, i) => {
  const a = toks(ref), b = toks(hyps[i] || '');
  if (a.join(' ') === b.join(' ')) st.sent++;
  a.forEach((x, j) => {
    const y = b[j], ok = x === y;
    if (/[.,!?]/.test(x)) { st.pt++; st.p += ok; return; }
    st.wt++; st.w += ok;
    if (D.exactMatches(m, D.wordKeys(x.replace(/'/g, ''))).length > 1) {
      st.at++; st.a += ok;
      if (!ok) { const k = `${x} -> ${y}`; errs.set(k, (errs.get(k) || 0) + 1); }
    }
  });
});
const pct = (a, b) => (100 * a / b).toFixed(2) + '%';
console.log(`${path.basename(testFile)}: ${refs.length} messages${hypFile ? '' : `, ${(ms / refs.length).toFixed(1)} ms/msg`}`);
console.log(`  sentences exact   ${pct(st.sent, refs.length)}`);
console.log(`  words             ${pct(st.w, st.wt)}  (${st.wt})`);
console.log(`  ambiguous words   ${pct(st.a, st.at)}  (${st.at})`);
console.log(`  punctuation       ${pct(st.p, st.pt)}  (${st.pt})`);
console.log('  top ambiguous errors: ' + [...errs].sort((x, y) => y[1] - x[1]).slice(0, 12)
  .map(([k, c]) => `${k} (${c})`).join(', '));
