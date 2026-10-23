// Tune the decoder's punctuation adjustments on held-out dev messages and store them in the model.
//   node model/tune_punct.js model.json corpora/nus/dev.txt
// Coordinate descent on correct tokens (words + punctuation): punctuation also changes the
// context the next word is scored in, so both count.
const fs = require('fs'), path = require('path');
const D = require(path.join(__dirname, '../web/decoder.js'));
const [modelFile, devFile] = process.argv.slice(2);
const M = JSON.parse(fs.readFileSync(modelFile));
const refs = fs.readFileSync(devFile, 'utf8').split('\n').filter(Boolean);
const enc = s => s.toLowerCase().replace(/'/g, '').replace(/[.,!?]/g, '#').replace(/ /g, '0')
  .replace(/[a-z]/g, c => D.wordKeys(c));
const TOK = /[a-z]+(?:'[a-z]+)?|[.,!?]/g;
const toks = s => s.toLowerCase().match(TOK) || [];
const cases = refs.map(s => ({ keys: enc(s), ref: toks(s) }));

function score(pp) {
  M.punctParams = pp;
  const m = D.buildModel(M);
  let ok = 0, pok = 0;
  for (const c of cases) {
    const r = D.decode(m, c.keys, {}, 8);
    const b = toks(D.render(m, r, r.hyps[0]).map(p => p.text).join(''));
    c.ref.forEach((x, j) => { if (x === b[j]) { ok++; if (/[.,!?]/.test(x)) pok++; } });
  }
  return { ok, pok };
}

let pp = Object.assign({ qQ: 2.5, qN: -1.5, dQ: -1.5, cF: -3, dB: 0, cB: 0, eB: 0 }, M.punctParams || {});
let best = score(pp);
console.log('start', JSON.stringify(pp), best);
for (const stepSize of [1, 0.5, 0.25]) {
  let improved = true;
  while (improved) {
    improved = false;
    for (const k of Object.keys(pp)) {
      for (const d of [stepSize, -stepSize]) {
        const trial = Object.assign({}, pp, { [k]: +(pp[k] + d).toFixed(2) });
        const s = score(trial);
        if (s.ok > best.ok) { pp = trial; best = s; improved = true; console.log(k, pp[k], s); }
      }
    }
  }
}
M.punctParams = pp;
fs.writeFileSync(modelFile, JSON.stringify(M));
console.log('tuned', JSON.stringify(pp));
