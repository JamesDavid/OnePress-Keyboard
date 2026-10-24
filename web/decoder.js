// Keypad decoder: word unigram + bigram model, beam search over word slots.
// Reads the KPD2 binary model (model/export_bin.py). Scores are integers (1/scale nats), so
// this file and the C decoder (c/onepress.c) produce identical results. Keep them in step.
const KEYMAP = { a:'2',b:'2',c:'2',d:'3',e:'3',f:'3',g:'4',h:'4',i:'4',j:'5',k:'5',l:'5',
  m:'6',n:'6',o:'6',p:'7',q:'7',r:'7',s:'7',t:'8',u:'8',v:'8',w:'9',x:'9',y:'9',z:'9',"'":'#' };
const KEY_LETTERS = { '#':"'", '2':'abc','3':'def','4':'ghi','5':'jkl','6':'mno','7':'pqrs','8':'tuv','9':'wxyz' };
const SECTIONS = ['wordText', 'wordOff', 'keyIdx', 'stripIdx', 'dispId', 'dispOff', 'dispText', 'uni',
  'rowStart', 'bow', 'next', 'lp', 'qStart', 'punct', 'params'];
const PARAMS = ['qQ', 'qN', 'dQ', 'cF', 'dB', 'cB', 'eB', 'apostrophe', 'completion', 'literal', 'unknown'];
const MAX_EXACT = 40, MAX_COMPLETIONS = 12;
const AFTER_NUMBER = -2;           // beam state after a number (the model has no number token)
const TIME_BONUS = 6;              // nats for "am"/"pm" right after a number

function wordKeys(w) { let s = ''; for (const c of w) s += KEYMAP[c]; return s; }

// bytes: Uint8Array (or Node Buffer) holding a KPD2 file.
function buildModel(bytes) {
  if (bytes.byteOffset % 4) bytes = new Uint8Array(bytes);
  const dv = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  if (String.fromCharCode(...bytes.subarray(0, 4)) !== 'KPD2') throw new Error('not a KPD2 model');
  const scale = dv.getUint16(6, true), n = dv.getUint16(8, true), nPunct = dv.getUint16(10, true);
  const bos = dv.getUint16(12, true), nSec = dv.getUint16(14, true);
  const sec = {};
  SECTIONS.forEach((name, i) => {
    if (i < nSec) sec[name] = [dv.getUint32(16 + 8 * i, true), dv.getUint32(20 + 8 * i, true)];
  });
  const at = (name, T) => new T(bytes.buffer, bytes.byteOffset + sec[name][0], sec[name][1] / T.BYTES_PER_ELEMENT);
  const utf8 = new TextDecoder();
  const wordText = at('wordText', Uint8Array), wordOff = at('wordOff', Uint32Array);
  const words = new Array(n);
  for (let i = 0; i < n; i++) words[i] = utf8.decode(wordText.subarray(wordOff[i], wordOff[i + 1]));
  const dispId = at('dispId', Uint16Array), dispOff = at('dispOff', Uint32Array), dispText = at('dispText', Uint8Array);
  const display = new Array(n);
  dispId.forEach((id, i) => { display[id] = utf8.decode(dispText.subarray(dispOff[i], dispOff[i + 1])); });
  const keyIdx = at('keyIdx', Uint16Array), stripIdx = at('stripIdx', Uint16Array);
  const fullKeys = words.map(wordKeys);
  const raw = at('params', Int16Array), params = {};
  PARAMS.forEach((k, i) => { params[k] = raw[i]; });
  return {
    words, display, fullKeys, n, bos, scale, params,
    timeIds: ['am', 'pm'].map(w => words.indexOf(w)).filter(i => i >= 0),
    punct: utf8.decode(at('punct', Uint8Array)).split(''),
    uni: at('uni', Int16Array), rowStart: at('rowStart', Uint32Array), bow: at('bow', Int16Array),
    next: at('next', Uint16Array), lp: at('lp', Int16Array), qStart: new Set(at('qStart', Uint16Array)),
    // The two key indexes, with each entry's key string. keyIdx holds every word under its
    // full keys; stripIdx holds apostrophe words again under their keys without '#'.
    indexes: [
      { ids: keyIdx, keys: Array.from(keyIdx, id => fullKeys[id]) },
      { ids: stripIdx, keys: Array.from(stripIdx, id => fullKeys[id].replace(/#/g, '')) },
    ],
  };
}

// log P(cur | prev) in model units. prev < 0 (an unknown word or a number) falls back to the
// unigram; right after a number, "am" and "pm" get a bonus.
function lp(m, prev, cur) {
  if (prev === AFTER_NUMBER) return m.uni[cur] + (m.timeIds.includes(cur) ? TIME_BONUS * m.scale : 0);
  if (prev < 0 || prev > m.bos) return m.uni[cur];     // > bos: a word the user taught it
  let lo = m.rowStart[prev], hi = m.rowStart[prev + 1];
  while (lo < hi) {
    const mid = (lo + hi) >> 1, x = m.next[mid];
    if (x === cur) return m.lp[mid];
    if (x < cur) lo = mid + 1; else hi = mid;
  }
  return m.bow[prev] + m.uni[cur];
}

// First entry in an index whose key is >= k.
function lowerBound(ix, k) {
  let lo = 0, hi = ix.keys.length;
  while (lo < hi) { const mid = (lo + hi) >> 1; if (ix.keys[mid] < k) lo = mid + 1; else hi = mid; }
  return lo;
}

// Ids whose key is exactly k (ascending, which is frequency order), with the key matched.
function exactMatches(m, k) {
  const out = [];
  for (const ix of m.indexes) {
    for (let i = lowerBound(ix, k); i < ix.keys.length && ix.keys[i] === k; i++) out.push(ix.ids[i]);
  }
  return out.sort((a, b) => a - b);
}

// The `limit` most frequent distinct ids with a key starting with prefix that pass pred(id, key).
function prefixCandidates(m, prefix, limit, pred) {
  const best = [];
  for (const ix of m.indexes) {
    for (let i = lowerBound(ix, prefix); i < ix.keys.length && ix.keys[i].startsWith(prefix); i++) {
      const id = ix.ids[i];
      if (pred && !pred(id, ix.keys[i])) continue;
      if (best.includes(id)) continue;
      if (best.length < limit) { best.push(id); best.sort((x, y) => x - y); }
      else if (id < best[limit - 1]) { best[limit - 1] = id; best.sort((x, y) => x - y); }
    }
  }
  return best;
}

// The key string holds predictive presses ('2'-'9', '0' space, '#') and, from exact
// (multi-tap) mode or a held number key, literal characters: 'a'-'z', "'", '.', ',', '?',
// '!', and 'A'-'J' for the digits 0-9.
const LIT_PUNCT = new Set(['.', ',', '?', '!']);
function isLetterKey(ch) {          // a press that can be part of a word's letters
  return (ch >= '2' && ch <= '9') || (ch >= 'a' && ch <= 'z') || ch === "'";
}
function isDigitLit(ch) { return ch >= 'A' && ch <= 'J'; }
function keyOf(ch) {               // the keypad key a stored character stands for
  if (ch >= 'a' && ch <= 'z') return KEYMAP[ch];
  if (ch === "'") return '#';
  return ch;                       // predictive digit, or a literal digit (never matches a word)
}
function litOf(ch) {               // the exact character, or null for a predictive press
  if ((ch >= 'a' && ch <= 'z') || ch === "'") return ch;
  if (isDigitLit(ch)) return String(ch.charCodeAt(0) - 65);
  return null;
}

// Split the key string into tokens: {type:'word', keys, lit[]}, {type:'punct', lit?},
// {type:'space'}, {type:'number', keys}.
// Digits end a word: "4" + 3837 is "4" then "ever". A number runs on through further digits
// and through '#', '.' or ',' between digits; a '#' just before a number is '$', so
// #6#000#00 is "$6,000.00" (see formatNumber). Digits next to exactly spelled letters stay in
// the word, for call signs like ke7aqa.
function tokenize(keys) {
  const toks = [];
  for (let i = 0; i < keys.length; i++) {
    const ch = keys[i], nxt = keys[i + 1] || '';
    const last = toks[toks.length - 1];
    if (ch === '0') toks.push({ type: 'space' });
    else if ((ch === '#' || ch === '.' || ch === ',') && last && last.type === 'number' &&
             /[0-9]$/.test(last.keys) && isDigitLit(nxt)) {
      last.keys += ch === '#' ? 's' : ch;       // 's': a separator for formatNumber to choose
    } else if (ch === '#') {
      // A predictive '#' between two letters is an apostrophe; otherwise punctuation.
      if (last && last.type === 'word' && isLetterKey(nxt)) { last.keys += '#'; last.lit.push(null); }
      else toks.push({ type: 'punct' });
    } else if (LIT_PUNCT.has(ch)) {
      toks.push({ type: 'punct', lit: ch });
    } else if (isDigitLit(ch)) {
      const d = litOf(ch), before = toks[toks.length - 2];
      if (last && last.type === 'number') last.keys += d;
      else if (last && last.type === 'word' && last.lit[last.lit.length - 1] !== null) { last.keys += ch; last.lit.push(d); }
      else if (last && last.type === 'punct' && !last.lit && keys[i - 1] === '#' &&
               !(before && (before.type === 'word' || before.type === 'number'))) {
        toks[toks.length - 1] = { type: 'number', keys: '$' + d };
      } else toks.push({ type: 'number', keys: d });
    } else if (isLetterKey(ch)) {
      if (last && last.type === 'number' && litOf(ch) !== null && /^[0-9]+$/.test(last.keys)) {
        // Digits followed by an exactly spelled letter are one word (2e0abc, 90's).
        toks[toks.length - 1] = { type: 'word', keys: [...last.keys].map(c => String.fromCharCode(65 + +c)).join(''),
          lit: [...last.keys] };
      }
      const cur = toks[toks.length - 1];
      if (cur && cur.type === 'word') { cur.keys += keyOf(ch); cur.lit.push(litOf(ch)); }
      else toks.push({ type: 'word', keys: keyOf(ch), lit: [litOf(ch)] });
    }
  }
  return toks;
}

// A number's text. Each 's' separator becomes ',' when the groups read as thousands (a first
// group of 1-3 digits, then groups of 3, with an optional last group of another length after
// a '.'), otherwise '.': 6s000s00 -> 6,000.00, 1s500 -> 1,500, 3s14 -> 3.14, 10s0s0s1 -> 10.0.0.1.
// time: the words around it say it's a time (render decides), so H s MM is H:MM.
function formatNumber(keys, time) {
  if (time && /^[0-9]{1,2}s[0-9]{2}$/.test(keys) && +keys.slice(0, -3) <= 24 && +keys.slice(-2) <= 59) {
    return keys.replace('s', ':');
  }
  const g = keys.replace('$', '').split(/[s.,]/).map(x => x.length);
  let commas = g[0] <= 3;
  for (let k = 1; k < g.length - 1; k++) if (g[k] !== 3) commas = false;
  let out = '', k = 0;
  for (const ch of keys) {
    if (ch === 's') { k++; out += commas && g[k] === 3 ? ',' : '.'; }
    else { if (ch === '.' || ch === ',') k++; out += ch; }
  }
  return out;
}

// Does dictionary word `id` (matched through key string `key`) agree with the exact letters?
function litMatch(m, tok, id, key) { return litMatchText(tok, m.words[id], key); }
function litMatchText(tok, word, key) {
  const text = key.includes('#') ? word : word.replace(/'/g, '');
  for (let i = 0; i < tok.lit.length; i++) {
    if (tok.lit[i] !== null && text[i] !== tok.lit[i]) return false;
  }
  return true;
}

// Learned words may hold digits (call signs like ke7aqa). Their keys: letters as usual, a digit
// 2-9 as its own key (so it can be typed with one press like a letter) and 0 or 1 as the held
// digit ('A', 'B'). userTyped maps a typed key string the same way (a held 7 'H' -> '7'); the
// exact letters/digits (tok.lit) still have to agree, so a held 7 never matches a p.
function userKeys(w) {
  let s = '';
  for (const c of w) s += c >= '0' && c <= '9' ? (c >= '2' ? c : String.fromCharCode(17 + c.charCodeAt(0))) : KEYMAP[c];
  return s;
}
function userTyped(k) { return k.replace(/[C-J]/g, c => String(c.charCodeAt(0) - 65)); }

// How learned word w fits word token tok (typed keys already through userTyped): {full} for a
// whole match (full: with its apostrophes), {partial} for its beginning if `partial`, else null.
function userMatch(w, tok, keys, partial) {
  const full = userKeys(w), strip = full.replace(/#/g, '');
  if (full === keys || (strip !== full && strip === keys)) {
    return litMatchText(tok, w, full === keys ? full : strip) ? { full: full === keys } : null;
  }
  if (!partial) return null;
  const key = full.startsWith(keys) ? full : strip.startsWith(keys) ? strip : null;
  return key && litMatchText(tok, w, key) ? { partial: true } : null;
}

// Typing a call sign with the digit held splits it (53, held 7, 272). A run of word and number
// tokens with nothing between them that spells a learned word is that one word; the last run
// may be its beginning.
function joinLearned(toks, u) {
  if (!u || !u.words.some(w => /[0-9]/.test(w))) return toks;
  const out = [];
  for (let i = 0; i < toks.length;) {
    let j = i;
    while (j < toks.length && (toks[j].type === 'word' || (toks[j].type === 'number' && /^[0-9]+$/.test(toks[j].keys)))) j++;
    if (j - i > 1) {
      const run = toks.slice(i, j);
      const tok = {
        type: 'word',
        keys: run.map(t => t.type === 'word' ? t.keys : [...t.keys].map(d => String.fromCharCode(65 + +d)).join('')).join(''),
        lit: [].concat(...run.map(t => t.type === 'word' ? t.lit : [...t.keys])),
      };
      const keys = userTyped(tok.keys);
      if (u.words.some(w => userMatch(w, tok, keys, j === toks.length))) { out.push(tok); i = j; continue; }
    }
    if (j === i) j = i + 1;
    while (i < j) out.push(toks[i++]);
  }
  return out;
}

// Candidates for each slot: [{text, id, partial, penalty}]
function slotCandidates(m, tok, isLast, u) {
  const P = m.params;
  if (tok.type === 'number') return [{ text: formatNumber(tok.keys), id: -1, number: true }];
  if (tok.type === 'punct') {
    if (tok.lit) return [{ text: tok.lit, id: m.n + m.punct.indexOf(tok.lit), exact: true }];
    return m.punct.map((p, i) => ({ text: p, id: m.n + i }));
  }
  const hasLit = tok.lit.some(x => x !== null);
  const allLit = tok.lit.every(x => x !== null);
  // A contraction typed without its apostrophe ("im" for I'm) is allowed but slightly penalized.
  let ids = exactMatches(m, tok.keys);
  if (hasLit) ids = ids.filter(id => litMatch(m, tok, id, tok.keys));
  const exact = ids.slice(0, MAX_EXACT).map(id =>
    ({ text: m.words[id], id, penalty: m.fullKeys[id] === tok.keys ? 0 : P.apostrophe }));
  // Words this person taught it: exact matches first, completions after the dictionary's.
  const userExact = [], userPartial = [];
  if (u) {
    const keys = userTyped(tok.keys), partial = isLast && !allLit;
    u.words.forEach((w, k) => {
      const id = m.bos + 1 + k, f = userMatch(w, tok, keys, partial);
      if (!f) return;
      if (!f.partial && userExact.length < MAX_USER_CANDS)
        userExact.push({ text: w, id, penalty: f.full ? 0 : P.apostrophe });
      else if (f.partial && userPartial.length < MAX_USER_CANDS)
        userPartial.push({ text: w.slice(0, tok.keys.length), id, partial: w, penalty: P.completion });
    });
  }
  exact.push(...userExact);
  if (isLast && !allLit) {
    // While still typing, also offer completions (shown truncated to what's typed).
    const seen = new Set(exact.map(c => c.id));
    const pred = hasLit ? (id, key) => litMatch(m, tok, id, key) : null;
    for (const id of prefixCandidates(m, tok.keys, MAX_COMPLETIONS, pred)) {
      if (seen.has(id)) continue;
      exact.push({ text: m.words[id].slice(0, tok.keys.length), id, partial: m.words[id], penalty: P.completion });
    }
    exact.push(...userPartial);
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

// start: { prev: token id before the composition (default BOS, -1 for an unknown word),
//          user: what this person has typed (newUser / learn), optional }
function decode(m, keys, locks = {}, beamWidth = 8, nBest = 5, start = {}) {
  const P = m.params;
  const u = start.user && start.user.bos === m.bos ? start.user : null;
  const toks = joinLearned(tokenize(keys), u);
  const slots = [];
  toks.forEach((t, i) => { if (t.type !== 'space') slots.push({ tok: t, tokIndex: i }); });
  const lastTokIsWord = toks.length && toks[toks.length - 1].type === 'word';
  slots.forEach((s, j) => {
    const isLast = j === slots.length - 1 && lastTokIsWord;
    let c = slotCandidates(m, s.tok, isLast, u);
    s.all = c;
    const lock = locks[j];
    if (lock && lock.keys === s.tok.keys) {
      const hit = c.filter(x => (x.partial || x.text) === lock.text);
      if (hit.length) c = hit;
    }
    s.cands = c;
  });

  const startPrev = start.prev === undefined ? m.bos : start.prev;
  let beam = [{ score: 0, prev: startPrev, first: null, cf: null, path: [] }];
  slots.forEach((s, j) => {
    const isFinal = j === slots.length - 1;
    const next = [];
    for (const h of beam) {
      for (let ci = 0; ci < s.cands.length; ci++) {
        const c = s.cands[ci];
        let step = c.id < 0 ? (c.number ? 0 : c.literal ? P.literal : P.unknown) : tokenScore(m, u, h.prev, c.id) + (c.penalty || 0);
        let prev = c.number ? AFTER_NUMBER : c.id < 0 ? -1 : c.id;
        let first = h.first, cf = h.cf;
        if (c.id >= m.n && c.id < m.bos) {
          // Punctuation: a word-pair model can't see how the sentence began,
          // so use the sentence's first word to judge question vs statement.
          const q = [first, cf].some(f => f !== null && m.qStart.has(f));
          if (c.text === '?') step += q ? P.qQ : P.qN;
          else if (c.text === '.') step += P.dB + (q ? P.dQ : 0);
          else if (c.text === ',') step += P.cB + (isFinal ? P.cF : 0);
          else if (c.text === '!') step += P.eB;
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
    // question word (all the punctuation heuristic looks at). The sort is stable, so ties
    // keep generation order; the C decoder relies on the same rule.
    next.sort((a, b) => b.score - a.score);
    const qs = f => f === null ? 0 : m.qStart.has(f) ? 1 : 2;
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
  return { toks, slots, hyps: beam.slice(0, nBest) };
}

// Render a hypothesis to display text with sentence capitalization.
// start.cap: capitalize the first word (default true; false mid-sentence).
const TIME_BEFORE = new Set(['at', 'by', 'until', 'til', 'till', 'around', 'before', 'after', 'from', 'since']);
const TIME_AFTER = new Set(['am', 'pm']);

function render(m, result, hyp, start = {}) {
  const { toks, slots } = result;
  const bySlotTok = new Map();
  slots.forEach((s, j) => bySlotTok.set(s.tokIndex, j));
  // The dictionary word chosen for the nearest token before/after toks[i] (spaces skipped).
  const wordNear = (i, dir) => {
    for (let k = i + dir; k >= 0 && k < toks.length; k += dir) {
      if (toks[k].type === 'space') continue;
      if (toks[k].type !== 'word') return null;
      const j = bySlotTok.get(k), c = slots[j].cands[hyp.path[j]];
      return c.id >= 0 && c.id < m.n && !c.partial ? m.words[c.id] : null;
    }
    return null;
  };
  let capNext = start.cap === undefined ? true : start.cap;
  const pieces = [];
  toks.forEach((t, i) => {
    if (t.type === 'space') { pieces.push({ text: ' ', slot: -1 }); return; }
    const j = bySlotTok.get(i);
    const c = slots[j].cands[hyp.path[j]];
    let text = c.text;
    if (t.type === 'number') {
      text = formatNumber(t.keys, TIME_BEFORE.has(wordNear(i, -1)) || TIME_AFTER.has(wordNear(i, 1)));
      capNext = false;
    } else if (t.type === 'word') {
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

// Probability of each letter a-z coming next, for sizing QWERTY keys (null if unknown).
// Floating point is fine here: it only scales keys, so it needn't match other decoders exactly.
function nextLetterProbs(m, result, hyp, start = {}) {
  const S = m.scale, startPrev = start.prev === undefined ? m.bos : start.prev;
  const prevContext = slotIndex => {
    if (slotIndex < 0 || !hyp) return startPrev;
    const s = result.slots[slotIndex], c = s.cands[hyp.path[slotIndex]];
    if (c.id < 0 || c.id > m.bos) return -1;
    if (c.id >= m.n && c.text !== ',') return m.bos;
    return c.id;
  };
  const p = new Float64Array(26);
  const toks = result ? result.toks : [];
  const last = toks[toks.length - 1];
  if (last && last.type === 'word') {
    // Word in progress: weight every word that starts with these keys by P(word | previous word).
    const k = last.keys, prev = prevContext(result.slots.length - 2);
    const seen = new Set();
    for (const ix of m.indexes) {
      for (let i = lowerBound(ix, k); i < ix.keys.length && ix.keys[i].startsWith(k); i++) {
        const id = ix.ids[i], key = ix.keys[i];
        if (seen.has(id) || key.length <= k.length) continue;
        seen.add(id);
        const text = key.includes('#') ? m.words[id] : m.words[id].replace(/'/g, '');
        const c = text.charCodeAt(k.length) - 97;
        if (c >= 0 && c < 26) p[c] += Math.exp(lp(m, prev, id) / S);
      }
    }
  } else {
    // Start of a word: P(first letter | previous word) = backoff share of the unigram
    // first-letter mass, corrected by the row's explicit pairs.
    const prev = prevContext(result ? result.slots.length - 1 : -1);
    if (!m.firstLetter) {
      m.firstLetter = new Float64Array(26);
      for (let i = 0; i < m.n; i++) {
        const c = m.words[i].charCodeAt(0) - 97;
        if (c >= 0 && c < 26) m.firstLetter[c] += Math.exp(m.uni[i] / S);
      }
    }
    const bow = prev < 0 ? 0 : m.bow[prev];
    for (let c = 0; c < 26; c++) p[c] = Math.exp(bow / S) * m.firstLetter[c];
    if (prev >= 0) {
      for (let e = m.rowStart[prev]; e < m.rowStart[prev + 1]; e++) {
        const id = m.next[e];
        if (id >= m.n) continue;
        const c = m.words[id].charCodeAt(0) - 97;
        if (c >= 0 && c < 26) p[c] += Math.exp(m.lp[e] / S) - Math.exp((bow + m.uni[id]) / S);
      }
    }
  }
  let sum = 0; for (const v of p) sum += Math.max(v, 0);
  if (sum > 0) for (let c = 0; c < 26; c++) p[c] = Math.max(p[c], 0) / sum;
  return sum > 0 ? p : null;
}

// ---- Learning from the user ----
// A small fixed-size table of what this person types, read by decode() (start.user) and
// updated by learn(): words the dictionary lacks (spelled once in exact mode, predicted from
// then on) and counts of each token and token pair they used, which add a bonus to those
// choices. Mirrors op_user in c/onepress.c: same sizes, same integer tables, same eviction.
// Ids: learned word k is bos + 1 + k. It belongs to one model (u.bos must match).
const USER_WORDS = 256, USER_WORD_LEN = 23, USER_PAIRS = 1024, MAX_USER_CANDS = 4;
const USER_ANY = 0xFFFD;           // pair prev for a token's own count
// Bonus by count (capped at 15), in model units (1/256 nat): round(256 * a * ln(1 + count)),
// a = 4 for a token, 3 for a pair; tuned on the NUS dev users (tests/learn_eval.js).
const USER_UNI = [0, 710, 1125, 1420, 1648, 1835, 1993, 2129, 2250, 2358, 2455, 2545, 2627, 2702, 2773, 2839];
const USER_PAIR = [0, 532, 844, 1065, 1236, 1376, 1494, 1597, 1687, 1768, 1842, 1908, 1970, 2027, 2080, 2129];
let USER_WORD_BASE = -2560;        // log P of a learned word before its bonuses (-10 nats)
// For tuning only: replace the tables with a = uni, pair and the base (nats).
function userParams(uni, pair, base) {
  for (let c = 0; c < 16; c++) {
    USER_UNI[c] = Math.round(uni * 256 * Math.log(1 + c));
    USER_PAIR[c] = Math.round(pair * 256 * Math.log(1 + c));
  }
  USER_WORD_BASE = Math.round(base * 256);
}

function newUser(m) { return { bos: m.bos, words: [], pairs: [] }; }   // pairs: [prev, cur, count], sorted

// Index of pair (prev, cur), or -(insertion point) - 1.
function userFind(u, prev, cur) {
  let lo = 0, hi = u.pairs.length;
  const k = prev * 65536 + cur;
  while (lo < hi) {
    const mid = (lo + hi) >> 1, e = u.pairs[mid], x = e[0] * 65536 + e[1];
    if (x === k) return mid;
    if (x < k) lo = mid + 1; else hi = mid;
  }
  return -lo - 1;
}
function userCount(u, prev, cur) { const i = userFind(u, prev, cur); return i >= 0 ? u.pairs[i][2] : 0; }

function tokenScore(m, u, prev, id) {
  let s = id > m.bos ? USER_WORD_BASE : lp(m, prev, id);
  if (u) {
    s += USER_UNI[Math.min(userCount(u, USER_ANY, id), 15)];
    if (prev >= 0) s += USER_PAIR[Math.min(userCount(u, prev, id), 15)];
  }
  return s;
}

function userBump(u, prev, cur) {
  let i = userFind(u, prev, cur);
  if (i >= 0) { u.pairs[i][2] = Math.min(255, u.pairs[i][2] + 1); return; }
  // Full: halve every count and drop the ones that reach zero, until there is room.
  while (u.pairs.length >= USER_PAIRS) u.pairs = u.pairs.filter(e => (e[2] >>= 1) > 0);
  i = -userFind(u, prev, cur) - 1;
  u.pairs.splice(i, 0, [prev, cur, 1]);
}

// Id of learned word w, adding it (replacing the least used one when full).
function userWord(m, u, w) {
  let k = u.words.indexOf(w);
  if (k < 0 && u.words.length < USER_WORDS) { u.words.push(w); k = u.words.length - 1; }
  else if (k < 0) {
    k = 0;
    for (let j = 1; j < u.words.length; j++) {
      if (userCount(u, USER_ANY, m.bos + 1 + j) < userCount(u, USER_ANY, m.bos + 1 + k)) k = j;
    }
    const id = m.bos + 1 + k;
    u.pairs = u.pairs.filter(e => e[0] !== id && e[1] !== id);
    u.words[k] = w;
  }
  return m.bos + 1 + k;
}

// Learn from text the person accepted (sent, copied): hyp as decoded, with their corrections.
// Words still being completed and unmatched key strings are skipped; a word spelled exactly
// that the dictionary lacks (letters, apostrophes and digits: ke7aqa) becomes a learned word.
function learn(m, u, result, hyp, start = {}) {
  if (!u || u.bos !== m.bos || !hyp) return;
  let prev = start.prev === undefined ? m.bos : start.prev;
  result.slots.forEach((s, j) => {
    const c = s.cands[hyp.path[j]];
    let id = c.id;
    if (c.number) { prev = AFTER_NUMBER; return; }
    if (c.literal && /^[a-z'0-9]+$/.test(c.text) && c.text.length <= USER_WORD_LEN) id = userWord(m, u, c.text);
    else if (c.partial || id < 0) { prev = -1; return; }
    userBump(u, USER_ANY, id);
    if (prev >= 0) userBump(u, prev, id);
    prev = id >= m.n && id < m.bos && c.text !== ',' ? m.bos : id;
  });
}

if (typeof module !== 'undefined') module.exports = { buildModel, decode, render, nextLetterProbs, exactMatches, wordKeys, tokenize, formatNumber,
  newUser, learn, USER_UNI, USER_PAIR, userParams };
