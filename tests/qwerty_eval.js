// QWERTY accuracy: each message typed on a QWERTY layout, each letter landing on a neighboring
// key with probability --miss (seeded, so runs compare), the decoder getting the keypad digits
// and the letters tapped (start.hint), as the web page and an app's QWERTY keyboard send them.
//   node tests/qwerty_eval.js [test.txt] [--miss 0.1] [--model onepress.bin] [--nn file]
// Words count as right when the decoded word is the intended one (case ignored).
const fs = require('fs'), path = require('path');
const D = require(path.join(__dirname, '../web/decoder.js'));
const args = process.argv.slice(2);
const opt = (k, d) => { const i = args.indexOf(k); return i >= 0 ? args.splice(i, 2)[1] : d; };
const miss = +opt('--miss', 0.1), limit = +opt('--limit', 0);
const modelFile = opt('--model', path.join(__dirname, '../model/onepress.bin')), nnFile = opt('--nn');
const params = opt('--params');                    // tuning: "near,far" in nats
const testFile = args[0] || path.join(__dirname, '../model/corpora/nus/test_na.txt');
const m = D.buildModel(fs.readFileSync(modelFile));
const nn = nnFile ? D.buildNN(fs.readFileSync(nnFile), m) : undefined;
if (params && D.qwertyParams) D.qwertyParams(...params.split(',').map(Number));

const ROWS = ['qwertyuiop', 'asdfghjkl', 'zxcvbnm'], OFF = [0, 0.5, 1];
const pos = {};
ROWS.forEach((r, y) => [...r].forEach((c, x) => { pos[c] = [x + OFF[y], y]; }));
const near = c => Object.keys(pos).filter(d => d !== c && Math.hypot(pos[d][0] - pos[c][0], pos[d][1] - pos[c][1]) < 1.2);
let seed = 4242;
const rnd = () => { seed = (seed * 1103515245 + 12345) & 0x7fffffff; return seed / 0x80000000; };

let refs = fs.readFileSync(testFile, 'utf8').split('\n').filter(Boolean);
if (limit) refs = refs.slice(0, limit);
const TOK = /[a-z]+(?:'[a-z]+)?|[.,!?]/g;
let w = 0, wt = 0, typo = 0;
for (const ref of refs) {
  let keys = '', hint = '';
  for (const ch of ref.toLowerCase()) {
    if (ch >= 'a' && ch <= 'z') {
      let t = ch;
      if (rnd() < miss) { const n = near(ch); t = n[Math.floor(rnd() * n.length)]; typo++; }
      keys += D.wordKeys(t); hint += t;
    } else if (ch === ' ') { keys += '0'; hint += ' '; }
    else if ('.,!?'.includes(ch)) { keys += '#'; hint += ' '; }
  }
  const r = D.decode(m, keys, {}, 8, 1, { hint, nn });
  const out = D.render(m, r, r.hyps[0]).map(p => p.text).join('').toLowerCase();
  const a = ref.toLowerCase().match(TOK) || [], b = out.match(TOK) || [];
  a.forEach((x, j) => { if (/[a-z]/.test(x)) { wt++; w += x.replace(/'/g, '') === (b[j] || '').replace(/'/g, ''); } });
}
console.log(`${path.basename(testFile)}, ${(100 * miss).toFixed(0)}% of letters on a neighboring key (${typo} typos): words ${(100 * w / wt).toFixed(2)}% (${wt})`);
