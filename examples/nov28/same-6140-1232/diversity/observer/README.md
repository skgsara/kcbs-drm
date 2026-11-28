# Observing the 12:32 UTC MSC decoder input

The patch records one receiver's equalized MSC cells after symbol deinterleaving and before the multilevel decoder calculates its metrics. For each block it also records the original hard decisions after energy dispersal. On the two published recordings, the first 728 bytes of **every** block match the corresponding original service row in order. All 218 Edogawa rows and 220 Yokohama rows have distinct bodies within each station. The other two decoded bits fall outside the service bytes. [Expected counts and hashes](expected.json) · [Original station recordings and hard outputs](../../README.md)

## Build and replay

Use a dedicated Linux checkout of this repository. The existing build recipe fetches the pinned Dream revision and installs its dependencies. The observer also uses Python 3, NumPy and SoundFile with FLAC support. From the repository root, run the following commands. Use a new output directory each time. [Dream build instructions](../../../../../build/README.md)

```sh
bash build/build.sh
observer="$PWD/examples/nov28/same-6140-1232/diversity/observer"
git -C build/dream-src apply --check "$observer/dream-msc-observer.patch"
git -C build/dream-src apply "$observer/dream-msc-observer.patch"
make -C build/dream-src -j2
python "$observer/replay.py" run --dream build/dream-src/dream --out /tmp/drm-1232-observations
```

The replay checks each FLAC and decoded PCM digest, uses the published cold Wiener/MLC1 configuration, and requires byte equality with both complete native MSC files. It then reads each newly recorded trace and checks every block against the original row. The two generated traces occupy about 25 MB together. Each station directory contains `cells.bin`, `msc.bin`, the receiver log and INI. The output root contains `verification.json`.

For an existing trace, run the check separately. Adding `--require-trace-hash` also requires all floating-point bytes and receiver-state snapshots to match the development build. Compiler, math library or FFT differences can change the floating-point trace. The full hard-output and ordered per-row checks run on every replay.

```sh
python "$observer/replay.py" check /tmp/drm-1232-observations/edogawa/cells.bin \
  examples/nov28/same-6140-1232/edogawa-msc.bin --require-trace-hash
```

## MSCObs1 binary format

The file starts with `MSCObs1` and one LF byte. Each block starts with 28 signed little-endian 32-bit integers. The indices below are zero-based.

| Header indices | Contents |
|---|---|
| 0–2 | Local block index, number of MSC cells, decoded output bits |
| 3–5 | Dream robustness mode, spectrum occupancy, MSC coding scheme |
| 6–9 | Protection levels A, B and hierarchical, then symbol interleaver setting |
| 10–12 | Receiver frame ID snapshot, MLC iteration setting, coding levels |
| 13–17 | Decoder partition sizes N0, N1, L0, L1, L2 |
| 18–25 | Part A and B lengths in bytes for streams 0, 1, 2 and 3 |
| 26–27 | Usable MSC cells per frame, nominal receiver SNR in millidecibels |

The header is followed by one little-endian IEEE binary64 triple per cell in the decoder's input order. The three numbers hold the real and imaginary parts of `CEquSig.cSig` and the supplied reliability `CEquSig.rChan`. The final `ceil(output_bits/8)` bytes contain the original output bits in MSB-first order, with zero low padding in the last byte. Both recordings have 2,337 cells and 5,826 output bits per block. The frame ID and nominal SNR report the receiver's state at invocation. The local block index and modulo-three frame ID alone cannot establish a cross-site timestamp. [Dream MLC source](https://github.com/mmjee/dream-patched/blob/895658c567d2fd47d6006065e75abf0c3157783f/src/mlc/MLC.cpp)
