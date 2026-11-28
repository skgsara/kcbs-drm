/* Exercise the unmodified 3GPP range encoder on the five noisy SWB GSC codebooks. */
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include "prot.h"

enum { BANDS = 5, BLOCK_BITS = 51, RAW_BITS = 9, TRIALS = 2000 };
static const unsigned sizes[BANDS] = {256, 256, 256, 256, 2736};
static uint32_t random_state = 0x1320u;

static uint32_t next_random(void)
{
    random_state = random_state * 1664525u + 1013904223u;
    return random_state;
}

static void require(int condition, int trial, const char *message)
{
    if (!condition) {
        fprintf(stderr, "Stock range-encoder trial %d: %s\n", trial, message);
        exit(EXIT_FAILURE);
    }
}

int main(void)
{
    static Encoder_State state;
    static Indice indices[MAX_NUM_INDICES];
    int counts[3][2] = {{0}};
    unsigned witness_indices[BANDS] = {0}, witness_signs[BANDS] = {0};
    unsigned ranges[BANDS] = {0};
    state.ind_list = indices;

    for (int trial = 0; trial < TRIALS; ++trial) {
        unsigned values[BANDS], signs[BANDS];
        reset_indices_enc(&state);
        rc_enc_init(&state, BLOCK_BITS);
        for (int band = 0; band < BANDS; ++band) {
            values[band] = (next_random() >> 4) % sizes[band];
            signs[band] = next_random() >> 31;
            rc_enc_bits(&state, signs[band], 1);
            rc_enc_uniform(&state, values[band], sizes[band]);
            if (trial == 0)
                ranges[band] = state.rc_range;
            require(state.rc_range == ranges[band], trial, "range changed with symbol value");
        }
        require(state.rc_num_bits == 32 + RAW_BITS, trial, "unexpected count before finish");
        rc_enc_finish(&state);
        int fill = BLOCK_BITS - state.rc_num_bits;
        require(fill == 1 || fill == 2, trial, "unexpected zero-fill width");

        unsigned char bytes[7] = {0};
        short width = 0;
        indices_to_serial_generic(indices, MAX_NUM_INDICES, bytes, &width);
        require(width == BLOCK_BITS, trial, "unexpected serialized width");
        /* Physical bits 222 and 223 are bits 40 and 41 of the MSB-first block. */
        int bit222 = (bytes[5] >> 7) & 1;
        int bit223 = (bytes[5] >> 6) & 1;
        require(bit223 == 0, trial, "b223 was one");
        require(fill == 1 || bit222 == 0, trial, "two-bit fill contained a one");
        if (bit222 && !counts[1][1]) {
            for (int band = 0; band < BANDS; ++band) {
                witness_indices[band] = values[band];
                witness_signs[band] = signs[band];
            }
        }
        ++counts[fill][bit222];
    }

    require(counts[1][1] && counts[2][0], TRIALS, "missing one-bit or two-bit witness");
    for (int band = 0; band < BANDS; ++band)
        printf("range %u\n", ranges[band]);
    for (int fill = 1; fill <= 2; ++fill)
        for (int b222 = 0; b222 <= 1; ++b222)
            printf("count %d %d %d\n", fill, b222, counts[fill][b222]);
    for (int band = 0; band < BANDS; ++band)
        printf("witness %u %u\n", witness_indices[band], witness_signs[band]);
    return EXIT_SUCCESS;
}
