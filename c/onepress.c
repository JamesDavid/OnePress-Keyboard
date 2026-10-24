/* OnePress decoder. Mirrors web/decoder.js; see onepress.h. */
#include "onepress.h"

#include <stdlib.h>
#include <string.h>

enum { TOK_WORD, TOK_PUNCT, TOK_SPACE, TOK_NUM };
enum { N_SECTIONS = 15 };

static const char KEY_OF[26] = "22233344455566677778889999";
static const char FIRST_LETTER[8] = "adgjmptw";     /* first letter of keys 2-9 */
#define AFTER_NUMBER 0xFFFE     /* beam state after a number (the model has no number token) */
#define TIME_BONUS 6            /* nats for "am"/"pm" right after a number */
static const char *const TIME_BEFORE[] = { "at", "by", "until", "til", "till", "around", "before", "after", "from", "since" };
static const char *const TIME_AFTER[] = { "am", "pm" };

static int find_word(const op_model *m, const char *w);

/* ---- model ---- */

static uint16_t rd16(const uint8_t *p) { return (uint16_t)(p[0] | p[1] << 8); }
static uint32_t rd32(const uint8_t *p) { return (uint32_t)p[0] | (uint32_t)p[1] << 8 | (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24; }

int op_model_open(op_model *m, const void *data, size_t size) {
    const uint8_t *b = (const uint8_t *)data;
    const void *sec[N_SECTIONS];
    uint32_t len[N_SECTIONS];
    if (!m || !b || ((uintptr_t)b & 3) || size < 16 || memcmp(b, "KPD2", 4) != 0) return OP_ERR_MODEL;
    if (rd16(b + 4) != 1 || rd16(b + 14) < N_SECTIONS || size < 16 + 8u * N_SECTIONS) return OP_ERR_MODEL;
    m->scale = rd16(b + 6);
    m->n_words = rd16(b + 8);
    m->n_punct = rd16(b + 10);
    m->bos = rd16(b + 12);
    for (int i = 0; i < N_SECTIONS; i++) {
        uint32_t off = rd32(b + 16 + 8 * i);
        len[i] = rd32(b + 20 + 8 * i);
        if ((off & 3) || off > size || len[i] > size - off) return OP_ERR_MODEL;
        sec[i] = b + off;
    }
    m->word_text = (const char *)sec[0];
    m->word_off = (const uint32_t *)sec[1];
    m->key_idx = (const uint16_t *)sec[2];
    m->strip_idx = (const uint16_t *)sec[3];
    m->n_strip = len[3] / 2;
    m->disp_id = (const uint16_t *)sec[4];
    m->n_disp = len[4] / 2;
    m->disp_off = (const uint32_t *)sec[5];
    m->disp_text = (const char *)sec[6];
    m->uni = (const int16_t *)sec[7];
    m->row_start = (const uint32_t *)sec[8];
    m->bow = (const int16_t *)sec[9];
    m->next = (const uint16_t *)sec[10];
    m->lp = (const int16_t *)sec[11];
    m->q_start = (const uint16_t *)sec[12];
    m->n_q = len[12] / 2;
    m->punct = (const char *)sec[13];
    if (len[13] != m->n_punct || len[14] < 2 * OP_N_PARAMS || m->bos != m->n_words + m->n_punct ||
        len[1] != 4u * (m->n_words + 1u) || len[2] != 2u * m->n_words || len[8] != 4u * (m->bos + 2u))
        return OP_ERR_MODEL;
    for (int i = 0; i < OP_N_PARAMS; i++) m->param[i] = (int16_t)rd16((const uint8_t *)sec[14] + 2 * i);
    for (int i = 0; i < 2; i++) m->time_id[i] = (uint16_t)find_word(m, TIME_AFTER[i]);
    return OP_OK;
}

int op_word(const op_model *m, uint16_t id, const char **text) {
    *text = m->word_text + m->word_off[id];
    return (int)(m->word_off[id + 1] - m->word_off[id]);
}

/* log P(cur | prev) in model units; prev OP_NONE (unknown word) or AFTER_NUMBER falls back to
 * the unigram, and right after a number "am" and "pm" get a bonus. */
static int32_t lp(const op_model *m, uint16_t prev, uint16_t cur) {
    if (prev == AFTER_NUMBER)
        return m->uni[cur] + (cur == m->time_id[0] || cur == m->time_id[1] ? TIME_BONUS * m->scale : 0);
    if (prev == OP_NONE) return m->uni[cur];
    uint32_t lo = m->row_start[prev], hi = m->row_start[prev + 1];
    while (lo < hi) {
        uint32_t mid = (lo + hi) / 2;
        uint16_t x = m->next[mid];
        if (x == cur) return m->lp[mid];
        if (x < cur) lo = mid + 1; else hi = mid;
    }
    return m->bow[prev] + m->uni[cur];
}

static int is_q_start(const op_model *m, uint16_t id) {
    uint32_t lo = 0, hi = m->n_q;
    while (lo < hi) {
        uint32_t mid = (lo + hi) / 2;
        if (m->q_start[mid] == id) return 1;
        if (m->q_start[mid] < id) lo = mid + 1; else hi = mid;
    }
    return 0;
}

/* Compare the keys of word `id` (apostrophes dropped if strip) with q[0..qn).
 * Returns <0, 0, >0 like strcmp; *starts is set when the word's keys begin with q. */
static int key_cmp(const op_model *m, uint16_t id, int strip, const char *q, int qn, int *starts) {
    const char *w;
    int wn = op_word(m, id, &w), i = 0;
    for (int j = 0;; j++) {
        int c = -1;
        while (i < wn) {
            char ch = w[i++];
            if (ch == '\'') { if (strip) continue; c = '#'; }
            else c = (ch >= 'a' && ch <= 'z') ? KEY_OF[ch - 'a'] : '?';
            break;
        }
        if (j == qn) { *starts = 1; return c < 0 ? 0 : 1; }
        *starts = 0;
        if (c < 0) return -1;
        if (c != q[j]) return c < q[j] ? -1 : 1;
    }
}

/* First position in an index whose key is >= q. */
static uint32_t lower_bound(const op_model *m, const uint16_t *ix, uint32_t n, int strip, const char *q, int qn) {
    uint32_t lo = 0, hi = n;
    int starts;
    while (lo < hi) {
        uint32_t mid = (lo + hi) / 2;
        if (key_cmp(m, ix[mid], strip, q, qn, &starts) < 0) lo = mid + 1; else hi = mid;
    }
    return lo;
}

/* Id of dictionary word w, or OP_NONE. */
static int find_word(const op_model *m, const char *w) {
    char k[32];
    int kn = 0, starts;
    for (; w[kn] && kn < 32; kn++) k[kn] = w[kn] == 39 ? '#' : KEY_OF[w[kn] - 'a'];
    for (uint32_t i = lower_bound(m, m->key_idx, m->n_words, 0, k, kn);
         i < m->n_words && key_cmp(m, m->key_idx[i], 0, k, kn, &starts) == 0; i++) {
        const char *t;
        int tn = op_word(m, m->key_idx[i], &t);
        if (tn == kn && memcmp(t, w, (size_t)kn) == 0) return m->key_idx[i];
    }
    return OP_NONE;
}

/* Does word `id` (apostrophes dropped if strip) agree with the exact letters in lit[0..n)? */
static int lit_match(const op_model *m, uint16_t id, int strip, const char *lit, int n) {
    const char *w;
    int wn = op_word(m, id, &w), t = 0;
    for (int i = 0; i < wn && t < n; i++) {
        if (strip && w[i] == '\'') continue;
        if (lit[t] && lit[t] != w[i]) return 0;
        t++;
    }
    for (; t < n; t++) if (lit[t]) return 0;    /* word shorter than the exact letters */
    return 1;
}

/* Are a and b the same once apostrophes are dropped? */
static int same_letters(const char *a, int an, const char *b, int bn) {
    int i = 0, j = 0;
    for (;;) {
        while (i < an && a[i] == '\'') i++;
        while (j < bn && b[j] == '\'') j++;
        if (i == an || j == bn) return i == an && j == bn;
        if (a[i++] != b[j++]) return 0;
    }
}

/* ---- tokenizer ---- */

static int is_letter_key(char ch) {     /* a press that can be part of a word's letters */
    return (ch >= '2' && ch <= '9') || (ch >= 'a' && ch <= 'z') || ch == '\'';
}
static int is_digit_lit(char ch) { return ch >= 'A' && ch <= 'J'; }
static char key_of(char ch) {
    if (ch >= 'a' && ch <= 'z') return KEY_OF[ch - 'a'];
    if (ch == '\'') return '#';
    return ch;
}
static char lit_of(char ch) {
    if ((ch >= 'a' && ch <= 'z') || ch == '\'') return ch;
    if (is_digit_lit(ch)) return (char)('0' + (ch - 'A'));
    return 0;
}

/* Digits end a word and run on as a number through more digits and through '#', '.' or ','
 * between digits; a '#' just before a number is '$'. Digits next to exactly spelled letters
 * stay in the word (call signs). A number's span of keys[] holds '$', '0'-'9', '.', ',' and
 * 's' for a separator format_number chooses. See decoder.js tokenize. */
static int tokenize(op_decoder *d, const char *keys) {
    int n = (int)strlen(keys), nk = 0;
    if (n > OP_MAX_KEYS) return OP_ERR_TOO_LONG;
    d->n_toks = 0;
    for (int i = 0; i < n; i++) {
        char ch = keys[i], nxt = i + 1 < n ? keys[i + 1] : 0;
        op_tok *last = d->n_toks ? &d->toks[d->n_toks - 1] : NULL;
        op_tok *t = &d->toks[d->n_toks];
        if (ch == '0') {
            t->type = TOK_SPACE; d->n_toks++;
        } else if ((ch == '#' || ch == '.' || ch == ',') && last && last->type == TOK_NUM &&
                   d->keys[nk - 1] >= '0' && d->keys[nk - 1] <= '9' && is_digit_lit(nxt)) {
            d->keys[nk] = ch == '#' ? 's' : ch; d->lits[nk++] = 0; last->len++;
        } else if (ch == '#') {
            if (last && last->type == TOK_WORD && is_letter_key(nxt)) {
                d->keys[nk] = '#'; d->lits[nk++] = 0; last->len++;
            } else {
                t->type = TOK_PUNCT; t->lit = 0; d->n_toks++;
            }
        } else if (ch == '.' || ch == ',' || ch == '?' || ch == '!') {
            t->type = TOK_PUNCT; t->lit = ch; d->n_toks++;
        } else if (is_digit_lit(ch)) {
            char dg = lit_of(ch);
            const op_tok *before = d->n_toks >= 2 ? &d->toks[d->n_toks - 2] : NULL;
            if (last && last->type == TOK_NUM) {
                d->keys[nk] = dg; d->lits[nk++] = 0; last->len++;
            } else if (last && last->type == TOK_WORD && d->lits[nk - 1]) {
                d->keys[nk] = ch; d->lits[nk++] = dg; last->len++;
            } else {
                if (last && last->type == TOK_PUNCT && !last->lit && keys[i - 1] == '#' &&
                    !(before && (before->type == TOK_WORD || before->type == TOK_NUM))) {
                    t = last;               /* the '#' becomes the number's '$' */
                    t->len = 1;
                    d->keys[nk] = '$'; d->lits[nk++] = 0;
                } else {
                    t->len = 0; d->n_toks++;
                }
                t->type = TOK_NUM; t->off = (uint16_t)(nk - t->len);
                d->keys[nk] = dg; d->lits[nk++] = 0; t->len++;
            }
        } else if (is_letter_key(ch)) {
            if (last && last->type == TOK_NUM && lit_of(ch)) {
                /* Digits followed by an exactly spelled letter are one word (2e0abc, 90's). */
                int pure = 1;
                for (int k = last->off; k < nk; k++) if (d->keys[k] < '0' || d->keys[k] > '9') pure = 0;
                if (pure) {
                    last->type = TOK_WORD;
                    for (int k = last->off; k < nk; k++) { d->lits[k] = d->keys[k]; d->keys[k] = (char)('A' + (d->keys[k] - '0')); }
                }
            }
            if (!(last && last->type == TOK_WORD)) {
                t->type = TOK_WORD; t->off = (uint16_t)nk; t->len = 0; d->n_toks++;
                last = t;
            }
            d->keys[nk] = key_of(ch); d->lits[nk++] = lit_of(ch); last->len++;
        }
    }
    return OP_OK;
}

/* Write a number's text (see decoder.js formatNumber): each 's' is ',' when the groups read
 * as thousands, else '.'; with `time`, H s MM is H:MM. Returns its length, or OP_ERR_SPACE. */
static int format_number(const char *k, int kn, int time, char *out, int cap) {
    int commas = 1, group = 0, glen = 0, n = 0;
    if (time && (kn == 4 || kn == 5) && k[kn - 3] == 's') {
        int ok = 1, h = 0;
        for (int i = 0; i < kn; i++) if (i != kn - 3 && (k[i] < '0' || k[i] > '9')) ok = 0;
        for (int i = 0; ok && i < kn - 3; i++) h = h * 10 + (k[i] - '0');
        if (ok && h <= 24 && (k[kn - 2] - '0') * 10 + (k[kn - 1] - '0') <= 59) time = 2;
    }
    for (int i = 0; i < kn; i++) {
        char c = k[i];
        if (c >= '0' && c <= '9') glen++;
        else if (c != '$') {
            if (group == 0 ? glen > 3 : glen != 3) commas = 0;
            group++; glen = 0;
        }
    }
    if (group == 0 && glen > 3) commas = 0;
    for (int i = 0; i < kn; i++) {
        char c = k[i];
        if (c == 's' && time == 2) c = ':';
        else if (c == 's') {
            int next = 0;
            for (int j = i + 1; j < kn && k[j] >= '0' && k[j] <= '9'; j++) next++;
            c = commas && next == 3 ? ',' : '.';
        }
        if (n + 1 >= cap) return OP_ERR_SPACE;
        out[n++] = c;
    }
    return n;
}

/* ---- candidates ---- */

typedef struct { uint16_t id; uint8_t kind; int16_t pen; } cand;

static int punct_index(const op_model *m, char ch) {
    for (int i = 0; i < m->n_punct; i++) if (m->punct[i] == ch) return i;
    return 0;
}

static int slot_cands(const op_decoder *d, const op_model *m, const op_tok *t, int is_last, cand *out) {
    if (t->type == TOK_NUM) { out[0] = (cand){ OP_NONE, OP_NUMBER, 0 }; return 1; }
    if (t->type == TOK_PUNCT) {
        if (t->lit) { out[0] = (cand){ (uint16_t)(m->n_words + punct_index(m, t->lit)), OP_PUNCT, 0 }; return 1; }
        for (int i = 0; i < m->n_punct; i++) out[i] = (cand){ (uint16_t)(m->n_words + i), OP_PUNCT, 0 };
        return m->n_punct;
    }
    const char *k = d->keys + t->off, *lit = d->lits + t->off;
    int kn = t->len, has_lit = 0, all_lit = 1, has_hash = 0, n = 0;
    for (int i = 0; i < kn; i++) {
        if (lit[i]) has_lit = 1; else all_lit = 0;
        if (k[i] == '#') has_hash = 1;
    }
    /* Exact matches from both indexes, merged into id (frequency) order. A contraction typed
     * without its apostrophe ("im" for I'm) matches through stripIdx with a small penalty. */
    int starts;
    uint32_t a = lower_bound(m, m->key_idx, m->n_words, 0, k, kn), ae = a;
    uint32_t b = lower_bound(m, m->strip_idx, m->n_strip, 1, k, kn), be = b;
    while (ae < m->n_words && key_cmp(m, m->key_idx[ae], 0, k, kn, &starts) == 0) ae++;
    while (be < m->n_strip && key_cmp(m, m->strip_idx[be], 1, k, kn, &starts) == 0) be++;
    while ((a < ae || b < be) && n < OP_MAX_EXACT) {
        int from_strip = a >= ae || (b < be && m->strip_idx[b] < m->key_idx[a]);
        uint16_t id = from_strip ? m->strip_idx[b++] : m->key_idx[a++];
        if (has_lit && !lit_match(m, id, !has_hash, lit, kn)) continue;
        out[n++] = (cand){ id, OP_WORD, from_strip ? m->param[OP_P_APOSTROPHE] : 0 };
    }
    int n_exact = n;
    if (is_last && !all_lit) {
        /* While still typing, also offer the most frequent completions. */
        uint16_t best[OP_MAX_COMPLETIONS];
        int nb = 0;
        for (int strip = 0; strip < 2; strip++) {
            const uint16_t *ix = strip ? m->strip_idx : m->key_idx;
            uint32_t ixn = strip ? m->n_strip : m->n_words;
            for (uint32_t i = lower_bound(m, ix, ixn, strip, k, kn); i < ixn; i++) {
                key_cmp(m, ix[i], strip, k, kn, &starts);
                if (!starts) break;
                uint16_t id = ix[i];
                if (has_lit && !lit_match(m, id, strip, lit, kn)) continue;
                int dup = 0;
                for (int j = 0; j < nb; j++) if (best[j] == id) dup = 1;
                if (dup) continue;
                if (nb < OP_MAX_COMPLETIONS) best[nb++] = id;
                else if (id < best[nb - 1]) best[nb - 1] = id;
                else continue;
                for (int j = nb - 1; j > 0 && best[j] < best[j - 1]; j--) {
                    uint16_t x = best[j]; best[j] = best[j - 1]; best[j - 1] = x;
                }
            }
        }
        for (int j = 0; j < nb; j++) {
            int seen = 0;
            for (int e = 0; e < n_exact; e++) if (out[e].id == best[j]) seen = 1;
            if (!seen) out[n++] = (cand){ best[j], OP_PARTIAL, m->param[OP_P_COMPLETION] };
        }
    }
    if (all_lit) {
        /* Spelled out exactly: keep only words spelled exactly that way, else the text as typed. */
        int kept = 0;
        for (int e = 0; e < n; e++) {
            const char *w;
            int wn = op_word(m, out[e].id, &w);
            if (wn == kn && same_letters(w, wn, lit, kn)) out[kept++] = out[e];
        }
        if (kept) return kept;
        out[0] = (cand){ OP_NONE, OP_LITERAL, 0 };
        return 1;
    }
    if (!n) out[n++] = (cand){ OP_NONE, OP_UNKNOWN, 0 };
    return n;
}

/* ---- beam search ---- */

static int cmp_entry(const void *x, const void *y) {
    const op_entry *a = (const op_entry *)x, *b = (const op_entry *)y;
    if (a->score != b->score) return a->score > b->score ? -1 : 1;
    return (int)a->seq - (int)b->seq;   /* ties keep generation order, like decoder.js's stable sort */
}

/* Sentence/clause opener state: 0 none yet, 1 question word, 2 anything else. */
static uint8_t q_state(const op_model *m, uint16_t id) {
    return id != OP_NONE && is_q_start(m, id) ? 1 : 2;
}

int op_decode(op_decoder *d, const op_model *m, const char *keys, int beam,
              const op_start *start, const op_lock *locks, int n_locks) {
    if (!d || !m || !keys || beam < 1 || beam > OP_MAX_BEAM) return OP_ERR_ARG;
    int r = tokenize(d, keys);
    if (r) return r;
    d->n_slots = 0;
    for (int i = 0; i < d->n_toks; i++) {
        if (d->toks[i].type == TOK_SPACE) continue;
        if (d->n_slots == OP_MAX_SLOTS) return OP_ERR_TOO_LONG;
        d->slot_tok[d->n_slots++] = (uint16_t)i;
    }
    int last_is_word = d->n_toks && d->toks[d->n_toks - 1].type == TOK_WORD;
    const int16_t *P = m->param;

    int32_t score[OP_MAX_BEAM];
    uint16_t prev[OP_MAX_BEAM];
    uint8_t first[OP_MAX_BEAM], cf[OP_MAX_BEAM];
    int nb = 1;
    score[0] = 0;
    prev[0] = start ? start->prev : m->bos;
    first[0] = cf[0] = 0;

    cand c[OP_MAX_CANDS];
    for (int j = 0; j < d->n_slots; j++) {
        const op_tok *t = &d->toks[d->slot_tok[j]];
        int is_final = j == d->n_slots - 1;
        int nc = slot_cands(d, m, t, is_final && last_is_word, c);
        for (int l = 0; l < n_locks; l++) {
            if (locks[l].slot != j) continue;
            int hit = 0;
            for (int i = 0; i < nc; i++) if (c[i].id == locks[l].id) c[hit++] = c[i];
            if (hit) nc = hit;
        }
        int ne = 0;
        for (int h = 0; h < nb; h++) {
            for (int ci = 0; ci < nc; ci++) {
                uint16_t id = c[ci].id, p;
                uint8_t f = first[h], g = cf[h];
                int32_t step;
                if (id == OP_NONE) {
                    step = c[ci].kind == OP_NUMBER ? 0 : c[ci].kind == OP_LITERAL ? P[OP_P_LITERAL] : P[OP_P_UNKNOWN];
                    p = c[ci].kind == OP_NUMBER ? AFTER_NUMBER : OP_NONE;
                } else {
                    step = lp(m, prev[h], id) + c[ci].pen;
                    p = id;
                }
                if (id != OP_NONE && id >= m->n_words) {
                    /* Punctuation: a word-pair model can't see how the sentence began,
                     * so use the sentence's first word to judge question vs statement. */
                    int q = f == 1 || g == 1;
                    char ch = m->punct[id - m->n_words];
                    if (ch == '?') step += q ? P[OP_P_QQ] : P[OP_P_QN];
                    else if (ch == '.') step += P[OP_P_DB] + (q ? P[OP_P_DQ] : 0);
                    else if (ch == ',') step += P[OP_P_CB] + (is_final ? P[OP_P_CF] : 0);
                    else if (ch == '!') step += P[OP_P_EB];
                    if (ch != ',') { p = m->bos; f = 0; }
                    g = 0;
                } else {
                    if (!f) f = q_state(m, id);
                    if (!g) g = q_state(m, id);
                }
                op_entry *e = &d->ent[ne];
                e->score = score[h] + step;
                e->seq = (uint16_t)ne;
                e->prev = p;
                e->id = id;
                e->parent = (uint8_t)h;
                e->kind = c[ci].kind;
                e->first = f;
                e->cf = g;
                ne++;
            }
        }
        qsort(d->ent, (size_t)ne, sizeof(op_entry), cmp_entry);
        /* Keep the best hypothesis per state (previous token + opener states): the rest
         * would score every future slot the same way. */
        int kept[OP_MAX_BEAM], nk = 0;
        for (int i = 0; i < ne && nk < beam; i++) {
            const op_entry *e = &d->ent[i];
            int dup = 0;
            for (int k = 0; k < nk && !dup; k++) {
                const op_entry *o = &d->ent[kept[k]];
                dup = o->prev == e->prev && o->first == e->first && o->cf == e->cf;
            }
            if (!dup) kept[nk++] = i;
        }
        for (int k = 0; k < nk; k++) {
            const op_entry *e = &d->ent[kept[k]];
            score[k] = e->score;
            prev[k] = e->prev;
            first[k] = e->first;
            cf[k] = e->cf;
            d->bp[j][k].id = e->id;
            d->bp[j][k].parent = e->parent;
            d->bp[j][k].kind = e->kind;
        }
        nb = nk;
    }
    d->score = score[0];
    for (int j = d->n_slots - 1, h = 0; j >= 0; j--) {
        d->choice[j].id = d->bp[j][h].id;
        d->choice[j].kind = d->bp[j][h].kind;
        h = d->bp[j][h].parent;
    }
    return OP_OK;
}

/* ---- rendering ---- */

static int display(const op_model *m, uint16_t id, const char **text) {
    uint32_t lo = 0, hi = m->n_disp;
    while (lo < hi) {
        uint32_t mid = (lo + hi) / 2;
        if (m->disp_id[mid] == id) {
            *text = m->disp_text + m->disp_off[mid];
            return (int)(m->disp_off[mid + 1] - m->disp_off[mid]);
        }
        if (m->disp_id[mid] < id) lo = mid + 1; else hi = mid;
    }
    return -1;
}

static int is_one_of(const op_model *m, op_choice ch, const char *const *list, int n) {
    if (ch.kind != OP_WORD || ch.id >= m->n_words) return 0;
    const char *w;
    int wn = op_word(m, ch.id, &w);
    for (int i = 0; i < n; i++) if ((int)strlen(list[i]) == wn && memcmp(list[i], w, (size_t)wn) == 0) return 1;
    return 0;
}

int op_render(const op_decoder *d, const op_model *m, const op_start *start, char *out, int cap) {
    int n = 0, cap_next = start ? start->cap : 1;
    op_choice before = { OP_NONE, OP_UNKNOWN };     /* choice of the last non-space token */
    for (int i = 0, j = 0; i < d->n_toks; i++) {
        const op_tok *t = &d->toks[i];
        if (t->type == TOK_SPACE) {
            if (n + 1 >= cap) return OP_ERR_SPACE;
            out[n++] = ' ';
            continue;
        }
        op_choice ch = d->choice[j++], prior = before;
        before = t->type == TOK_WORD ? ch : (op_choice){ OP_NONE, OP_UNKNOWN };
        if (t->type == TOK_PUNCT) {
            if (n + 1 >= cap) return OP_ERR_SPACE;
            out[n++] = m->punct[ch.id - m->n_words];
            cap_next = out[n - 1] != ',';
            continue;
        }
        if (t->type == TOK_NUM) {
            /* A time when the words around it say so: "at 5:30", "5:30 pm". */
            int time = is_one_of(m, prior, TIME_BEFORE, (int)(sizeof TIME_BEFORE / sizeof *TIME_BEFORE));
            int k = i + 1;
            while (k < d->n_toks && d->toks[k].type == TOK_SPACE) k++;
            if (k < d->n_toks && d->toks[k].type == TOK_WORD) time |= is_one_of(m, d->choice[j], TIME_AFTER, 2);
            int len = format_number(d->keys + t->off, t->len, time, out + n, cap - n);
            if (len < 0) return len;
            n += len;
            cap_next = 0;
            continue;
        }
        int s = n, len;
        if (ch.kind == OP_WORD || ch.kind == OP_PARTIAL) {
            const char *w, *shown, *src;
            int wn = op_word(m, ch.id, &w), dn = display(m, ch.id, &shown);
            len = wn;
            if (ch.kind == OP_PARTIAL && len > t->len) len = t->len;   /* only what's typed so far */
            if (dn >= 0) {
                if (ch.kind == OP_WORD) len = dn;
                else if (len > dn) len = dn;
                src = shown;
            } else {
                src = w;
            }
            if (n + len >= cap) return OP_ERR_SPACE;
            memcpy(out + n, src, (size_t)len);
            n += len;
        } else {
            /* Typed exactly, or no dictionary word fits: the exact letters, else each key's first letter. */
            if (n + t->len >= cap) return OP_ERR_SPACE;
            for (int k = 0; k < t->len; k++) {
                char l = d->lits[t->off + k], key = d->keys[t->off + k];
                if (!l) l = key == '#' ? '\'' : (key >= '2' && key <= '9') ? FIRST_LETTER[key - '2'] : '?';
                out[n++] = l;
            }
        }
        len = n - s;
        if (len && out[s] == 'i' && (len == 1 || out[s + 1] == '\'')) out[s] = 'I';
        /* Capitalize a sentence start, but keep brand styling like iPhone / eBay. */
        int brand = len >= 2 && out[s] >= 'a' && out[s] <= 'z' && out[s + 1] >= 'A' && out[s + 1] <= 'Z';
        if (cap_next && !brand && len && out[s] >= 'a' && out[s] <= 'z') out[s] = (char)(out[s] - 'a' + 'A');
        cap_next = 0;
    }
    if (n >= cap) return OP_ERR_SPACE;
    out[n] = 0;
    return n;
}
