/* Command-line driver: decode one key string per line of stdin.
 *   opdecode onepress.bin [beam] [--learn] < keys.txt
 * --learn: one person typed every line, and each decoded line is learned before the next.
 * Used by tests/parity.js to check the C decoder against web/decoder.js. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "onepress.h"

static op_model model;
static op_decoder dec;
static op_user user;

int main(int argc, char **argv) {
    if (argc < 2) {
        fprintf(stderr, "usage: opdecode model.bin [beam] [--learn] < keys.txt\n");
        return 2;
    }
    int beam = argc > 2 ? atoi(argv[2]) : 8, learn = argc > 3 && strcmp(argv[3], "--learn") == 0;
    FILE *f = fopen(argv[1], "rb");
    if (!f) {
        perror(argv[1]);
        return 1;
    }
    fseek(f, 0, SEEK_END);
    long size = ftell(f);
    fseek(f, 0, SEEK_SET);
    void *blob = malloc((size_t)size);     /* malloc memory is suitably aligned */
    if (!blob || fread(blob, 1, (size_t)size, f) != (size_t)size) {
        fprintf(stderr, "can't read %s\n", argv[1]);
        return 1;
    }
    fclose(f);
    if (op_model_open(&model, blob, (size_t)size) != OP_OK) {
        fprintf(stderr, "%s is not a KPD2 model\n", argv[1]);
        return 1;
    }

    op_user_init(&user, &model);
    op_start start = { model.bos, 1, learn ? &user : NULL, NULL, NULL };
    static char line[4 * OP_MAX_KEYS + 4096];
    char out[4 * OP_MAX_KEYS + 64];
    while (fgets(line, sizeof line, stdin)) {
        line[strcspn(line, "\r\n")] = 0;
        /* @Word: give the learned word spelled that way (ignoring case) this casing, as an app's
         * "capitalize this word" would; prints the line back. */
        if (line[0] == '@') {
            for (int k = 0; k < user.n_words; k++) {
                size_t n = strlen(user.word[k]), i = 0;
                if (n != strlen(line + 1)) continue;
                while (i < n && (user.word[k][i] | 32) == (line[1 + i] | 32)) i++;
                if (i == n) memcpy(user.word[k], line + 1, n);
            }
            printf("%s\n", line);
            continue;
        }
        /* keys<TAB>before<TAB>hint: the text before ('|' for a line break), the QWERTY letters */
        char *before = strchr(line, '\t'), *hint = NULL;
        if (before) {
            *before++ = 0;
            hint = strchr(before, '\t');
            if (hint) *hint++ = 0;
            for (char *c = before; *c; c++) if (*c == '|') *c = '\n';
        }
        start.before = before;
        start.hint = hint;
        int r = op_decode(&dec, &model, line, beam, &start, NULL, 0);
        if (r == OP_OK) r = op_render(&dec, &model, &start, out, sizeof out);
        if (r >= 0 && learn) op_learn(&user, &dec, &model, &start);
        if (r < 0) printf("<error %d>\n", r);
        else printf("%s\n", out);
    }
    return 0;
}
