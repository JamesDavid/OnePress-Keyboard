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
const nnFile = opt('--nn');
if (learnMode) args.splice(args.indexOf('--learn'), 1);
const beam = +opt('--beam', 8), nFuzz = +opt('--fuzz', 5000);
const modelFile = opt('--model', path.join(__dirname, '../model/onepress.bin'));
const textFile = opt('--text');
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
// --text file: its sentences too (e.g. corpora/es/dev.txt for a Spanish model), accents included,
// some with the text before and QWERTY letters (plain).
if (textFile) {
  const plain = x => x.normalize('NFD').replace(/[̀-ͯ]/g, '');
  for (const line of fs.readFileSync(textFile, 'utf8').split('\n').filter(Boolean).slice(0, 2000)) {
    const low = line.toLowerCase();                 // apostrophes typed as #: French elisions
    const k = [...low].map(c => c === ' ' ? '0' : '.,!?'.includes(c) ? '#' : (/^[2-9#]$/.test(D.wordKeys(c)) ? D.wordKeys(c) : '')).join('');
    inputs.push(k, k + '\t' + line.split(' ').slice(0, 3).join(' ') + '\t' + [...plain(low)].map(c => /[a-z]/.test(c) ? c : ' ').join(''));
  }
}
// Known words run together (compounds), some with letters typed exactly or an apostrophe.
const COMPOUNDS = [enc('lollypops'), enc('i love lollypops'), enc('snowmanparty'), enc('bestfriendforever'),
  '5655976l77', 'l6559767767', enc('the bluebirdnest is'), '766#7468', '4663968727983', enc('kittycatz')];
inputs.push(...COMPOUNDS);
if (learnMode) {
  inputs.length = 0;
  // Call signs and words with digits: spelled once, then typed with the digit held or pressed.
  // At the start (room in the table) and again at the end (full, so words get replaced).
  const callsigns = ['keHaqa', '53H272', '537272', '53H2', '53', '4404053H272#', 'wDbcd', '9D222', 'wDbcd0keHaqa',
    '9D2220537272#', 'Eever', 'E3837', '43837', '2B3', '2B32', '53H272H', 'H53H272', '53H#272',
    // typed on QWERTY (hints) with no word matching, then predicted; and with text before
    '767839\t\tqorvex', '767839', '76783', '4404767839#\they|\tgi qorvex', '96#93\t\tzm wd', '96#93',
    '4663\tsee you at the qorvex|\t',
    // learned words given a casing by the app
    '@Qorvex', '767839', '4404767839#', 'qorvex', '@KE7aqa', '53H272', 'keHaqa0767839', '76783\tQORVEX said'];
  inputs.push(...callsigns, ...COMPOUNDS, ...COMPOUNDS, '@@save');
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
  inputs.push('@@save', ...callsigns, '@@save');
}

const LETTERS = { 2: 'abc', 3: 'def', 4: 'ghi', 5: 'jkl', 6: 'mno', 7: 'pqrs', 8: 'tuv', 9: 'wxyz' };
const BEFORE = ['', 'how are you', 'Hello how are you doing', 'See you at the beach.|', 'I bought milk, eggs and',
  'Are you coming tonight?|Yes|', 'meet at 5 by the KE7AQA', 'It’s my turn, ', 'WHAT ARE YOU DOING', 'the',
  'call me|ok|what time is the game tonight', 'lol ok! so', 'I think the meeting moved to', 'qorvex is here, and',
  'x'.repeat(40) + ' word', 'Starbucks after school', 'in', 'ok, and then what', '?', 'helloé world 2day'];
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
        'D.BE', 'B,FAA', 'E3837', 'keHaqa', 'CeAabc', "JA's", '#B#', 'F##B', 'G#', '53H252', '280F#DA', '290BA#BF076', 'F#DA76', 'C#BE26', 'CG#FF',
        'F.DA', 'F:DA', 'F:', ':', 'J.EF026', '280F.DA', 'B:FG#', '#.#', 'BC:DE', 'C#J9', 'F#DA#AA']);
    } else {
      k += pick('23456789') + pick(['', 'a', '#', "'"]) + pick('23456789');
    }
    k += pick(['0', '0', '0', '#0', '', '00', '#']);
  }
  k = k.slice(0, 250);
  // A third also get the text before (start.before) and QWERTY letter hints (start.hint).
  if (rnd(3) === 0) {
    const before = pick(BEFORE);
    const hint = [...k].map(c => /[2-9]/.test(c) && rnd(4) ? pick(LETTERS[c]) : ' ').join('');
    k += '\t' + before + (rnd(2) ? '\t' + hint : '');
  }
  inputs.push(k);
}

// Typed on QWERTY: every letter's tap in the hint, some on a neighboring key, some messages cut
// off mid-word (completions), some with text before. From the NUS dev messages, or the fuzz words.
{
  const ROWS = ['qwertyuiop', 'asdfghjkl', 'zxcvbnm'], pos = {};
  ROWS.forEach((r, y) => [...r].forEach((c, x) => { pos[c] = [x + [0, 0.5, 1][y], y]; }));
  const near = c => Object.keys(pos).filter(d => d !== c && Math.hypot(pos[d][0] - pos[c][0], pos[d][1] - pos[c][1]) < 1.2);
  const dev = path.join(__dirname, '../model/corpora/nus/dev.txt');
  const msgs = fs.existsSync(dev) ? fs.readFileSync(dev, 'utf8').split('\n').filter(Boolean).slice(0, 1500)
    : Array.from({ length: 300 }, () => Array.from({ length: 1 + rnd(6) }, () => m.words[rnd(5000)]).join(' '));
  for (const msg of msgs) {
    let k = '', h = '';
    for (const ch of msg.toLowerCase()) {
      if (ch >= 'a' && ch <= 'z') { const t = rnd(10) ? ch : pick(near(ch)); k += D.wordKeys(t); h += t; }
      else if (ch === ' ') { k += '0'; h += ' '; }
      else if (ch === "'") { k += '#'; h += ' '; }
      else if ('.,!?'.includes(ch)) { k += '#'; h += ' '; }
    }
    const cut = rnd(3) ? k.length : Math.max(1, k.length - 1 - rnd(4));
    inputs.push(k.slice(0, cut) + '\t' + (rnd(3) ? '' : pick(BEFORE)) + '\t' + h.slice(0, cut));
  }
  // And on the keypad with slips: a neighboring key, or a key pressed twice.
  const KEYPAD_NEAR = { 2: '35', 3: '26', 4: '57', 5: '2468', 6: '359', 7: '48', 8: '579', 9: '68' };
  for (const msg of msgs.slice(0, 600)) {
    inputs.push([...enc(msg)].map(c => !KEYPAD_NEAR[c] || rnd(12) ? c : rnd(2) ? pick(KEYPAD_NEAR[c]) : c + c).join(''));
  }
}

const user = learnMode ? D.newUser(m) : null;
const nn = nnFile ? D.buildNN(fs.readFileSync(nnFile), m) : undefined;
const js = inputs.map(line => {
  if (line === '@@save') {          // save, load back, print the bytes (as opdecode does)
    const b = D.saveUser(user), back = D.loadUser(m, b);
    Object.assign(user, back);
    return Buffer.from(b).toString('hex');
  }
  if (line[0] === '@') {           // @Word: recase a learned word (as opdecode does)
    if (user) user.words.forEach((w, i) => { if (w.toLowerCase() === line.slice(1).toLowerCase()) user.words[i] = line.slice(1); });
    return line;
  }
  const [k, before, hint] = line.split('\t');
  const r = D.decode(m, k, {}, beam, 5, { user, before: before === undefined ? undefined : before.replace(/\|/g, '\n'), hint, nn });
  const text = D.render(m, r, r.hyps[0]).map(p => p.text).join('');
  if (user) D.learn(m, user, r, r.hyps[0]);
  return text;
});
const t0 = Date.now();
const c = execFileSync(exe, [modelFile, String(beam)].concat(learnMode ? ['--learn'] : [], nnFile ? ['--nn', nnFile] : []), { input: inputs.join('\n') + '\n', maxBuffer: 1 << 28 })
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
