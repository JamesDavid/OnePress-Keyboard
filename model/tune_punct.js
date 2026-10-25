// Tune the decoder's punctuation adjustments on held-out dev messages.
//   node model/tune_punct.js onepress.bin model.json dev.txt[:N] [dev2.txt[:N] ...]
// e.g. corpora/nus/dev.txt corpora/chat/dev_chat.txt:3000 (texting and modern chat).
// Writes the result to model.json as punctParams; rerun export_bin.py to apply it.
// Coordinate descent on correct tokens (words + punctuation), each file's share averaged so
// both kinds of writing count the same: punctuation also changes the context the next word is
// scored in, so words count too. Words the model lacks are spelled exactly, as a person would.
const fs = require('fs'), path = require('path');
const D = require(path.join(__dirname, '../web/decoder.js'));
const [binFile, jsonFile, ...devFiles] = process.argv.slice(2);
const m = D.buildModel(fs.readFileSync(binFile));
const M = JSON.parse(fs.readFileSync(jsonFile));
const known = new Set(m.words);
const enc = s => s.toLowerCase().split(' ').map(w => w.replace(/[a-z']+/, x => !known.has(x) && !known.has(x.replace(/'/g, '')) ? x
  : x.replace(/'/g, '').replace(/[a-z]/g, c => D.wordKeys(c)))).join('0').replace(/[.,!?]/g, '#');
const TOK = /[a-z]+(?:'[a-z]+)?|[.,!?]/g;
const toks = s => s.toLowerCase().match(TOK) || [];
const sets = devFiles.map(f => {
  const [file, n] = f.split(':');
  let refs = fs.readFileSync(file, 'utf8').split('\n').filter(Boolean);
  if (n) refs = refs.slice(0, +n);
  return refs.map(s => ({ keys: enc(s), ref: toks(s) }));
});

function score(pp) {
  for (const k in pp) m.params[k] = Math.round(pp[k] * m.scale);
  let total = 0, pAll = [];
  for (const cases of sets) {
    let ok = 0, n = 0, pok = 0, pn = 0;
    for (const c of cases) {
      const r = D.decode(m, c.keys, {}, 8);
      const b = toks(D.render(m, r, r.hyps[0]).map(p => p.text).join(''));
      c.ref.forEach((x, j) => {
        n++; ok += x === b[j];
        if (/[.,!?]/.test(x)) { pn++; pok += x === b[j]; }
      });
    }
    total += ok / n / sets.length;
    pAll.push((100 * pok / pn).toFixed(2) + '%');
  }
  return { total, punct: pAll.join(' / ') };
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
        if (s.total > best.total) { pp = trial; best = s; improved = true; console.log(k, pp[k], s); }
      }
    }
  }
}
M.punctParams = pp;
fs.writeFileSync(jsonFile, JSON.stringify(M));
console.log('tuned', JSON.stringify(pp), best);
