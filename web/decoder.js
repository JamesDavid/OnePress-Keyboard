// Keypad decoder: word unigram + bigram model, beam search over word slots.
const KEYMAP = { a:'2',b:'2',c:'2',d:'3',e:'3',f:'3',g:'4',h:'4',i:'4',j:'5',k:'5',l:'5',
  m:'6',n:'6',o:'6',p:'7',q:'7',r:'7',s:'7',t:'8',u:'8',v:'8',w:'9',x:'9',y:'9',z:'9',"'":'#' };
const KEY_LETTERS = { '#':"'", '2':'abc','3':'def','4':'ghi','5':'jkl','6':'mno','7':'pqrs','8':'tuv','9':'wxyz' };

const QUESTION_STARTERS = new Set(['what','where','when','why','who','whom','whose','which','how',
  'can','could','would','should','will','shall','do','does','did','is','are','was','were','am',
  "isn't","aren't","don't","doesn't","didn't","can't","won't","wouldn't","shouldn't","couldn't",'have','has','may','might',
  'want','wanna','need','got','any','anyone','anybody','anything','ready','free','you','u']);

function wordKeys(w) { let s = ''; for (const c of w) s += KEYMAP[c]; return s; }

function buildModel(M) {
  const words = M.words, n = words.length;
  const uni = new Float64Array(n + M.punct.length + 1);
  for (let i = 0; i < n; i++) uni[i] = Math.exp(M.logp[i]);
  for (let i = 0; i < M.punct.length; i++) uni[n + i] = Math.exp(M.punctLogp[i]);
  const byKey = new Map();
  const keyed = [];
  for (let i = 0; i < n; i++) {
    const full = wordKeys(words[i]);
    // Apostrophes are optional: "don't" matches both 366#8 and 3668.
    const variants = full.includes('#') ? [full, full.replace(/#/g, '')] : [full];
    for (const k of variants) {
      if (!byKey.has(k)) byKey.set(k, []);
      byKey.get(k).push(i);         // vocab is frequency-ordered, so lists are too
      keyed.push([k, i]);
    }
  }
  keyed.sort((a, b) => (a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : a[1] - b[1]));
  const bi = new Map();
  for (const prev in M.bi) {
    const arr = M.bi[prev], m = new Map();
    for (let j = 0; j < arr.length; j += 2) m.set(arr[j], arr[j + 1]);
    bi.set(+prev, m);
  }
  const ctx = new Map();
  for (const k in M.ctx) ctx.set(+k, M.ctx[k]);
  const fullKeys = words.map(wordKeys);
  const display = new Array(n);
  for (const k in (M.display || {})) display[+k] = M.display[k];
  return { words, display, fullKeys, n, uni, byKey, keyed, bi, ctx, punct: M.punct, bos: M.bos };
}

// log P(cur | prev), interpolated (Witten-Bell style weight)
function lp(m, prev, cur) {
  const c = m.ctx.get(prev) || 0;
  const pu = m.uni[cur] || 1e-9;
  if (!c) return Math.log(pu);
  const row = m.bi.get(prev);
  const cb = (row && row.get(cur)) || 0;
  const lam = c / (c + 40);
  return Math.log(lam * cb / c + (1 - lam) * pu);
}

function prefixCandidates(m, prefix, limit, pred) {
  // binary search the first key >= prefix
  const a = m.keyed; let lo = 0, hi = a.length;
  while (lo < hi) { const mid = (lo + hi) >> 1; if (a[mid][0] < prefix) lo = mid + 1; else hi = mid; }
  const best = [];
  for (let i = lo; i < a.length && a[i][0].startsWith(prefix); i++) {
    const id = a[i][1];
    if (pred && !pred(id, a[i][0])) continue;
    if (best.includes(id)) continue;
    if (best.length < limit) { best.push(id); best.sort((x, y) => x - y); }
    else if (id < best[limit - 1]) { best[limit - 1] = id; best.sort((x, y) => x - y); }
  }
  return best;
}

// The key string holds predictive presses ('2'-'9', '0' space, '#') and, from exact
// (multi-tap) mode, literal characters: 'a'-'z', "'", '.', ',', '?', '!',
// and 'A'-'J' for the digits 0-9.
const LIT_PUNCT = new Set(['.', ',', '?', '!']);
function isWordChar(ch) {
  return (ch >= '2' && ch <= '9') || (ch >= 'a' && ch <= 'z') || ch === "'" || (ch >= 'A' && ch <= 'J');
}
function keyOf(ch) {               // the keypad key a stored character stands for
  if (ch >= 'a' && ch <= 'z') return KEYMAP[ch];
  if (ch === "'") return '#';
  return ch;                       // predictive digit, or a literal digit (never matches a word)
}
function litOf(ch) {               // the exact character, or null for a predictive press
  if ((ch >= 'a' && ch <= 'z') || ch === "'") return ch;
  if (ch >= 'A' && ch <= 'J') return String(ch.charCodeAt(0) - 65);
  return null;
}

// Split the key string into tokens: {type:'word', keys, lit[]}, {type:'punct', lit?}, {type:'space'}
function tokenize(keys) {
  // A predictive '#' between two word characters is an apostrophe; otherwise punctuation.
  const toks = [];
  for (let i = 0; i < keys.length; i++) {
    const ch = keys[i];
    const last = toks[toks.length - 1];
    if (ch === '0') toks.push({ type: 'space' });
    else if (ch === '#') {
      if (last && last.type === 'word' && isWordChar(keys[i + 1] || '')) { last.keys += '#'; last.lit.push(null); }
      else toks.push({ type: 'punct' });
    } else if (LIT_PUNCT.has(ch)) {
      toks.push({ type: 'punct', lit: ch });
    } else if (isWordChar(ch)) {
      if (last && last.type === 'word') { last.keys += keyOf(ch); last.lit.push(litOf(ch)); }
      else toks.push({ type: 'word', keys: keyOf(ch), lit: [litOf(ch)] });
    }
  }
  return toks;
}

// Does dictionary word `id` (matched through key string `key`) agree with the exact letters?
function litMatch(m, tok, id, key) {
  const text = key.includes('#') ? m.words[id] : m.words[id].replace(/'/g, '');
  for (let i = 0; i < tok.lit.length; i++) {
    if (tok.lit[i] !== null && text[i] !== tok.lit[i]) return false;
  }
  return true;
}

// Candidates for each slot: [{text, id, partial}]
function slotCandidates(m, tok, isLast) {
  if (tok.type === 'punct') {
    if (tok.lit) return [{ text: tok.lit, id: m.n + m.punct.indexOf(tok.lit), exact: true }];
    return m.punct.map((p, i) => ({ text: p, id: m.n + i }));
  }
  const hasLit = tok.lit.some(x => x !== null);
  const allLit = tok.lit.every(x => x !== null);
  // A contraction typed without its apostrophe ("im" for I'm) is allowed but slightly penalized.
  let ids = m.byKey.get(tok.keys) || [];
  if (hasLit) ids = ids.filter(id => litMatch(m, tok, id, tok.keys));
  const exact = ids.slice(0, 40).map(id =>
    ({ text: m.words[id], id, penalty: m.fullKeys[id] === tok.keys ? 0 : Math.log(0.5) }));
  if (isLast && !allLit) {
    // While still typing, also offer completions (shown truncated to what's typed).
    const seen = new Set(exact.map(c => c.id));
    const pred = hasLit ? (id, key) => litMatch(m, tok, id, key) : null;
    for (const id of prefixCandidates(m, tok.keys, 12, pred)) {
      if (seen.has(id)) continue;
      exact.push({ text: m.words[id].slice(0, tok.keys.length), id, partial: m.words[id], penalty: Math.log(0.5) });
    }
  }
  if (allLit) {
    // Spelled out exactly: always offer it as typed, even if it isn't in the word list.
    const typed = tok.lit.join('');
    const known = exact.filter(c => c.text.replace(/'/g, '') === typed.replace(/'/g, '') && c.text.length === typed.length);
    if (known.length) return known;
    return [{ text: typed, id: -1, literal: true }];
  }
  if (!exact.length) {
    const raw = [...tok.keys].map((k, i) => tok.lit[i] || (KEY_LETTERS[k] || '?')[0]).join('');
    exact.push({ text: raw, id: -1, unknown: true });
  }
  return exact;
}

function decode(m, keys, locks = {}, beamWidth = 40, nBest = 5) {
  const toks = tokenize(keys);
  const slots = [];
  toks.forEach((t, i) => { if (t.type !== 'space') slots.push({ tok: t, tokIndex: i }); });
  const lastTokIsWord = toks.length && toks[toks.length - 1].type === 'word';
  slots.forEach((s, j) => {
    const isLast = j === slots.length - 1 && lastTokIsWord;
    let c = slotCandidates(m, s.tok, isLast);
    s.all = c;
    const lock = locks[j];
    if (lock && lock.keys === s.tok.keys) {
      const hit = c.filter(x => (x.partial || x.text) === lock.text);
      if (hit.length) c = hit;
    }
    s.cands = c;
  });

  let beam = [{ score: 0, prev: m.bos, first: null, cf: null, path: [] }];
  slots.forEach((s, j) => {
    const isFinal = j === slots.length - 1;
    const next = [];
    for (const h of beam) {
      for (let ci = 0; ci < s.cands.length; ci++) {
        const c = s.cands[ci];
        let step = c.id < 0 ? (c.literal ? -14 : -25) : lp(m, h.prev, c.id) + (c.penalty || 0);
        let prev = c.id < 0 ? -1 : c.id;
        let first = h.first, cf = h.cf;
        if (c.id >= m.n) {
          // Punctuation: a word-pair model can't see how the sentence began,
          // so use the sentence's first word to judge question vs statement.
          const q = [first, cf].some(f => f !== null && QUESTION_STARTERS.has(m.words[f]));
          if (c.text === '?') step += q ? 2.5 : -1.5;
          else if (c.text === '.' && q) step -= 1.5;
          else if (c.text === ',' && isFinal) step -= 3;
          if (c.text !== ',') { prev = m.bos; first = null; }
          cf = null;
        } else {
          if (first === null) first = c.id;
          if (cf === null) cf = c.id;
        }
        next.push({ score: h.score + step, prev, first, cf, path: h.path.concat(ci) });
      }
    }
    // Hypotheses with the same state score every future slot the same way, so keep only the
    // best of each. State: the previous token plus whether the sentence/clause opener is a
    // question word (all the punctuation heuristic looks at).
    next.sort((a, b) => b.score - a.score);
    const qs = f => f === null ? 0 : QUESTION_STARTERS.has(m.words[f]) ? 1 : 2;
    const states = new Set();
    beam = [];
    for (const h of next) {
      const k = h.prev * 9 + qs(h.first) * 3 + qs(h.cf);
      if (states.has(k)) continue;
      states.add(k);
      beam.push(h);
      if (beam.length >= beamWidth) break;
    }
  });
  // collapse to distinct texts
  const out = [], seen = new Set();
  for (const h of beam) {
    const k = h.path.join(',');
    if (seen.has(k)) continue; seen.add(k);
    out.push(h);
    if (out.length >= nBest) break;
  }
  return { toks, slots, hyps: out };
}

// Render a hypothesis to display text with sentence capitalization.
function render(m, result, hyp) {
  const { toks, slots } = result;
  const bySlotTok = new Map();
  slots.forEach((s, j) => bySlotTok.set(s.tokIndex, j));
  let out = [], capNext = true;
  const pieces = [];
  toks.forEach((t, i) => {
    if (t.type === 'space') { pieces.push({ text: ' ', slot: -1 }); return; }
    const j = bySlotTok.get(i);
    const c = slots[j].cands[hyp.path[j]];
    let text = c.text;
    if (t.type === 'word') {
      const shown = c.id >= 0 && m.display[c.id];
      if (shown) text = c.partial ? shown.slice(0, text.length) : shown;
      if (text === 'i' || text.startsWith("i'")) text = 'I' + text.slice(1);
      // keep brand styling like iPhone / eBay at the start of a sentence
      if (capNext && !/^[a-z][A-Z]/.test(text)) text = text.charAt(0).toUpperCase() + text.slice(1);
      capNext = false;
    } else {
      capNext = text !== ',';
    }
    const partial = c.partial ? (m.display[c.id] || c.partial) : undefined;
    pieces.push({ text, slot: j, partial, unknown: c.unknown });
  });
  return pieces;
}

if (typeof module !== 'undefined') module.exports = { buildModel, decode, render, wordKeys, tokenize };
