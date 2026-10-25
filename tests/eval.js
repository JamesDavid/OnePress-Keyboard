// Held-out accuracy on real messages.
//   node tests/eval.js [test.txt] [--model onepress.bin] [--nn onepress-nn.bin] [--out decoded.txt] [--hyp decoded.txt] [--limit N]
// Default test set: model/corpora/nus/test_na.txt (built by model/prep_nus.py).
// --hyp scores another decoder's output (one line per test line) instead of running decoder.js.
// --slip P: each letter press lands on a neighboring keypad key with probability P; --double P:
// pressed twice (seeded, so runs compare).
const fs = require('fs'), path = require('path');
const D = require(path.join(__dirname, '../web/decoder.js'));

const args = process.argv.slice(2);
const opt = (k) => { const i = args.indexOf(k); return i >= 0 ? args.splice(i, 2)[1] : null; };
const outFile = opt('--out'), hypFile = opt('--hyp'), limit = +(opt('--limit') || 0);
const modelFile = opt('--model') || path.join(__dirname, '../model/onepress.bin'), nnFile = opt('--nn');
const slip = +(opt('--slip') || 0), double = +(opt('--double') || 0);
const params = opt('--params');                  // tuning: keypad slip costs "sub,dup" in nats
if (params && D.slipParams) D.slipParams(...params.split(',').map(Number));
const KEYPAD_NEAR = { 2: '35', 3: '26', 4: '57', 5: '2468', 6: '359', 7: '48', 8: '579', 9: '68' };
let seed = 777;
const rnd = () => { seed = (seed * 1103515245 + 12345) & 0x7fffffff; return seed / 0x80000000; };
const noisy = k => [...k].map(c => {
  if (!KEYPAD_NEAR[c]) return c;
  if (rnd() < slip) { const n = KEYPAD_NEAR[c]; return n[Math.floor(rnd() * n.length)]; }
  return rnd() < double ? c + c : c;
}).join('');
const testFile = args[0] || path.join(__dirname, '../model/corpora/nus/test_na.txt');
let refs = fs.readFileSync(testFile, 'utf8').split('\n').filter(Boolean);
if (limit) refs = refs.slice(0, limit);

const m = D.buildModel(fs.readFileSync(modelFile));
const nn = nnFile ? D.buildNN(fs.readFileSync(nnFile), m) : undefined;
const nnWeight = opt('--nn-weight');            // tuning: override the file's weight (1/256)
if (nn && nnWeight) nn.weight = +nnWeight;
// --oov-exact: words the model lacks are spelled in exact mode, as a person would, and not scored
// (for test sets that keep them, like test_chat.txt).
const oovExact = args.includes('--oov-exact');
if (oovExact) args.splice(args.indexOf('--oov-exact'), 1);
const known = new Set(m.words);
const isOov = w => oovExact && !known.has(w) && !known.has(w.replace(/'/g, ''));
// Letters include the accented ones (other languages); exact mode has no accents, so a word
// the model lacks is spelled with its plain letters.
const L = 'a-zß-öø-ÿ', plain = x => x.normalize('NFD').replace(/[̀-ͯ]/g, '');
const enc = s => s.toLowerCase().split(' ').map(w => w.replace(new RegExp(`[${L}']+`), x => isOov(x) ? plain(x) : x.replace(/'/g, '')
  .replace(new RegExp(`[${L}]`, 'g'), c => D.wordKeys(c)))).join('0').replace(/[.,!?]/g, '#');
const TOK = new RegExp(`[${L}]+(?:'[${L}]+)?|[.,!?]`, 'g');
const toks = s => s.toLowerCase().match(TOK) || [];

let hyps;
const t0 = Date.now();
if (hypFile) hyps = fs.readFileSync(hypFile, 'utf8').split('\n').slice(0, refs.length);
else hyps = refs.map(s => {
  const r = D.decode(m, slip || double ? noisy(enc(s)) : enc(s), {}, 8, 5, { nn });
  return D.render(m, r, r.hyps[0]).map(p => p.text).join('');
});
const ms = Date.now() - t0;
if (outFile) fs.writeFileSync(outFile, hyps.join('\n') + '\n');

const st = { sent: 0, w: 0, wt: 0, a: 0, at: 0, p: 0, pt: 0, oov: 0 };
const errs = new Map();
refs.forEach((ref, i) => {
  const a = toks(ref), b = toks(hyps[i] || '');
  if (a.join(' ') === b.join(' ')) st.sent++;
  a.forEach((x, j) => {
    const y = b[j], ok = x === y;
    if (/[.,!?]/.test(x)) { st.pt++; st.p += ok; return; }
    if (isOov(x)) { st.oov++; return; }
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
if (oovExact) console.log(`  spelled exactly   ${pct(st.oov, st.oov + st.wt)}  (${st.oov} words the model lacks, not scored)`);
console.log(`  ambiguous words   ${pct(st.a, st.at)}  (${st.at})`);
console.log(`  punctuation       ${pct(st.p, st.pt)}  (${st.pt})`);
console.log('  top ambiguous errors: ' + [...errs].sort((x, y) => y[1] - x[1]).slice(0, 12)
  .map(([k, c]) => `${k} (${c})`).join(', '));
