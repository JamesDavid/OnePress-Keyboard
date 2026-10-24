// The C decoder must produce exactly what web/decoder.js does.
//   node tests/parity.js [path/to/opdecode] [--beam N] [--fuzz N] [--model onepress.bin] [--learn]
// --learn: one person types everything (their NUS dev messages, spelling unknown words exactly
// the first time, then the fuzz), learning each decoded line, so learned words, pair counts
// and both kinds of eviction are compared too.
// Inputs: every held-out NUS message (if model/corpora/nus exists), the regression sentences,
// and random key strings that mix predictive keys with exact-mode letters, apostrophes,
// digits (numbers, call signs) and punctuation.
const fs = require('fs'), path = require('path'), { execFileSync } = require('child_process');
const D = require(path.join(__dirname, '../web/decoder.js'));

const args = process.argv.slice(2);
const opt = (k, d) => { const i = args.indexOf(k); return i >= 0 ? args.splice(i, 2)[1] : d; };
const learnMode = args.includes('--learn');
if (learnMode) args.splice(args.indexOf('--learn'), 1);
const beam = +opt('--beam', 8), nFuzz = +opt('--fuzz', 5000);
const modelFile = opt('--model', path.join(__dirname, '../model/onepress.bin'));
const exe = args[0] || path.join(__dirname, '../build/opdecode' + (process.platform === 'win32' ? '.exe' : ''));
const m = D.buildModel(fs.readFileSync(modelFile));

const enc = s => s.toLowerCase().replace(/'/g, '').replace(/[.,!?]/g, '#').replace(/ /g, '0')
  .replace(/[a-z]/g, c => D.wordKeys(c));
const inputs = [];
for (const f of ['test.txt', 'dev.txt']) {
  const p = path.join(__dirname, '../model/corpora/nus', f);
  if (fs.existsSync(p)) for (const s of fs.readFileSync(p, 'utf8').split('\n')) if (s) inputs.push(enc(s));
}
inputs.push(enc("Can you pick up the kids after school?"), enc("We're going to McDonald's tonight!"), '');
if (learnMode) {
  inputs.length = 0;
  // Call signs and words with digits: spelled once, then typed with the digit held or pressed.
  // At the start (room in the table) and again at the end (full, so words get replaced).
  const callsigns = ['keHaqa', '53H272', '537272', '53H2', '53', '4404053H272#', 'wDbcd', '9D222', 'wDbcd0keHaqa',
    '9D2220537272#', 'Eever', 'E3837', '43837', '2B3', '2B32', '53H272H', 'H53H272', '53H#272'];
  inputs.push(...callsigns);
  const users = path.join(__dirname, '../model/corpora/nus/users_dev.tsv'), known = new Set(m.words), seen = new Set();
  if (fs.existsSync(users)) for (const line of fs.readFileSync(users, 'utf8').split('\n')) {
    const msg = line.split('\t')[1];
    if (!msg) continue;
    inputs.push(msg.toLowerCase().split(' ').map(w => w.replace(/[a-z']+/, x => {
      if (known.has(x) || seen.has(x)) return enc(x);
      seen.add(x);
      return x;
    }).replace(/[.,!?]/g, '#')).join('0'));
  }
  inputs.push(...callsigns);
}

// Seeded random so failures reproduce.
let seed = 12345;
const rnd = n => { seed = (seed * 1103515245 + 12345) & 0x7fffffff; return seed % n; };
const pick = s => s[rnd(s.length)];
for (let i = 0; i < nFuzz; i++) {
  let k = '';
  const parts = 1 + rnd(8);
  for (let p = 0; p < parts; p++) {
    const r = rnd(10);
    if (r < 5) {
      // A dictionary word, maybe with some letters typed exactly or its apostrophe kept.
      const w = m.words[rnd(r < 3 ? 3000 : m.n)];
      for (const c of w) {
        if (c === "'") k += rnd(2) ? '#' : (rnd(3) ? '' : "'");
        else k += rnd(6) ? D.wordKeys(c) : c;
      }
    } else if (r < 7) {
      for (let j = 1 + rnd(7); j > 0; j--) k += pick('23456789');      // random keys
    } else if (r === 7) {
      for (let j = 1 + rnd(5); j > 0; j--) k += pick("abcdefghijklmnopqrstuvwxyz'"); // spelled exactly
    } else if (r === 8) {
      k += pick(['#', '.', ',', '?', '!', '##', 'A', 'BC', '2A3', '#0#', '#G#AAA#AA', 'BJC#BGI#B#B',
        'D.BE', 'B,FAA', 'E3837', 'keHaqa', 'CeAabc', "JA's", '#B#', 'F##B', 'G#', '53H252', '280F#DA', '290BA#BF076', 'F#DA76', 'C#BE26', 'CG#FF']);
    } else {
      k += pick('23456789') + pick(['', 'a', '#', "'"]) + pick('23456789');
    }
    k += pick(['0', '0', '0', '#0', '', '00', '#']);
  }
  inputs.push(k.slice(0, 250));
}

const user = learnMode ? D.newUser(m) : null;
const js = inputs.map(k => {
  const r = D.decode(m, k, {}, beam, 5, { user });
  const text = D.render(m, r, r.hyps[0]).map(p => p.text).join('');
  if (user) D.learn(m, user, r, r.hyps[0]);
  return text;
});
const t0 = Date.now();
const c = execFileSync(exe, [modelFile, String(beam)].concat(learnMode ? ['--learn'] : []), { input: inputs.join('\n') + '\n', maxBuffer: 1 << 28 })
  .toString().split(/\r?\n/);
const ms = Date.now() - t0;
let bad = 0;
inputs.forEach((k, i) => {
  if (js[i] !== c[i]) {
    if (bad++ < 15) console.log(`MISMATCH keys=${JSON.stringify(k)}\n  js: ${JSON.stringify(js[i])}\n  c:  ${JSON.stringify(c[i])}`);
  }
});
console.log(`${inputs.length - bad}/${inputs.length} identical (beam ${beam}${learnMode ? `, learning: ${user.words.length} words, ${user.pairs.length} pairs` : ''}); C took ${ms} ms total`);
process.exit(bad ? 1 : 0);
