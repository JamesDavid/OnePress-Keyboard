// Letter-keyboard accuracy: each message typed on a keyboard layout, each letter landing on a
// neighboring key with probability --miss (seeded, so runs compare), the decoder getting the
// keypad digits, the letters tapped (start.hint) and the layout (start.layout), as the web page
// and an app's keyboard send them. A letter with no key of its own (é on English QWERTY, ά on
// Greek) is tapped as its plain letter; one the layout lacks entirely is skipped (not scored).
//   node tests/qwerty_eval.js [test.txt] [--miss 0.1] [--model onepress.bin] [--nn file]
//                             [--layout "qwertzuiopü|asdfghjklöä|yxcvbnm"] [--limit N]
// Words count as right when the decoded word is the intended one (case ignored).
const fs = require('fs'), path = require('path');
const D = require(path.join(__dirname, '../web/decoder.js'));
const args = process.argv.slice(2);
const opt = (k, d) => { const i = args.indexOf(k); return i >= 0 ? args.splice(i, 2)[1] : d; };
const miss = +opt('--miss', 0.1), limit = +opt('--limit', 0);
const modelFile = opt('--model', path.join(__dirname, '../model/onepress.bin')), nnFile = opt('--nn');
const layout = opt('--layout', 'qwertyuiop|asdfghjkl|zxcvbnm');
const params = opt('--params');                    // tuning: "near,far" in nats
const testFile = args[0] || path.join(__dirname, '../model/corpora/nus/test_na.txt');
const m = D.buildModel(fs.readFileSync(modelFile));
const nn = nnFile ? D.buildNN(fs.readFileSync(nnFile), m) : undefined;
if (params && D.qwertyParams) D.qwertyParams(...params.split(',').map(Number));

// Row r shifted right by r/2 key; neighbors one apart in a row or touching in the next row.
const pos = {};
layout.split('|').forEach((r, y) => [...r].forEach((c, x) => { pos[c] = [2 * x + y, y]; }));
const near = c => Object.keys(pos).filter(d => { if (d === c) return false;
  const dx = pos[d][0] - pos[c][0], dy = pos[d][1] - pos[c][1]; return dx * dx + 4 * dy * dy <= 5; });
const tapOf = c => pos[c] ? c : pos[c.normalize('NFD')[0]] ? c.normalize('NFD')[0] : null;
let seed = 4242;
const rnd = () => { seed = (seed * 1103515245 + 12345) & 0x7fffffff; return seed / 0x80000000; };

let refs = fs.readFileSync(testFile, 'utf8').split('\n').filter(Boolean);
if (limit) refs = refs.slice(0, limit);
const lower = m.words.some(w => w.includes('ı')) ? s => s.replace(/İ/g, 'i').replace(/I/g, 'ı').toLowerCase() : s => s.toLowerCase();
const TOK = /[\p{L}]+(?:'[\p{L}]+)?(?:-[\p{L}]+)*|[.,!?]/gu;
let w = 0, wt = 0, typo = 0;
for (const ref of refs) {
  let keys = '', hint = '', ok = true;
  for (const ch of lower(ref)) {
    if (/\p{L}/u.test(ch)) {
      let t = tapOf(ch);
      if (!t) { ok = false; break; }
      if (rnd() < miss) { const n = near(t); t = n[Math.floor(rnd() * n.length)]; typo++; }
      keys += D.wordKeys(t); hint += t;
    } else if (ch === ' ') { keys += '0'; hint += ' '; }
    else if ('.,!?\'-'.includes(ch)) { keys += '#'; hint += ' '; }
  }
  if (!ok) continue;
  const r = D.decode(m, keys, {}, 8, 1, { hint, nn, layout });
  const out = lower(D.render(m, r, r.hyps[0]).map(p => p.text).join(''));
  const a = lower(ref).match(TOK) || [], b = out.match(TOK) || [];
  a.forEach((x, j) => { if (/\p{L}/u.test(x)) { wt++; w += x.replace(/'/g, '') === (b[j] || '').replace(/'/g, ''); } });
}
console.log(`${path.basename(testFile)}, ${(100 * miss).toFixed(0)}% of letters on a neighboring key (${typo} typos): words ${(100 * w / wt).toFixed(2)}% (${wt})`);
