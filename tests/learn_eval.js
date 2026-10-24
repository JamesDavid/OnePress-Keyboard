// Does learning from the user help? Replays each person's messages in order: type the message
// (words the model doesn't know yet are spelled in exact mode), score the decode, then learn
// from the message as sent, as if they had fixed any mistakes first.
//   node tests/learn_eval.js [users_dev.tsv] [--model onepress.bin] [--params a,b,base]
//                            [--before N] [--recent bonus,maxUni] [--nn onepress-nn.bin]
// --before N: give the decoder the person's previous N messages as the text before (start.before),
// one per line, as an app carrying context from message to message would.
// Files: model/corpora/nus/users_{dev,test,test_na}.tsv, built by model/prep_nus.py.
// Scores predicted words only (exactly spelled ones are always right), with and without learning.
const fs = require('fs'), path = require('path');
const D = require(path.join(__dirname, '../web/decoder.js'));

const args = process.argv.slice(2);
const opt = (k) => { const i = args.indexOf(k); return i >= 0 ? args.splice(i, 2)[1] : null; };
const modelFile = opt('--model') || path.join(__dirname, '../model/onepress.bin');
const params = opt('--params'), nBefore = +(opt('--before') || 0), recent = opt('--recent');
if (recent) D.recentParams(...recent.split(',').map(Number));
if (params) D.userParams(...params.split(',').map(Number));
const file = args[0] || path.join(__dirname, '../model/corpora/nus/users_dev.tsv');
const m = D.buildModel(fs.readFileSync(modelFile));
const nnFile = opt('--nn'), nn = nnFile ? D.buildNN(fs.readFileSync(nnFile), m) : undefined;
const known = new Set(m.words);
const TOK = /[a-z]+(?:'[a-z]+)?|[.,!?]/g;
const toks = s => s.toLowerCase().match(TOK) || [];

const users = new Map();
for (const line of fs.readFileSync(file, 'utf8').split('\n')) {
  const t = line.indexOf('\t');
  if (t < 0) continue;
  const uid = line.slice(0, t);
  if (!users.has(uid)) users.set(uid, []);
  users.get(uid).push(line.slice(t + 1));
}

function run(learning) {
  const st = { w: 0, wt: 0, iv: 0, ivt: 0, p: 0, pt: 0, perUser: [] };
  for (const [uid, msgs] of users) {
    const u = D.newUser(m), learned = new Set();
    let uw = 0, uwt = 0;
    for (const [mi, msg] of msgs.entries()) {
      const before = nBefore ? msgs.slice(Math.max(0, mi - nBefore), mi).map(x => x + '\n').join('') : undefined;
      const ref = toks(msg);
      let keys = '';
      const predicted = [];
      ref.forEach((x, i) => {
        if (/[.,!?]/.test(x)) keys += '#';
        else {
          if (i && !/[.,!?]/.test(ref[i - 1])) keys += '0';
          else if (i) keys += '0';
          const pred = known.has(x) || (learning && learned.has(x));
          keys += pred ? D.wordKeys(x.replace(/'/g, '')) : x;
          predicted.push(pred);
        }
      });
      const r = D.decode(m, keys, {}, 8, 1, { user: learning ? u : null, before, nn });
      const out = toks(D.render(m, r, r.hyps[0]).map(p => p.text).join(''));
      let wi = 0;
      ref.forEach((x, i) => {
        const ok = out[i] === x;
        if (/[.,!?]/.test(x)) { st.pt++; st.p += ok; return; }
        if (!predicted[wi++]) return;
        st.wt++; st.w += ok; uwt++; uw += ok;
        if (known.has(x)) { st.ivt++; st.iv += ok; }
      });
      if (learning) {
        // Learn the message as sent: decode it with every word spelled out exactly.
        const exact = ref.map((x, i) => (/[.,!?]/.test(x) ? { ',': ',', '.': '.', '?': '?', '!': '!' }[x] : (i ? '0' : '') + x)).join('');
        const rr = D.decode(m, exact, {}, 8, 1, { user: u });
        D.learn(m, u, rr, rr.hyps[0]);
        ref.forEach(x => { if (!known.has(x) && !/[.,!?]/.test(x)) learned.add(x); });
      }
    }
    st.perUser.push([uid, msgs.length, uw, uwt]);
  }
  return st;
}

const pct = (a, b) => (100 * a / b).toFixed(2) + '%';
const base = run(false), learn = run(true);
console.log(`${path.basename(file)}: ${users.size} users, ${[...users.values()].reduce((a, b) => a + b.length, 0)} messages`);
console.log(`                     no learning   learning`);
console.log(`  predicted words    ${pct(base.w, base.wt).padEnd(13)} ${pct(learn.w, learn.wt)}  (${base.wt} / ${learn.wt})`);
console.log(`  dictionary words   ${pct(base.iv, base.ivt).padEnd(13)} ${pct(learn.iv, learn.ivt)}  (${base.ivt})`);
console.log(`  punctuation        ${pct(base.p, base.pt).padEnd(13)} ${pct(learn.p, learn.pt)}  (${base.pt})`);
const big = learn.perUser.map((x, i) => [x, base.perUser[i]]).filter(([x]) => x[1] >= 50);
console.log(`  users with 50+ messages (no learning -> learning):`);
for (const [l, b] of big) console.log(`    ${l[0].slice(0, 8)} ${String(l[1]).padStart(5)} msgs  ${pct(b[2], b[3])} -> ${pct(l[2], l[3])}`);
