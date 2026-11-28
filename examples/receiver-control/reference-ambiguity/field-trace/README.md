# Why four different narrowband words give the same decoded PCM

At slots 1648, 1664, 1702 and 1743 of the official clean narrowband 13.2 kb/s pair, word octet 10 carries two flags about an earlier HQ frame. Each fixed-point vector transmits `00` and its floating-point counterpart transmits `11`. The flags differ in meaning. On these four frames both values lead the floating-point decoder to the same integer spectrum and the same audio. [Official-vector comparison](../official.json) · [Full-stream playback and individual replacement tests](../playback.py)

| Zero-based slot | Changed physical bits, mode MSB = 0 | TCQ bit budget | Selected secondary allocation indices under both values |
|---:|---|---:|---|
| 1648 | 80, 81 | 178 | 2, 0 |
| 1664 | 84, 85 | 174 | 2, 9 |
| 1702 | 80, 81 | 178 | 2, 0 |
| 1743 | 81, 82 | 177 | 2, 7 |

All four signal nontransient, narrowband low-rate HQ. The TS 26.443 encoder writes `IND_HQ2_LAST_BA_MAX_BAND` twice at `lib_enc/hq_lr_enc.c:591`. Lines 845–858 update the sender's memory from pulse presence in the second-highest and highest bands of its most recent eligible narrowband or wideband HQ word. The receive trace records the **flags actually carried**. It does not reconstruct either encoder's earlier decisions. [Source conditions and previous sender control](../../../nov27/validation/hq-history/README.md)

The TS 26.443 decoder reads both flags at `lib_dec/hq_lr_dec.c:257–264`. Its conditional energy weighting at lines 404–454 gives weights of 13926 for `00` and 13106 for `11` in Q14 in both top bands of all four words. The resulting weighted energies differ, but the allocation procedure beginning at line 518 allocates zero bits to those two bands under either input and returns the same complete 17-band allocation. The secondary allocation routine receives the flags at `lib_dec/tcq_core_dec.c:176–177` and selects the same two indices in either case. All 17 decoded pulse counts and all 160 quantized spectral coefficients then compare equal. The receiver does use both flags. This result establishes their effect on these four original words with the specified decoding history. [Official TS 26.443 reference source](https://www.etsi.org/deliver/etsi_ts/126400_126499/126443/19.00.00_60/ts_126443v190000p0.zip)

## Reproduce

Supply the two original `stv8c_13200_8kHz.COD` files in the cache layout from the parent comparison, the November 4, 2021 floating-point TS 26.443 C distribution, Python 3 and GCC. The checker pins both vector hashes and the three relevant decoder source files. It builds an observation-only decoder in a temporary directory, leaves the original sources untouched and compares the original fixed stream with four full-length streams, each containing one original floating-point replacement word.

```sh
python examples/receiver-control/reference-ambiguity/field-trace/check.py /path/to/vector-cache /path/to/c-code --check
```

Each run emits 441,600 signed 16-bit PCM samples at 8 kHz with standard delay compensation. Each matches the original floating decoder's PCM SHA-256 `f6448c4463b3e595082cae2659ca31fc28fa0468c63fb6c67e531081c7ae2fa6`. The checker compares complete integer arrays before hashing them as little-endian signed 32-bit values. Packed-word hashes cover the original 33 octets, including the mode. [Per-word output, weighted energies and trace digests](expected.json)
