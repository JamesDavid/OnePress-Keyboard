// Regression test for the JS decoder: node tests/decoder_test.js [onepress.bin]
const path = require('path');
const D = require(path.join(__dirname, '../web/decoder.js'));
const m = D.buildModel(require('fs').readFileSync(process.argv[2] || path.join(__dirname, '../model/onepress.bin')));
const enc = s => s.toLowerCase().replace(/'/g, '').replace(/[.,!?]/g, '#').replace(/ /g, '0')
  .replace(/[a-z]/g, c => D.wordKeys(c));
const CASES = [
  "I'm on my way home.", "Can you pick up the kids after school?", "What time is the game tonight?",
  "The meeting was moved to Friday.", "He went to the store to buy some food.",
  "It is a good day for a walk in the park.", "Do you want to get dinner tonight?",
  "She said that she would be late.", "I think the new car is in the garage.",
  "Please send me the report before noon.", "We should go home now.", "Where did you put my keys?",
  "The cat is sleeping on the bed.", "I don't know.", "We're going to McDonald's tonight!",
  "My iPhone is dead.", "Let's watch Netflix later.", "It's raining in Tempe.",
  "I'm at Costco, want anything?", "Good morning, how are you?",
];
let exact = 0, w = 0, wt = 0;
for (const s of CASES) {
  const r = D.decode(m, enc(s));
  const t = D.render(m, r, r.hyps[0]).map(p => p.text).join('');
  const ok = t === s; exact += ok;
  const a = t.toLowerCase().split(' '), b = s.toLowerCase().split(' ');
  b.forEach((x, i) => { wt++; if (a[i] === x) w++; });
  console.log((ok ? 'OK ' : 'XX ') + t);
}
console.log(`\n${exact}/${CASES.length} sentences exact, ${w}/${wt} words (${(100 * w / wt).toFixed(1)}%)`);
