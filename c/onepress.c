/* OnePress decoder. Mirrors web/decoder.js; see onepress.h. */
#include "onepress.h"

#include <stdlib.h>
#include <string.h>

enum { TOK_WORD, TOK_PUNCT, TOK_SPACE, TOK_NUM };
enum { N_SECTIONS = 15, N_ALL_SECTIONS = 27 };     /* sections 15..26 are optional */

static const char KEY_OF[26] = "22233344455566677778889999";
static const char FIRST_LETTER[8] = "adgjmptw";     /* first letter of keys 2-9 */
#define AFTER_NUMBER 0xFFFE     /* beam state after a number (the model has no number token) */
#define AFTER_DECIMAL 0xFFFC    /* after a number that could have been a time but was read as 5.30 */
#define TIME_BONUS 8            /* nats for "am"/"pm" right after a number or a time */
/* A number that reads as H:MM has a decimal and a time candidate; see decoder.js TIME_PREV. */
#define TIME_PREV 2
#define TIME_ALONE 2
#define TIME_LITERAL 14
static const char *const TIME_BEFORE[OP_TIME_BEFORE] = { "at", "by", "until", "til", "till", "around", "before", "after", "from", "since" };
static const char *const TIME_AFTER[] = { "am", "pm" };

#define USER_ANY 0xFFFD         /* op_user_pair prev for a token's own count */
/* Learning bonus by count (capped at 15), as decoder.js USER_UNI / USER_PAIR. */
static const int16_t USER_UNI[16] = { 0, 710, 1125, 1420, 1648, 1835, 1993, 2129, 2250, 2358, 2455, 2545, 2627, 2702, 2773, 2839 };
static const int16_t USER_PAIR[16] = { 0, 532, 844, 1065, 1236, 1376, 1494, 1597, 1687, 1768, 1842, 1908, 1970, 2027, 2080, 2129 };
#define USER_WORD_BASE (-2560)  /* log P of a learned word before its bonuses (-10 nats) */

static int find_word(const op_model *m, const char *w);

/* ---- model ---- */

static uint16_t rd16(const uint8_t *p) { return (uint16_t)(p[0] | p[1] << 8); }
static uint32_t rd32(const uint8_t *p) { return (uint32_t)p[0] | (uint32_t)p[1] << 8 | (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24; }

int op_model_open(op_model *m, const void *data, size_t size) {
    const uint8_t *b = (const uint8_t *)data;
    const void *sec[N_ALL_SECTIONS];
    uint32_t len[N_ALL_SECTIONS];
    static const uint32_t one_zero = 0;      /* an empty triStart / altOff */
    if (!m || !b || ((uintptr_t)b & 3) || size < 16 || memcmp(b, "KPD2", 4) != 0) return OP_ERR_MODEL;
    if (rd16(b + 4) != 1 || rd16(b + 14) < N_SECTIONS || size < 16 + 8u * N_SECTIONS) return OP_ERR_MODEL;
    m->scale = rd16(b + 6);
    m->n_words = rd16(b + 8);
    m->n_punct = rd16(b + 10);
    m->bos = rd16(b + 12);
    /* Optional sections: older files stop after the 15th; files with three-word context have
     * at least 25 (capNextKey, the 26th, came last). Newer sections beyond these are ignored. */
    int n_sec = rd16(b + 14) < N_ALL_SECTIONS ? rd16(b + 14) : N_ALL_SECTIONS;
    if (n_sec < 25) n_sec = N_SECTIONS;
    if (size < 16 + 8u * n_sec) return OP_ERR_MODEL;
    for (int i = n_sec; i < N_ALL_SECTIONS; i++) { sec[i] = &one_zero; len[i] = 0; }
    for (int i = 0; i < n_sec; i++) {
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
    m->q_skip = (const uint16_t *)sec[15];
    m->n_skip = len[15] / 2;
    m->tri_key = (const uint32_t *)sec[16];
    m->n_tri = len[16] / 4;
    m->tri_start = (const uint32_t *)sec[17];
    m->tri_bow = (const int16_t *)sec[18];
    m->tri_next = (const uint16_t *)sec[19];
    m->tri_lp = (const int16_t *)sec[20];
    m->cap_key = (const uint32_t *)sec[21];
    m->n_cap = len[21] / 4;
    m->alt_id = (const uint16_t *)sec[22];
    m->n_alt = len[22] / 2;
    m->alt_off = (const uint32_t *)sec[23];
    m->alt_text = (const char *)sec[24];
    m->cap_next = (const uint32_t *)sec[25];
    m->n_cap_next = len[25] / 4;
    m->cap_keep = (const uint32_t *)sec[26];
    m->n_cap_keep = len[26] / 4;
    if (m->n_tri >= 0xFFFF || (n_sec > N_SECTIONS && (len[17] != 4u * (m->n_tri + 1) || len[18] != 2u * m->n_tri ||
        len[20] != len[19] || len[23] != 4u * (m->n_alt + 1))))
        return OP_ERR_MODEL;
    for (int i = 0; i < 2; i++) m->time_id[i] = (uint16_t)find_word(m, TIME_AFTER[i]);
    for (int i = 0; i < OP_TIME_BEFORE; i++) m->time_before[i] = (uint16_t)find_word(m, TIME_BEFORE[i]);
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
    if (prev > m->bos) return m->uni[cur];      /* unknown, or a learned word */
    uint32_t lo = m->row_start[prev], hi = m->row_start[prev + 1];
    while (lo < hi) {
        uint32_t mid = (lo + hi) / 2;
        uint16_t x = m->next[mid];
        if (x == cur) return m->lp[mid];
        if (x < cur) lo = mid + 1; else hi = mid;
    }
    return m->bow[prev] + m->uni[cur];
}

static int in_u16(const uint16_t *a, uint32_t n, uint16_t id) {
    uint32_t lo = 0, hi = n;
    while (lo < hi) {
        uint32_t mid = (lo + hi) / 2;
        if (a[mid] == id) return 1;
        if (a[mid] < id) lo = mid + 1; else hi = mid;
    }
    return 0;
}
static int is_q_start(const op_model *m, uint16_t id) { return in_u16(m->q_start, m->n_q, id); }

/* Sentence/clause opener state: 0 none yet, 1 question word, 2 anything else. */
static uint8_t q_state(const op_model *m, uint16_t id) {
    return id != OP_NONE && is_q_start(m, id) ? 1 : 2;
}

/* Index of key k in a sorted u32 array, or -1. */
static int32_t find_u32(const uint32_t *a, uint32_t n, uint32_t k) {
    uint32_t lo = 0, hi = n;
    while (lo < hi) {
        uint32_t mid = (lo + hi) / 2;
        if (a[mid] < k) lo = mid + 1; else hi = mid;
    }
    return lo < n && a[lo] == k ? (int32_t)lo : -1;
}

/* Three-word context (p2, p1): its index in tri_key, or OP_NONE (also for numbers, unknown and
 * learned words, which no context includes). See decoder.js triFind. */
static uint16_t tri_find(const op_model *m, uint16_t p2, uint16_t p1) {
    if (p2 > m->bos || p1 > m->bos) return OP_NONE;
    int32_t i = find_u32(m->tri_key, m->n_tri, (uint32_t)p2 << 16 | p1);
    return i < 0 ? OP_NONE : (uint16_t)i;
}
/* log P(cur | context t, prev): the triple if stored, else the context's backoff + the pair. */
static int32_t lp3(const op_model *m, uint16_t t, uint16_t prev, uint16_t cur) {
    if (t == OP_NONE) return lp(m, prev, cur);
    uint32_t lo = m->tri_start[t], hi = m->tri_start[t + 1];
    while (lo < hi) {
        uint32_t mid = (lo + hi) / 2;
        uint16_t x = m->tri_next[mid];
        if (x == cur) return m->tri_lp[mid];
        if (x < cur) lo = mid + 1; else hi = mid;
    }
    return m->tri_bow[t] + lp(m, prev, cur);
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

/* Does word w (apostrophes dropped if strip) agree with the exact letters in lit[0..n)? */
static int lit_match_text(const char *w, int wn, int strip, const char *lit, int n) {
    int t = 0;
    for (int i = 0; i < wn && t < n; i++) {
        if (strip && w[i] == '\'') continue;
        if (lit[t] && lit[t] != w[i]) return 0;
        t++;
    }
    for (; t < n; t++) if (lit[t]) return 0;    /* word shorter than the exact letters */
    return 1;
}
static int lit_match(const op_model *m, uint16_t id, int strip, const char *lit, int n) {
    const char *w;
    int wn = op_word(m, id, &w);
    return lit_match_text(w, wn, strip, lit, n);
}

/* ---- learned words ---- */

/* Text of a dictionary or learned word. */
static int tok_text(const op_model *m, const op_user *u, uint16_t id, const char **text) {
    if (id > m->bos) {
        *text = u->word[id - m->bos - 1];
        return (int)strlen(*text);
    }
    return op_word(m, id, text);
}

/* Index of pair (prev, cur), or -(insertion point) - 1. */
static int user_find(const op_user *u, uint16_t prev, uint16_t cur) {
    uint32_t k = (uint32_t)prev << 16 | cur;
    int lo = 0, hi = u->n_pairs;
    while (lo < hi) {
        int mid = (lo + hi) / 2;
        uint32_t x = (uint32_t)u->pair[mid].prev << 16 | u->pair[mid].cur;
        if (x == k) return mid;
        if (x < k) lo = mid + 1; else hi = mid;
    }
    return -lo - 1;
}
static int user_count(const op_user *u, uint16_t prev, uint16_t cur) {
    int i = user_find(u, prev, cur);
    return i >= 0 ? u->pair[i].count : 0;
}

static int32_t token_score(const op_model *m, const op_user *u, uint16_t prev, uint16_t id, uint16_t tri) {
    int32_t s = id > m->bos ? USER_WORD_BASE : lp3(m, tri, prev, id);
    if (u) {
        int c = user_count(u, USER_ANY, id);
        s += USER_UNI[c < 15 ? c : 15];
        if (prev != OP_NONE && prev != AFTER_NUMBER && prev != AFTER_DECIMAL) {
            c = user_count(u, prev, id);
            s += USER_PAIR[c < 15 ? c : 15];
        }
    }
    return s;
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
static int tokenize(op_decoder *d, const char *keys, const char *hint) {
    int n = (int)strlen(keys), nk = 0, hn = hint ? (int)strlen(hint) : 0;
    if (n > OP_MAX_KEYS) return OP_ERR_TOO_LONG;
    d->n_toks = 0;
    memset(d->hints, 0, sizeof d->hints);
    for (int i = 0; i < n; i++) {
        char ch = keys[i], nxt = i + 1 < n ? keys[i + 1] : 0;
        op_tok *last = d->n_toks ? &d->toks[d->n_toks - 1] : NULL;
        op_tok *t = &d->toks[d->n_toks];
        if (ch == '0') {
            t->type = TOK_SPACE; d->n_toks++;
        } else if ((ch == '#' || ch == '.' || ch == ',' || ch == ':') && last && last->type == TOK_NUM &&
                   d->keys[nk - 1] >= '0' && d->keys[nk - 1] <= '9' && is_digit_lit(nxt)) {
            d->keys[nk] = ch == '#' ? 's' : ch; d->lits[nk++] = 0; last->len++;
        } else if (ch == '#') {
            if (last && last->type == TOK_WORD && is_letter_key(nxt)) {
                d->keys[nk] = '#'; d->lits[nk++] = 0; last->len++;
            } else {
                t->type = TOK_PUNCT; t->lit = 0; d->n_toks++;
            }
        } else if (ch == '.' || ch == ',' || ch == '?' || ch == '!' || ch == ':') {
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
            if (i < hn && hint[i] >= 'a' && hint[i] <= 'z') d->hints[nk] = hint[i];
            d->keys[nk] = key_of(ch); d->lits[nk++] = lit_of(ch); last->len++;
        }
    }
    return OP_OK;
}

/* Write a number's text (see decoder.js formatNumber): each 's' is ',' when the groups read
 * as thousands, else '.'; with `time`, H s MM is H:MM. Returns its length, or OP_ERR_SPACE. */
static int format_number(const char *k, int kn, int time, char *out, int cap) {
    int commas = 1, group = 0, glen = 0, n = 0;
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
        if (time && (c == 's' || c == '.')) c = ':';
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

/* Can number keys k[0..kn) be a time H:MM (H <= 24, MM <= 59)? The separator ('s', '.' or
 * ':'), else 0. See decoder.js timeKind. */
static char time_kind(const char *k, int kn) {
    if (kn != 4 && kn != 5) return 0;
    char sep = k[kn - 3];
    if (sep != 's' && sep != '.' && sep != ':') return 0;
    int h = 0;
    for (int i = 0; i < kn; i++) {
        if (i == kn - 3) continue;
        if (k[i] < '0' || k[i] > '9') return 0;
        if (i < kn - 3) h = h * 10 + (k[i] - '0');
    }
    return h <= 24 && (k[kn - 2] - '0') * 10 + (k[kn - 1] - '0') <= 59 ? sep : 0;
}

/* ---- candidates ---- */

typedef struct { uint16_t id; uint8_t kind; int16_t pen; } cand;

/* Learned words may hold digits (call signs). As decoder.js userKeys / userTyped: a learned
 * word's digit 2-9 is its own key and 0/1 the held digit; a typed held digit 2-9 compares as
 * that key, and the exact characters (lit) must still agree. */
static char user_key(char c) {
    if (c == 39) return '#';
    if (c >= '0' && c <= '9') return c >= '2' ? c : (char)('A' + (c - '0'));
    return KEY_OF[c - 'a'];
}
static void user_typed(const char *k, int kn, char *out) {
    for (int i = 0; i < kn; i++) out[i] = k[i] >= 'C' && k[i] <= 'J' ? (char)('0' + (k[i] - 'A')) : k[i];
}

/* How learned word t fits typed keys k (through user_typed): 1 whole, 2 whole without its
 * apostrophes, 3 its beginning (only if `partial`), else 0. See decoder.js userMatch. */
static int user_match(const char *t, const char *k, const char *lit, int kn, int partial) {
    if (!t[0]) return 0;
    char full[OP_USER_WORD_LEN], strip[OP_USER_WORD_LEN];
    int fn = 0, sn = 0;
    for (; t[fn]; fn++) {
        full[fn] = user_key(t[fn]);
        if (t[fn] != 39) strip[sn++] = full[fn];
    }
    int full_eq = fn == kn && memcmp(full, k, (size_t)kn) == 0;
    int strip_eq = sn != fn && sn == kn && memcmp(strip, k, (size_t)kn) == 0;
    if (full_eq || strip_eq) return lit_match_text(t, fn, !full_eq, lit, kn) ? (full_eq ? 1 : 2) : 0;
    if (!partial) return 0;
    int fs = fn >= kn && memcmp(full, k, (size_t)kn) == 0;
    int ss = !fs && sn >= kn && memcmp(strip, k, (size_t)kn) == 0;
    return (fs || ss) && lit_match_text(t, fn, ss, lit, kn) ? 3 : 0;
}

/* Learned words matching a word token: exact ones into out (up to OP_MAX_USER_CANDS), and
 * with `partial` completions into part. Mirrors the user loop in decoder.js slotCandidates. */
static void user_cands(const op_model *m, const op_user *u, const char *k, const char *lit, int kn,
                       int partial, cand *out, int *n_out, cand *part, int *n_part) {
    char typed[OP_USER_WORD_LEN];
    if (kn > OP_USER_WORD_LEN) return;      /* longer than any learned word */
    user_typed(k, kn, typed);
    for (int w = 0; w < u->n_words; w++) {
        uint16_t id = (uint16_t)(m->bos + 1 + w);
        int f = user_match(u->word[w], typed, lit, kn, partial);
        if ((f == 1 || f == 2) && *n_out < OP_MAX_USER_CANDS)
            out[(*n_out)++] = (cand){ id, OP_WORD, (int16_t)(f == 1 ? 0 : m->param[OP_P_APOSTROPHE]) };
        else if (f == 3 && *n_part < OP_MAX_USER_CANDS)
            part[(*n_part)++] = (cand){ id, OP_PARTIAL, m->param[OP_P_COMPLETION] };
    }
}

/* A run of word and number tokens with nothing between them (53, held 7, 272) that spells a
 * learned word is that one word; the last run may be its beginning. See decoder.js joinLearned. */
static int pure_number(const op_decoder *d, const op_tok *t) {
    if (t->type != TOK_NUM) return 0;
    for (int k = t->off; k < t->off + t->len; k++) if (d->keys[k] < '0' || d->keys[k] > '9') return 0;
    return 1;
}
static void join_learned(op_decoder *d) {
    const op_user *u = d->user;
    int any = 0;
    for (int w = 0; w < u->n_words && !any; w++) any = strpbrk(u->word[w], "0123456789") != NULL;
    if (!any) return;
    int out = 0;
    for (int i = 0; i < d->n_toks;) {
        int j = i, len = 0;
        while (j < d->n_toks && (d->toks[j].type == TOK_WORD || pure_number(d, &d->toks[j]))) len += d->toks[j++].len;
        if (j - i > 1 && len <= OP_USER_WORD_LEN) {
            int off = d->toks[i].off, match = 0;
            char k[OP_USER_WORD_LEN], lit[OP_USER_WORD_LEN];
            for (int r = i; r < j; r++) {           /* spans are contiguous: nothing between them */
                const op_tok *t = &d->toks[r];
                for (int q = t->off; q < t->off + t->len; q++) {
                    char c = d->keys[q];
                    k[q - off] = t->type == TOK_NUM ? (char)('A' + (c - '0')) : c;
                    lit[q - off] = t->type == TOK_NUM ? c : d->lits[q];
                }
            }
            char typed[OP_USER_WORD_LEN];
            user_typed(k, len, typed);
            for (int w = 0; w < u->n_words && !match; w++) match = user_match(u->word[w], typed, lit, len, j == d->n_toks);
            if (match) {
                memcpy(d->keys + off, k, (size_t)len);
                memcpy(d->lits + off, lit, (size_t)len);
                d->toks[out].type = TOK_WORD; d->toks[out].lit = 0;
                d->toks[out].off = (uint16_t)off; d->toks[out].len = (uint16_t)len;
                out++; i = j;
                continue;
            }
        }
        if (j == i) j = i + 1;
        while (i < j) d->toks[out++] = d->toks[i++];
    }
    d->n_toks = (uint16_t)out;
}

static int punct_index(const op_model *m, char ch) {
    for (int i = 0; i < m->n_punct; i++) if (m->punct[i] == ch) return i;
    return 0;
}

static int slot_cands(const op_decoder *d, const op_model *m, const op_tok *t, int is_last, cand *out) {
    const op_user *u = d->user;
    if (t->type == TOK_NUM) {
        char tk = time_kind(d->keys + t->off, t->len);
        if (tk == ':') { out[0] = (cand){ OP_TIME_ID, OP_TIME, 0 }; return 1; }
        out[0] = (cand){ OP_NONE, OP_NUMBER, 0 };
        if (!tk) return 1;
        out[1] = (cand){ OP_TIME_ID, OP_TIME, 0 };
        return 2;
    }
    if (t->type == TOK_PUNCT) {
        if (t->lit && !memchr(m->punct, t->lit, m->n_punct)) { out[0] = (cand){ OP_NONE, OP_LITERAL, 0 }; return 1; }   /* ':' */
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
    cand upart[OP_MAX_USER_CANDS];
    int n_upart = 0;
    if (u) {
        int n_uexact = 0;
        user_cands(m, u, k, lit, kn, is_last && !all_lit, out + n, &n_uexact, upart, &n_upart);
        n += n_uexact;
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
        for (int j = 0; j < n_upart; j++) out[n++] = upart[j];
    }
    if (all_lit) {
        /* Spelled out exactly: keep only words spelled exactly that way, else the text as typed. */
        int kept = 0;
        for (int e = 0; e < n; e++) {
            const char *w;
            int wn = tok_text(m, u, out[e].id, &w);
            if (wn == kn && same_letters(w, wn, lit, kn)) out[kept++] = out[e];
        }
        if (kept) return kept;
        out[0] = (cand){ OP_NONE, OP_LITERAL, 0 };
        return 1;
    }
    if (!n) out[n++] = (cand){ OP_NONE, OP_UNKNOWN, 0 };
    return n;
}

/* ---- context ---- */

#define RECENT_BONUS 3          /* nats for a word used in the text before (see decoder.js) */
#define RECENT_MAX_UNI (-9)     /* ... unless it's this common (log P above -9 nats) */

/* Id of a word from the text before: the dictionary, then learned words, else OP_NONE. */
static uint16_t context_word(const op_model *m, const op_user *u, const char *w, int wn) {
    int letters = 1;
    for (int i = 0; i < wn; i++) if (!((w[i] >= 'a' && w[i] <= 'z') || w[i] == 39)) letters = 0;
    if (letters && wn < 32) {
        char buf[32];
        memcpy(buf, w, (size_t)wn);
        buf[wn] = 0;
        int id = find_word(m, buf);
        if (id != OP_NONE) return (uint16_t)id;
    }
    for (int k = 0; u && k < u->n_words; k++) {
        const char *t = u->word[k];
        int i = 0;
        while (i < wn && t[i] && (t[i] >= 'A' && t[i] <= 'Z' ? t[i] + 32 : t[i]) == w[i]) i++;
        if (i == wn && !t[i]) return (uint16_t)(m->bos + 1 + k);
    }
    return OP_NONE;
}

/* The context a composition starts in, from start->before (decoder.js context): the last words,
 * whether to capitalize, the opener of an unfinished sentence and the recently used words. */
static void context(op_decoder *d, const op_model *m, const op_start *start,
                    uint16_t *prev2, uint8_t *first, uint8_t *cf) {
    *prev2 = OP_NONE;
    *first = *cf = 0;
    d->ctx_prev = start ? start->prev : m->bos;
    d->ctx_cap = start ? start->cap : 1;
    d->n_recent = 0;
    if (!start || !start->before) return;
    const unsigned char *b = (const unsigned char *)start->before;
    uint16_t p2 = OP_NONE, p1 = m->bos, recent[OP_RECENT_WORDS];
    int n_recent = 0, cap = 1;
    uint8_t f = 0, g = 0;
    char w[OP_USER_WORD_LEN + 9];
    while (*b) {
        unsigned char c = *b;
        int wn = 0, long_word = 0;
        /* a run of letters, digits and apostrophes (curly ones included), lowercased */
        for (;;) {
            char x = 0;
            if ((c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') || c == 39) x = (char)c;
            else if (c >= 'A' && c <= 'Z') x = (char)(c + 32);
            else if (c == 0xE2 && b[1] == 0x80 && (b[2] == 0x98 || b[2] == 0x99)) { x = 39; b += 2; }
            if (!x) break;
            if (wn < (int)sizeof w) w[wn++] = x; else long_word = 1;
            c = *++b;
        }
        if (wn) {
            cap = 0;
            int digits = 1;
            for (int i = 0; i < wn; i++) if (w[i] < '0' || w[i] > '9') digits = 0;
            if (digits) { p2 = OP_NONE; p1 = AFTER_NUMBER; continue; }
            uint16_t id = long_word ? OP_NONE : context_word(m, d->user, w, wn);
            p2 = p1; p1 = id;
            int skip = id != OP_NONE && in_u16(m->q_skip, m->n_skip, id);
            if (!f && !skip) f = q_state(m, id);
            if (!g && !skip) g = q_state(m, id);
            if (id != OP_NONE) {
                if (n_recent == OP_RECENT_WORDS) { memmove(recent, recent + 1, sizeof recent - sizeof *recent); n_recent--; }
                recent[n_recent++] = id;
            }
            continue;
        }
        if (c == '.' || c == '!' || c == '?' || c == '\n') {     /* a line break ends a sentence too */
            p2 = OP_NONE; p1 = m->bos; f = g = 0; cap = 1;
        } else if (c == ',') {
            p2 = p1; p1 = (uint16_t)(m->n_words + punct_index(m, ',')); g = 0; cap = 0;
        }
        b++;
    }
    *prev2 = p2;
    *first = f;
    *cf = g;
    d->ctx_prev = p1;
    d->ctx_cap = (uint8_t)cap;
    memcpy(d->recent, recent, (size_t)n_recent * sizeof *recent);
    d->n_recent = (uint8_t)n_recent;
}

static int recent_bonus(const op_decoder *d, const op_model *m, uint16_t id) {
    for (int i = 0; i < d->n_recent; i++)
        if (d->recent[i] == id) return id > m->bos || m->uni[id] < RECENT_MAX_UNI * m->scale ? RECENT_BONUS * m->scale : 0;
    return 0;
}

/* ---- beam search ---- */

static int cmp_entry(const void *x, const void *y) {
    const op_entry *a = (const op_entry *)x, *b = (const op_entry *)y;
    if (a->score != b->score) return a->score > b->score ? -1 : 1;
    return (int)a->seq - (int)b->seq;   /* ties keep generation order, like decoder.js's stable sort */
}


int op_decode(op_decoder *d, const op_model *m, const char *keys, int beam,
              const op_start *start, const op_lock *locks, int n_locks) {
    if (!d || !m || !keys || beam < 1 || beam > OP_MAX_BEAM) return OP_ERR_ARG;
    int r = tokenize(d, keys, start ? start->hint : NULL);
    if (r) return r;
    d->user = start && start->user && start->user->bos == m->bos ? start->user : NULL;
    if (d->user) join_learned(d);
    d->n_slots = 0;
    for (int i = 0; i < d->n_toks; i++) {
        if (d->toks[i].type == TOK_SPACE) continue;
        if (d->n_slots == OP_MAX_SLOTS) return OP_ERR_TOO_LONG;
        d->slot_tok[d->n_slots++] = (uint16_t)i;
    }
    int last_is_word = d->n_toks && d->toks[d->n_toks - 1].type == TOK_WORD;
    const int16_t *P = m->param;

    int32_t score[OP_MAX_BEAM];
    uint16_t prev[OP_MAX_BEAM], tri[OP_MAX_BEAM];
    uint8_t first[OP_MAX_BEAM], cf[OP_MAX_BEAM];
    int nb = 1;
    uint16_t prev2;
    context(d, m, start, &prev2, &first[0], &cf[0]);
    score[0] = 0;
    prev[0] = d->ctx_prev;
    tri[0] = tri_find(m, prev2, prev[0]);

    cand c[OP_MAX_CANDS];
    for (int j = 0; j < d->n_slots; j++) {
        const op_tok *t = &d->toks[d->slot_tok[j]];
        int is_final = j == d->n_slots - 1;
        int nc = slot_cands(d, m, t, is_final && last_is_word, c);
        char tk = t->type == TOK_NUM ? time_kind(d->keys + t->off, t->len) : 0;
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
                if (id == OP_TIME_ID) {
                    int before = 0;
                    for (int i = 0; i < OP_TIME_BEFORE; i++) if (prev[h] != OP_NONE && prev[h] == m->time_before[i]) before = 1;
                    step = m->scale * ((before ? TIME_PREV : -TIME_ALONE) - (tk == '.' ? TIME_LITERAL : 0));
                    p = AFTER_NUMBER;
                } else if (id == OP_NONE) {
                    step = c[ci].kind == OP_NUMBER ? 0 : c[ci].kind == OP_LITERAL ? P[OP_P_LITERAL] : P[OP_P_UNKNOWN];
                    p = c[ci].kind == OP_NUMBER ? (tk ? AFTER_DECIMAL : AFTER_NUMBER) : OP_NONE;
                } else {
                    step = token_score(m, d->user, prev[h], id, tri[h]) + c[ci].pen + recent_bonus(d, m, id);
                    p = id;
                }
                if (id != OP_NONE && id >= m->n_words && id < m->bos) {
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
                    int skip = id != OP_NONE && in_u16(m->q_skip, m->n_skip, id);
                    if (!f && !skip) f = q_state(m, id);
                    if (!g && !skip) g = q_state(m, id);
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
                e->tri = p == m->bos ? OP_NONE : tri_find(m, prev[h], p);
                ne++;
            }
        }
        /* Finished sentences are frozen (decoder.js): at a punctuation slot with more typed after
         * it, find what decoding showed when the keys stopped here; if that ended the sentence,
         * keep only the entries from its parent, so the words before it can't change. */
        if (t->type == TOK_PUNCT && !is_final) {
            int top = -1;
            int32_t best = 0;
            for (int i = 0; i < ne; i++) {
                const op_entry *e = &d->ent[i];
                int comma = e->id != OP_NONE && m->punct[e->id - m->n_words] == ',';
                int32_t sc = e->score + (comma ? P[OP_P_CF] : 0);
                if (top < 0 || sc > best) { top = i; best = sc; }
            }
            uint16_t tid = d->ent[top].id;
            char tc = tid != OP_NONE ? m->punct[tid - m->n_words] : 0;
            if (tc == '.' || tc == '!' || tc == '?') {
                uint8_t parent = d->ent[top].parent;
                int k = 0;
                for (int i = 0; i < ne; i++) if (d->ent[i].parent == parent) d->ent[k++] = d->ent[i];
                ne = k;
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
                dup = o->prev == e->prev && o->tri == e->tri && o->first == e->first && o->cf == e->cf;
            }
            if (!dup) kept[nk++] = i;
        }
        for (int k = 0; k < nk; k++) {
            const op_entry *e = &d->ent[kept[k]];
            score[k] = e->score;
            prev[k] = e->prev;
            first[k] = e->first;
            cf[k] = e->cf;
            tri[k] = e->tri;
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

/* Text of id in a casing table (display or alt), or -1. */
static int cased(const uint16_t *ids, uint32_t n, const uint32_t *off, const char *text, uint16_t id, const char **out) {
    uint32_t lo = 0, hi = n;
    while (lo < hi) {
        uint32_t mid = (lo + hi) / 2;
        if (ids[mid] == id) {
            *out = text + off[mid];
            return (int)(off[mid + 1] - off[mid]);
        }
        if (ids[mid] < id) lo = mid + 1; else hi = mid;
    }
    return -1;
}
/* A word's casing between prev and next: its other casing if (prev, id) is a capKey pair
 * ("in May") or (id, next) a capNextKey pair ("Will Smith"), unless (id, next) is a capKeepKey
 * pair ("like apple pie"); else its usual one (iPhone, Friday), else -1 for plain lowercase.
 * See decoder.js capFlip. */
static int display(const op_model *m, uint16_t prev, uint16_t id, uint16_t next, const char **text) {
    int keep = next < m->n_words && find_u32(m->cap_keep, m->n_cap_keep, (uint32_t)id << 16 | next) >= 0;
    if (id < m->n_words && !keep && ((prev <= m->bos && find_u32(m->cap_key, m->n_cap, (uint32_t)prev << 16 | id) >= 0) ||
        (next < m->n_words && find_u32(m->cap_next, m->n_cap_next, (uint32_t)id << 16 | next) >= 0)))
        return cased(m->alt_id, m->n_alt, m->alt_off, m->alt_text, id, text);
    return cased(m->disp_id, m->n_disp, m->disp_off, m->disp_text, id, text);
}

/* Call signs are shown in capitals: 1-2 letters, a digit, 1-4 letters (ke7aqa), or digit,
 * letter, digit, 1-3 letters (2e0abc). See decoder.js CALL_SIGN. */
static int call_sign(const char *w, int n) {
    int i = 0, a = 0, b = 0;
    #define LOW(c) ((c) >= 'a' && (c) <= 'z')
    #define DIG(c) ((c) >= '0' && (c) <= '9')
    if (n >= 3 && DIG(w[0]) && LOW(w[1]) && DIG(w[2])) {
        for (i = 3; i < n && LOW(w[i]); i++) b++;
        return i == n && b >= 1 && b <= 3;
    }
    for (; i < n && LOW(w[i]); i++) a++;
    if (a < 1 || a > 2 || i >= n || !DIG(w[i])) return 0;
    for (i++; i < n && LOW(w[i]); i++) b++;
    return i == n && b >= 1 && b <= 4;
    #undef LOW
    #undef DIG
}

int op_render(const op_decoder *d, const op_model *m, const op_start *start, char *out, int cap) {
    int n = 0, cap_next = d->ctx_cap;
    uint16_t prev = d->ctx_prev;                      /* as op_decode's context */
    (void)start;
    for (int i = 0, j = 0; i < d->n_toks; i++) {
        const op_tok *t = &d->toks[i];
        if (t->type == TOK_SPACE) {
            if (n + 1 >= cap) return OP_ERR_SPACE;
            out[n++] = ' ';
            continue;
        }
        op_choice ch = d->choice[j++];
        if (t->type == TOK_PUNCT) {
            if (n + 1 >= cap) return OP_ERR_SPACE;
            out[n++] = ch.kind == OP_LITERAL ? t->lit : m->punct[ch.id - m->n_words];
            cap_next = out[n - 1] == '.' || out[n - 1] == '!' || out[n - 1] == '?';
            prev = ch.kind == OP_LITERAL ? OP_NONE : out[n - 1] == ',' ? ch.id : m->bos;
            continue;
        }
        if (t->type == TOK_NUM) {
            int len = format_number(d->keys + t->off, t->len, ch.kind == OP_TIME, out + n, cap - n);
            if (len < 0) return len;
            n += len;
            cap_next = 0;
            prev = OP_NONE;
            continue;
        }
        int s = n, len, call;
        if (ch.kind == OP_WORD || ch.kind == OP_PARTIAL) {
            const char *w, *shown, *src;
            /* the next word, if a whole word comes right after (spaces only between) */
            uint16_t next = OP_NONE;
            int k = i + 1;
            while (k < d->n_toks && d->toks[k].type == TOK_SPACE) k++;
            if (k < d->n_toks && d->toks[k].type == TOK_WORD && d->choice[j].kind == OP_WORD) next = d->choice[j].id;
            int wn = tok_text(m, d->user, ch.id, &w), dn = display(m, prev, ch.id, next, &shown);
            call = dn >= 0 ? call_sign(shown, dn) : call_sign(w, wn);
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
            /* Typed exactly, or no dictionary word fits: the exact letters, else the QWERTY
             * letters tapped, else each key's first letter. */
            if (n + t->len >= cap) return OP_ERR_SPACE;
            for (int k = 0; k < t->len; k++) {
                char l = d->lits[t->off + k], key = d->keys[t->off + k];
                if (!l) l = d->hints[t->off + k];
                if (!l) l = key == '#' ? '\'' : (key >= '2' && key <= '9') ? FIRST_LETTER[key - '2'] : '?';
                out[n++] = l;
            }
            call = call_sign(out + s, n - s);
        }
        len = n - s;
        if (call) for (int k = s; k < n; k++) if (out[k] >= 'a' && out[k] <= 'z') out[k] = (char)(out[k] - 'a' + 'A');
        if (len && out[s] == 'i' && (len == 1 || out[s + 1] == '\'')) out[s] = 'I';
        /* Capitalize a sentence start, but keep brand styling like iPhone / eBay. */
        int brand = len >= 2 && out[s] >= 'a' && out[s] <= 'z' && out[s + 1] >= 'A' && out[s + 1] <= 'Z';
        if (cap_next && !brand && len && out[s] >= 'a' && out[s] <= 'z') out[s] = (char)(out[s] - 'a' + 'A');
        cap_next = 0;
        prev = ch.kind == OP_WORD && ch.id < m->n_words ? ch.id : OP_NONE;
    }
    if (n >= cap) return OP_ERR_SPACE;
    out[n] = 0;
    return n;
}

/* ---- learning ---- */

void op_user_init(op_user *u, const op_model *m) {
    memset(u, 0, sizeof *u);
    u->bos = m->bos;
}

static void user_bump(op_user *u, uint16_t prev, uint16_t cur) {
    int i = user_find(u, prev, cur);
    if (i >= 0) {
        if (u->pair[i].count < 255) u->pair[i].count++;
        return;
    }
    /* Full: halve every count and drop the ones that reach zero, until there is room. */
    while (u->n_pairs >= OP_USER_PAIRS) {
        int k = 0;
        for (int j = 0; j < u->n_pairs; j++) {
            u->pair[j].count >>= 1;
            if (u->pair[j].count) u->pair[k++] = u->pair[j];
        }
        u->n_pairs = (uint16_t)k;
    }
    i = -user_find(u, prev, cur) - 1;
    memmove(&u->pair[i + 1], &u->pair[i], (size_t)(u->n_pairs - i) * sizeof *u->pair);
    u->pair[i].prev = prev;
    u->pair[i].cur = cur;
    u->pair[i].count = 1;
    u->n_pairs++;
}

/* Id of learned word w[0..wn), adding it (replacing the least used one when full). */
static uint16_t user_word(op_user *u, const op_model *m, const char *w, int wn) {
    int k = -1;
    for (int j = 0; j < u->n_words && k < 0; j++)
        if ((int)strlen(u->word[j]) == wn && memcmp(u->word[j], w, (size_t)wn) == 0) k = j;
    if (k < 0 && u->n_words < OP_USER_WORDS) {
        k = u->n_words++;
    } else if (k < 0) {
        k = 0;
        for (int j = 1; j < u->n_words; j++)
            if (user_count(u, USER_ANY, (uint16_t)(m->bos + 1 + j)) < user_count(u, USER_ANY, (uint16_t)(m->bos + 1 + k))) k = j;
        uint16_t id = (uint16_t)(m->bos + 1 + k);
        int kept = 0;
        for (int j = 0; j < u->n_pairs; j++)
            if (u->pair[j].prev != id && u->pair[j].cur != id) u->pair[kept++] = u->pair[j];
        u->n_pairs = (uint16_t)kept;
    }
    memcpy(u->word[k], w, (size_t)wn);
    u->word[k][wn] = 0;
    return (uint16_t)(m->bos + 1 + k);
}

/* Mirrors decoder.js learn. */
int op_learn(op_user *u, const op_decoder *d, const op_model *m, const op_start *start) {
    if (!u || !d || !m || u->bos != m->bos) return OP_ERR_ARG;
    uint16_t prev = d->ctx_prev;
    (void)start;
    for (int j = 0; j < d->n_slots; j++) {
        op_choice ch = d->choice[j];
        const op_tok *t = &d->toks[d->slot_tok[j]];
        uint16_t id = ch.id;
        if (ch.kind == OP_NUMBER || ch.kind == OP_TIME) { prev = AFTER_NUMBER; continue; }
        if (ch.kind == OP_LITERAL && t->type != TOK_WORD) { prev = OP_NONE; continue; }   /* ':' */
        if (ch.kind == OP_LITERAL || (ch.kind == OP_UNKNOWN && t->type == TOK_WORD)) {
            /* Spelled exactly, or typed on QWERTY with no word matching: learn it. */
            char w[OP_USER_WORD_LEN];
            int ok = t->len <= OP_USER_WORD_LEN;
            for (int k = 0; ok && k < t->len; k++) {
                char l = d->lits[t->off + k];
                if (!l) l = d->hints[t->off + k];
                if (!l && d->keys[t->off + k] == '#') l = 39;
                if (!((l >= 'a' && l <= 'z') || (l >= '0' && l <= '9') || l == 39)) ok = 0;
                w[k] = l;
            }
            if (!ok) { prev = OP_NONE; continue; }
            id = user_word(u, m, w, t->len);
        } else if (ch.kind == OP_PARTIAL || id == OP_NONE) {
            prev = OP_NONE;
            continue;
        }
        user_bump(u, USER_ANY, id);
        if (prev != OP_NONE && prev != AFTER_NUMBER) user_bump(u, prev, id);
        prev = id >= m->n_words && id < m->bos && m->punct[id - m->n_words] != ',' ? m->bos : id;
    }
    return OP_OK;
}
