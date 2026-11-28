# Why the stock encoder writes zero at word bit 223

For ordinary 13.2 kb/s EVS, the checker selects a SWB GSC AUDIO/TBE word with mode octet `68`–`6B` (hex), noisy-speech flag b40 = 1, and four-bit pitch-band index b41–b44 in 1–10. Bit numbers start at the MSB of the mode octet. In the 12.8 kHz core this branch uses four subframes. Its five-band pulse-vector block occupies word bits [182,233), with budgets of 10, 10, 10, 10 and 11 bits. Under that allocation **b223, the low bit of payload octet 26, is always zero**. Adjacent b222 can be one. The public checker uses the mode and payload octet 4 to select a word before it reads the target. [Direct-field checker](../../../../scripts/evs_gsc_fields.py)

## Width proof

The encoder writes one leading sign for each of the five vectors. Their codebook sizes are 256, 256, 256, 256 and 2,736. The final index contributes four additional low bits to the backward stream, for nine raw bits in total. Its high part is 0–170 and the range coder uses total `(2736 >> 4) + 1 = 172`. Thus the five arithmetic totals are 256, 256, 256, 256 and 172. Every symbol has frequency one.

For current range `R`, the stock `UL_inverse(total)` returns reciprocal `I` and exponent `e`. Before renormalization, the next range is `((R × I) >> 32) >> (e − 32)`. The chosen symbol affects the low register and carry. The range depends only on the total and symbol frequency. Starting from `0xFFFFFFFF`, the stock integer recurrence gives the following widths.

| Arithmetic total | Range before renormalization | Shift bits | Range after renormalization |
|---|---:|---:|---:|
| 256 | 16,777,215 | 8 | 0xFFFFFF00 |
| 256 | 16,777,214 | 8 | 0xFFFFFE00 |
| 256 | 16,777,213 | 8 | 0xFFFFFD00 |
| 256 | 16,777,212 | 8 | 0xFFFFFC00 |
| 172 | 24,970,734 | 0 | 0x017D05EE |

The shifts consume 32 forward bits. All five sign writes fit. Just before the last four raw bits, 37 bits are accounted for and the final range has seven leading zeros. The stock budget test gives `37 + 2 + 7 + 4 = 50 ≤ 51`, so the encoder writes all four. At entry to `rc_enc_finish`, 41 bits are accounted for and ten remain. Its first termination length is `norm_ul(range) + 1 = 8`. Its low-register rounding branch can increase that length once, to nine. Both lengths fit. The final explicit zero fill therefore occupies two bits or one bit immediately before the backward indices. Those indices start at `233 − 9 = 224`. The last zero is always at 223.

The native harness calls the stock range encoder, serializes the 51-bit block, and checks both positions on 2,000 fixed legal index sequences. It observed b223 zero in all 2,000 and b222 one in 1,011. One b222=1 witness uses indices `191, 136, 122, 124, 2424` and leading signs `0, 1, 0, 0, 1`. These trials verify the implementation and show why the guarantee stops at b223. The integer width proof covers every legal symbol sequence with this allocation. [Expected result](expected.json)

## Reproduce

Use Python 3, GCC and GNU-compatible linker section garbage collection. The source argument is the directory containing `lib_com`, `lib_dec` and `lib_enc` from the November 4, 2021 floating-point reference code. The checker verifies the hashes of the five C translation units used, then compiles the harness in a temporary directory. The official TS 26.443 archive has SHA-256 `f3e0928f917fe67a620a37578757b0db00e0ca216481a96a99ea8ff5e3b8271b`. [ETSI reference software](https://www.etsi.org/deliver/etsi_ts/126400_126499/126443/19.00.00_60/ts_126443v190000p0.zip)

From any working directory, supply the paths to this example and the extracted source tree.

```sh
example=/path/to/repository/examples/nov28/gsc-fields/padding
python3 "$example/check.py" /path/to/c-code --out /tmp/gsc-padding.json
cmp "$example/expected.json" /tmp/gsc-padding.json
```

Omit `--out` to print the result. The expected JSON has SHA-256 `dd4f7cbffb6a5409e985272e0da19d1031203a486613ef50997a9a77012d80ba` regardless of the source tree’s absolute path.
