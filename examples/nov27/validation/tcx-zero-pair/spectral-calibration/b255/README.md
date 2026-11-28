# What the TCX decoder reads at bit 255

In the 15 complete first-position words of counter `43865914`, physical bit 255 selected the sign of an already nonzero quantized coefficient eight times. In the other seven words it refined an already nonzero spectral coefficient. The comparison uses the original 128-bit prefix and all remaining bits of each known word. Bit 255 is the least significant bit of payload octet 30 when the mode octet is excluded.

| Observed operation | Zero-based cycles | Effect of the fixed bit flip |
| --- | --- | --- |
| Read coefficient sign | 0, 1, 2, 6, 7, 10, 11, 14 | The signed integer coefficient changes sign at the same magnitude. |
| Refine nonzero coefficient | 3, 4, 5, 8, 9, 12, 13 | The binary operand selecting a refinement at the same coefficient changes. |

The outputs identify the decoder’s zero-based spectral bin. For a sign, the original and flipped operands are the signed coefficient after the read. For a refinement, they are the bit values consumed by `tcx_res_invQ_spec`. Cycle 3 uses residual index 6. The other six refinement cycles use index 4. [Per-cycle operands and bins](expected.json)

The observer reads the stock decoder’s cursor immediately before `get_next_indice_1` in the sign loop. For residuals it records the backwards address `lsbs_bit_pos - k`, then observes the same residual index in the synthesis inverse quantizer. The sign and residual ranges and the consumer’s bin agree across the two chronological replays in every cycle. A separate cold decode of each original word produced the same ranges, operation, bin and operand in all fifteen cases. These observed histories do not establish that another word has the same layout.

All 15 predetermined flips change PCM in the corresponding 20 ms slot. Both alternatives keep the other 263 current-word bits, including the complete 27-octet projection, identical. Field location was measured on fully specified words. This test supplies no second-position bit value. [Arithmetic reserialization control, expected T records and chronology](../README.md)

## Reproduce

Use Python 3.10+, a C compiler with GNU99 support, the November 4, 2021 floating-point TS 26.443 `c-code` directory, and an unmodified `EVS_dec` built from that version. Keep the parent directory’s `check.py` and `first-position.bin` in place. Run from this directory.

```sh
python3 -I build.py --source /path/to/c-code --out /tmp/b255-observer
python3 -I check.py --observer /tmp/b255-observer --stock /path/to/EVS_dec > result.json
```

The build checks the two instrumented source digests and creates the observer at a new path. The replay verifies the frozen chronological input, compares observer PCM with stock PCM for every run and checks the per-cycle results against `expected.json`. A reproducible run reports `matches_expected: true`. [Build and source digest checks](build.py) · [Replay](check.py)
