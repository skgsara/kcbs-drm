# Wideband GSC pulse-codebook control

Two synthetic 13.2 kbit/s EVS encoder runs produced nine words whose first 128 physical bits were sufficient to predict two later bits. All nine predictions matched the original sender words. Physical bits 230 and 231 are the two least significant bits of payload octet 27 when the mode octet is excluded.

| Synthetic input and maximum bandwidth | Total words | GSC blocks | Qualifying zero-based slots | Slots at position 2 |
| --- | ---: | ---: | --- | --- |
| 48 s, 32 kHz input, WB | 2,400 | 597 | 193, 793, 1787, 1796, 1962, 2161 | 193, 793, 2161 |
| 480 s, 16 kHz input, WB | 24,000 | 6,313 | 745, 8584, 19740 | 745 |

Position 2 means a slot index congruent to 1 modulo 4 in these synthetic timelines. The first stream's six words use WB INACTIVE GSC. The second stream's three use WB AUDIO GSC. The codebook bound applies whenever the reference allocation reaches the stated size, range symbol and raw-bit position. The prefixes in this experiment yielded zero restrictions on octet 24.

## Reproduce

Use Python 3 with NumPy, GCC, the floating-point TS 26.443 C source dated 4 November 2021, and its stock `EVS_cod` binary. Run this command from this directory.

```sh
python -B check.py --source /path/to/c-code --encoder /path/to/EVS_cod --out result.json
```

The command generates both PCM inputs, invokes the stock encoder, and compares SHA-256 digests for both the PCM and the original G.192 files. The expected file includes per-slot hashes of the nine 16-byte prefixes. Their concatenation in the table's order hashes to `b98e98d745f0282b54070c0341c41a8b6c65d4cc020817fd1e45b396bb063d18`. [Expected digests and observations](expected.json)

## What the two runs check

1. **Stateful census.** The stock decoder processes each complete sender stream from reset. At GSC entry the observer checks that all prior current-word bit reads fit within the first 128 bits. It starts a separate PVQ allocation walk using that prefix and the checked allocation. The walk keeps lower and upper bounds on the arithmetic register wherever prefetch extends past bit 127. It stops if those bounds allow different cumulative frequencies or a required split flag is unavailable. Leading signs and raw index residuals consume their declared widths without supplying values, which preserves allocation accounting. The complete decoder's PCM matches the pinned stock result. Once the walk has emitted its predictions, the verifier opens the original residuals for comparison.
2. **Independent cold-word controls.** Each of the nine sender words is then decoded alone, in a fresh process, four times. The prefix-derived symbol and its physical address recur in all 36 runs. The genuine pair is `00` in all nine. Substituting `01`, `10` or `11` while retaining every other bit causes the reference decoder's MPVQ index-range check to fire in 27 of 27 runs. The corresponding nine originals pass that branch. The JSON lists the actual native indices and error outcomes for each slot.

The stock sender computes a pulse-vector index smaller than its codebook size in `lib_enc/pvq_encode.c`. In `lib_enc/range_enc.c`, `rc_enc_uniform` splits a large index into an arithmetic-coded upper part and backward-written low bits. Each qualifying word uses a 16-dimensional, five-pulse codebook of size 142,544, an upper part of 139, and 10 low bits at physical [230, 240). Since `142544 - 139*1024 = 208`, the legal residual is 0 through 207 and its first two bits must be zero. The separately exercised error branch is `entry.index >= entry.size` in `lib_dec/pvq_decode.c`.

Other codebook sizes, arithmetic symbols or addresses can give different outcomes. These runs demonstrate the conditional relation on synthetic wideband sender output. They supply no frequency-of-occurrence estimate for a broadcaster or another EVS bandwidth.
