// Exports, for each message, the decoder's best sentence and the top alternatives for each
// word slot (each with the whole-sentence score when that slot is locked to it, and the
// sentence it gives), for tests/nn_rerank.py to rescore with a neural language model.
//   node tests/nn_export.js test.txt out.jsonl [--model onepress.bin] [--k 5]
const fs = require('fs'), path = require('path');
const D = require(path.join(__dirname, '../web/decoder.js'));
const args = process.argv.slice(2);
const opt = k => { const i = args.indexOf(k); return i >= 0 ? args.splice(i, 2)[1] : null; };
const m = D.buildModel(fs.readFileSync(opt('--model') || path.join(__dirname, '../model/onepress.bin')));
const K = +(opt('--k') || 5);
const [inFile, outFile] = args;
const enc = s => s.toLowerCase().replace(/'/g, '').replace(/[.,!?]/g, '#').replace(/ /g, '0').replace(/[a-z]/g, c => D.wordKeys(c));
const text = (r, h) => D.render(m, r, h).map(p => p.text).join('');
const out = [];
for (const ref of fs.readFileSync(inFile, 'utf8').split('\n').filter(Boolean)) {
  const keys = enc(ref);
  const r = D.decode(m, keys, {}, 8, 1);
  const best = r.hyps[0];
  const slots = [];
  r.slots.forEach((s, j) => {
    if (s.tok.type !== 'word') return;
    const seen = new Map();
    for (const c of s.all.slice(0, 30)) {
      if (c.unknown || c.partial || seen.has(c.text)) continue;
      const rr = D.decode(m, keys, { [j]: { keys: s.tok.keys, text: c.text } }, 8, 1);
      if (!rr.hyps.length) continue;
      seen.set(c.text, { word: c.text, score: rr.hyps[0].score, sentence: text(rr, rr.hyps[0]) });
    }
    const alts = [...seen.values()].sort((a, b) => b.score - a.score).slice(0, K);
    if (alts.length > 1) slots.push({ slot: j, alts });
  });
  out.push(JSON.stringify({ ref, best: text(r, best), score: best.score, slots }));
}
fs.writeFileSync(outFile, out.join('\n') + '\n');
console.log(`${out.length} messages -> ${outFile}`);
