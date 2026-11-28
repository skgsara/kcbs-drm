# Transition pairs in original EVS sender words

The table counts every occurrence of four exact mode and final payload octet (p31) combinations in 12 previously generated 13.2 kb/s EVS streams. Each of the 32 matching 33-byte words was distinct. Word bits 8–9 are the high two bits of the octet immediately after the mode. [Original words and zero-based frame numbers](witnesses.tsv) · [Earlier pinned hashes for all 12 streams](https://github.com/skgsara/kcbs-drm/blob/a120e545540041f8fcd07203c6554c163593a4bd/examples/nov28/gsc-fields/f8-sender.json)

| Mode / p31 | Sender words | Original bits 8–9 |
|---|---:|---|
| 60 / 3A | 1 | 00 |
| 60 / B6 | 10 | 00 in all 10 |
| 61 / 6C | 9 | 01 in all 9 |
| 61 / 4C | 12 | 01 in all 12 |

The streams contained 54,802 words, including 1,988 SWB TRANSITION words. All 32 matches came from seven synthetic stimuli that share generator code and use different seeds. The original 48-second public transition control contained zero occurrences. This retrospective comparison measures one stock encoder. Independent clear labels for these bits at radio counter 43288730 remain unavailable.

## Reproduce the 60 / 3A control

From this directory, generate two minutes of 32 kHz mono PCM with NumPy, then run the unmodified floating-point TS 26.443 encoder dated November 4, 2021. A fresh run from reset reproduced the entire 6,000-word stream byte for byte, including all nine TSV rows for `transient_bands`. Its sole `60/3A` word is frame 5782 and begins `60 15`, giving `00`.

```sh
python transient_bands.py transient_bands.s16
EVS_cod -q -no_delay_cmp -max_band SWB 13200 32 transient_bands.s16 transient_bands.192
sha256sum transient_bands.s16 transient_bands.192
```

| File | Expected SHA-256 |
|---|---|
| `transient_bands.s16` | `8c3487c0256aa2a76e131fe99d76f222ff202ba53d8e3fcf5034de9d39235b59` |
| `transient_bands.192` | `160386c2f92f0ebadf1ca7e0de6b1ca19c19dbc281f82bbd9b357e667a648c48` |

To read the matching sender frame from the regenerated file, run the following in the same directory. The output is `5782 15 00` (frame number, second octet in hex, high two bits in binary).

```sh
PYTHONPATH=../../../../scripts python - <<'PY'
from compare_evs_group import read_words
for frame, word in enumerate(read_words("transient_bands.192")):
    if word and word[0] == 0x60 and word[-1] == 0x3A:
        print(frame, f"{word[1]:02X}", f"{word[1] >> 6:02b}")
PY
```
