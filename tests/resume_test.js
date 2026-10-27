// Resuming after a finished sentence must not change anything. Types messages of several
// sentences one key at a time and checks every prefix: decode as typed (resuming) against a
// decode from scratch, in JS, and the C decoder (fed the same prefixes, so it resumes too)
// against JS. Also with the text before, QWERTY letters, learning between messages, a network.
//   node tests/resume_test.js [--model onepress.bin] [--nn onepress-nn.bin] [--n 150] [--learn] [--text file]
// --text: messages from that file instead, three lines each (Chinese: the pinyin column of
// corpora/zh/dev.txt with the spaces taken out, so the decoder splits the words).
const fs = require('fs'), path = require('path'), { execFileSync } = require('child_process');
const D = require(path.join(__dirname, '../web/decoder.js'));
const args = process.argv.slice(2);
const opt = (k, d) => { const i = args.indexOf(k); return i >= 0 ? args.splice(i, 2)[1] : d; };
const learnMode = args.includes('--learn');
const modelFile = opt('--model', path.join(__dirname, '../model/onepress.bin')), nnFile = opt('--nn'), N = +opt('--n', 150);
const exe = path.join(__dirname, '../build/opdecode' + (process.platform === 'win32' ? '.exe' : ''));
const m = D.buildModel(fs.readFileSync(modelFile));
const fresh = D.buildModel(fs.readFileSync(modelFile));        // never resumes (resume cleared each time)
const nn = nnFile ? D.buildNN(fs.readFileSync(nnFile), m) : undefined;
const nnFresh = nnFile ? D.buildNN(fs.readFileSync(nnFile), fresh) : undefined;

// Messages with at least two sentences, from the chat and NUS dev sets.
const msgs = [], textFile = opt('--text');
if (textFile) {
  const t = fs.readFileSync(textFile, 'utf8').split('\n').filter(Boolean);
  for (let i = 0; i + 2 < t.length; i += 3) msgs.push(t.slice(i, i + 3).join(' '));
}
for (const f of textFile ? [] : ['../model/corpora/chat/dev_chat.txt', '../model/corpora/nus/dev.txt']) {
  const p = path.join(__dirname, f);
  if (fs.existsSync(p)) for (const s of fs.readFileSync(p, 'utf8').split('\n')) if (/[.!?] \w.*[.!?,]? \w/.test(s)) msgs.push(s);
}
const L = 'a-zß-öø-ÿ';
let seed = 99;
const rnd = n => { seed = (seed * 1103515245 + 12345) & 0x7fffffff; return seed % n; };
const lines = [], expect = [];
const uJS = learnMode ? D.newUser(m) : null, uFresh = learnMode ? D.newUser(fresh) : null;
let resumed = 0, total = 0, tJs = 0, tFresh = 0;
for (const msg of msgs.slice(0, N)) {
  const low = msg.toLowerCase().replace(/'/g, '');
  const keys = [...low].map(c => c === ' ' ? '0' : '.,!?'.includes(c) ? '#' : D.wordKeys(c) || '').join('');
  const qwerty = rnd(3) === 0, before = rnd(3) === 0 ? 'ok see you then.\n' : undefined;
  const hint = qwerty ? [...low].map(c => /[a-z]/.test(c) ? c : ' ').join('') : '';
  let r, rf;
  for (let i = 1; i <= keys.length; i++) {
    const k = keys.slice(0, i), h = hint.slice(0, i);
    const prevResume = m.resume;
    let t0 = process.hrtime.bigint();
    r = D.decode(m, k, {}, 8, 1, { hint: h, before, user: uJS, nn });
    tJs += Number(process.hrtime.bigint() - t0);
    if (m.resume === prevResume && prevResume && k.startsWith(prevResume.keys) && k.length > prevResume.keys.length) resumed++;
    total++;
    fresh.resume = null;
    t0 = process.hrtime.bigint();
    rf = D.decode(fresh, k, {}, 8, 1, { hint: h, before, user: uFresh, nn: nnFresh });
    tFresh += Number(process.hrtime.bigint() - t0);
    const a = D.render(m, r, r.hyps[0]).map(p => p.text).join(''), b = D.render(fresh, rf, rf.hyps[0]).map(p => p.text).join('');
    if (a !== b || r.hyps[0].score !== rf.hyps[0].score) {
      console.log(`JS MISMATCH at ${JSON.stringify(k)}\n  resumed: ${a}\n  fresh:   ${b}`);
      process.exit(1);
    }
    lines.push(k + '\t' + (before ? before.replace(/\n/g, '|') : '') + '\t' + h);
    expect.push(b);
  }
  if (learnMode) { D.learn(m, uJS, r, r.hyps[0]); D.learn(fresh, uFresh, rf, rf.hyps[0]); }
}
console.log(`JS: ${total} prefixes of ${Math.min(N, msgs.length)} messages identical, about ${resumed} resumed; ` +
  `${(tJs / 1e6).toFixed(0)} ms typed vs ${(tFresh / 1e6).toFixed(0)} ms from scratch`);

// C: the same prefixes in order through one decoder (learning after each message's last line).
// opdecode learns from every line with --learn, so only compare without learning here.
if (!learnMode) {
  const c = execFileSync(exe, [modelFile, '8'].concat(nnFile ? ['--nn', nnFile] : []), { input: lines.join('\n') + '\n', maxBuffer: 1 << 28 })
    .toString().split(/\r?\n/);
  let bad = 0;
  lines.forEach((k, i) => { if (c[i] !== expect[i] && bad++ < 5) console.log(`C MISMATCH at ${JSON.stringify(k)}\n  c:  ${c[i]}\n  js: ${expect[i]}`); });
  console.log(`C: ${lines.length - bad}/${lines.length} identical`);
  process.exit(bad ? 1 : 0);
}
