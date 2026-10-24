/* OnePress decoder: one keypad press per letter, a word-pair model picks the letters.
 *
 * Portable C99 with no allocation: the model is read in place (flash, a memory map or a
 * buffer) and all working memory lives in an op_decoder the caller provides. Mirrors
 * web/decoder.js exactly; tests/parity.js checks the two agree.
 *
 * Usage:
 *   static op_model model;   static op_decoder dec;
 *   op_model_open(&model, blob, blob_size);           // blob: 4-byte aligned KPD2 file
 *   op_decode(&dec, &model, "4330968", 8, NULL, NULL, 0);
 *   op_render(&dec, &model, NULL, out, sizeof out);   // "Hello you"
 *
 * Key strings use the same characters as decoder.js: '2'-'9' predictive letters, '0'
 * space, '#' punctuation (an apostrophe between letters), and from exact mode the literal
 * characters 'a'-'z', '\'', '.', ',', '?', '!' and 'A'-'J' for the digits 0-9 (exact mode or
 * a held number key). Digits form numbers: #6#000#00 renders "$6,000.00".
 *
 * Memory: sizeof(op_decoder) is about 20 KB with the defaults below. Small targets can
 * lower the limits, e.g. -DOP_MAX_BEAM=4 -DOP_MAX_SLOTS=48 -DOP_MAX_KEYS=160 for ~5 KB.
 * The model must be little-endian (it is on ARM, x86, ESP32 and RISC-V).
 */
#ifndef ONEPRESS_H
#define ONEPRESS_H

#include <stddef.h>
#include <stdint.h>

#ifndef OP_MAX_KEYS
#define OP_MAX_KEYS 256         /* key presses in one composition */
#endif
#ifndef OP_MAX_SLOTS
#define OP_MAX_SLOTS 96         /* words + punctuation marks in one composition */
#endif
#ifndef OP_MAX_BEAM
#define OP_MAX_BEAM 16          /* largest beam op_decode accepts; 4-8 is plenty */
#endif
#define OP_MAX_EXACT 40         /* dictionary words considered per slot */
#define OP_MAX_COMPLETIONS 12   /* extra prefix completions for the word being typed */
#define OP_MAX_CANDS (OP_MAX_EXACT + OP_MAX_COMPLETIONS)

#define OP_NONE 0xFFFF          /* token id of an unknown word (decoder.js uses -1) */

enum { OP_OK = 0, OP_ERR_MODEL = -1, OP_ERR_TOO_LONG = -2, OP_ERR_SPACE = -3, OP_ERR_ARG = -4 };

/* What each slot was decoded as. */
enum { OP_WORD, OP_PARTIAL, OP_PUNCT, OP_LITERAL, OP_UNKNOWN, OP_NUMBER };

enum { OP_P_QQ, OP_P_QN, OP_P_DQ, OP_P_CF, OP_P_DB, OP_P_CB, OP_P_EB,
       OP_P_APOSTROPHE, OP_P_COMPLETION, OP_P_LITERAL, OP_P_UNKNOWN, OP_N_PARAMS };

typedef struct {
    uint16_t scale, n_words, n_punct, bos;
    const char *word_text;
    const uint32_t *word_off;
    const uint16_t *key_idx, *strip_idx;
    uint32_t n_strip;
    const uint16_t *disp_id;
    const uint32_t *disp_off;
    const char *disp_text;
    uint32_t n_disp;
    const int16_t *uni, *bow, *lp;
    const uint32_t *row_start;
    const uint16_t *next;
    const uint16_t *q_start;
    uint32_t n_q;
    const char *punct;
    int16_t param[OP_N_PARAMS];
    uint16_t time_id[2];        /* "am", "pm" (OP_NONE if absent) */
} op_model;

/* Context before the composition, from the text already in the field. */
typedef struct {
    uint16_t prev;      /* previous token id: model->bos at a sentence start, OP_NONE if unknown */
    uint8_t cap;        /* capitalize the first word */
} op_start;

/* Force slot `slot` to word `id` (as decoder.js locks do). Ignored if that word isn't a candidate. */
typedef struct {
    uint16_t slot, id;
} op_lock;

typedef struct {
    uint8_t type;       /* internal token type */
    char lit;           /* punctuation typed exactly, or 0 */
    uint16_t off, len;  /* word: span of keys[] / lits[] */
} op_tok;

typedef struct {
    uint16_t id;        /* token id, or OP_NONE for OP_LITERAL / OP_UNKNOWN / OP_NUMBER */
    uint8_t kind;       /* OP_WORD, OP_PARTIAL, ... */
} op_choice;

typedef struct {
    int32_t score;
    uint16_t seq, prev, id;
    uint8_t parent, kind, first, cf;
} op_entry;

typedef struct {
    /* Results of the last op_decode. */
    uint16_t n_toks, n_slots;
    op_tok toks[OP_MAX_KEYS];
    uint16_t slot_tok[OP_MAX_SLOTS];
    op_choice choice[OP_MAX_SLOTS];
    int32_t score;
    /* Working memory. */
    char keys[OP_MAX_KEYS], lits[OP_MAX_KEYS];
    struct { uint16_t id; uint8_t parent, kind; } bp[OP_MAX_SLOTS][OP_MAX_BEAM];
    op_entry ent[OP_MAX_BEAM * OP_MAX_CANDS];
} op_decoder;

/* Point `m` at a KPD2 model. `data` must stay valid and be 4-byte aligned. */
int op_model_open(op_model *m, const void *data, size_t size);

/* Decode a key string (NUL-terminated). beam: 1..OP_MAX_BEAM. start/locks may be NULL. */
int op_decode(op_decoder *d, const op_model *m, const char *keys, int beam,
              const op_start *start, const op_lock *locks, int n_locks);

/* Write the decoded text (NUL-terminated) and return its length, or OP_ERR_SPACE. */
int op_render(const op_decoder *d, const op_model *m, const op_start *start, char *out, int cap);

/* Word text of token `id` (not NUL-terminated); returns its length. */
int op_word(const op_model *m, uint16_t id, const char **text);

#endif
