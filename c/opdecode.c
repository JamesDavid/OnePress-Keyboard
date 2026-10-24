/* Command-line driver: decode one key string per line of stdin.
 *   opdecode onepress.bin [beam] [--learn] [--nn onepress-nn.bin] < keys.txt
 * --learn: one person typed every line, and each decoded line is learned before the next.
 * --nn: also score with the neural word model.
 * Used by tests/parity.js to check the C decoder against web/decoder.js. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "onepress.h"

static op_model model;
static op_decoder dec;
static op_user user;
static op_nn nn;
static op_nn_work nn_work;

/* The whole file, in malloc'd (so suitably aligned) memory. */
static void *read_file(const char *path, size_t *size) {
    FILE *f = fopen(path, "rb");
    if (!f) { perror(path); exit(1); }
    fseek(f, 0, SEEK_END);
    long n = ftell(f);
    fseek(f, 0, SEEK_SET);
    void *blob = malloc((size_t)n);
    if (!blob || fread(blob, 1, (size_t)n, f) != (size_t)n) { fprintf(stderr, "can't read %s\n", path); exit(1); }
    fclose(f);
    *size = (size_t)n;
    return blob;
}

int main(int argc, char **argv) {
    if (argc < 2) {
        fprintf(stderr, "usage: opdecode model.bin [beam] [--learn] [--nn network.bin] < keys.txt\n");
        return 2;
    }
    int beam = 8, learn = 0;
    const char *nn_path = NULL;
    for (int i = 2; i < argc; i++) {
        if (strcmp(argv[i], "--learn") == 0) learn = 1;
        else if (strcmp(argv[i], "--nn") == 0 && i + 1 < argc) nn_path = argv[++i];
        else beam = atoi(argv[i]);
    }
    size_t size;
    void *blob = read_file(argv[1], &size);
    if (op_model_open(&model, blob, size) != OP_OK) {
        fprintf(stderr, "%s is not a KPD2 model\n", argv[1]);
        return 1;
    }
    if (nn_path) {
        void *nb = read_file(nn_path, &size);
        if (op_nn_open(&nn, nb, size, &model) != OP_OK) {
            fprintf(stderr, "%s is not a KPN1 network for this model\n", nn_path);
            return 1;
        }
    }

    op_user_init(&user, &model);
    op_start start = { model.bos, 1, learn ? &user : NULL, NULL, NULL, nn_path ? &nn : NULL, &nn_work };
    static char line[4 * OP_MAX_KEYS + 4096];
    char out[4 * OP_MAX_KEYS + 64];
    while (fgets(line, sizeof line, stdin)) {
        line[strcspn(line, "\r\n")] = 0;
        /* @@save: save the user, load it back, and print the saved bytes in hex. */
        if (strcmp(line, "@@save") == 0) {
            static uint8_t saved[sizeof(op_user) + 16];
            int n = op_user_save(&user, saved, sizeof saved);
            if (n < 0 || op_user_load(&user, &model, saved, (size_t)n) != OP_OK) { printf("<save error>\n"); continue; }
            for (int i = 0; i < n; i++) printf("%02x", saved[i]);
            printf("\n");
            continue;
        }
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
