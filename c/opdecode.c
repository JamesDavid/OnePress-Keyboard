/* Command-line driver: decode one key string per line of stdin.
 *   opdecode onepress.bin [beam] < keys.txt
 * Used by tests/parity.js to check the C decoder against web/decoder.js. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "onepress.h"

static op_model model;
static op_decoder dec;

int main(int argc, char **argv) {
    if (argc < 2) {
        fprintf(stderr, "usage: opdecode model.bin [beam] < keys.txt\n");
        return 2;
    }
    int beam = argc > 2 ? atoi(argv[2]) : 8;
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

    char line[OP_MAX_KEYS + 8], out[4 * OP_MAX_KEYS + 64];
    while (fgets(line, sizeof line, stdin)) {
        line[strcspn(line, "\r\n")] = 0;
        int r = op_decode(&dec, &model, line, beam, NULL, NULL, 0);
        if (r == OP_OK) r = op_render(&dec, &model, NULL, out, sizeof out);
        if (r < 0) printf("<error %d>\n", r);
        else printf("%s\n", out);
    }
    return 0;
}
