# Two newly CRC-valid data units from the 12:32 UTC pair

Combining equalized MSC cells from Edogawa and Yokohama before Dream's channel decoder recovered **two additional 716-byte data units** in the evaluation set. The comparison used only native row pairs already aligned by a unique, identical CRC-valid packet at both stations. Evaluation covered 73 such pairs; only two of the 292 packet coordinates lacked an accepted packet at both sites. These counts apply to this selected subset of the recordings. [Alignment evidence](../alignment/README.md) · [Frozen combining rule](../protocol.md)

| Evaluation, 73 row pairs | Accepted packets / 292 | Complete CRC-valid DUs / 73 |
|---|---:|---:|
| Edogawa hard decisions | 261 | 54 |
| Yokohama hard decisions | 284 | 68 |
| Pool intact packets from both sites | 290 | 71 |
| Aligned cell combination | 292 | 73 |
| Shift peer one cell backward or forward | 0 in each control | 0 in each control |
| Shift peer one native block backward or forward | 0 in each control | 0 in each control |

All 290 packets in the hard-decision pool matched the combined result byte for byte. Calibration covered 55 pairs, the guard interval covered seven, and both cohorts already had all DUs available through packet pooling. In calibration, each wrong-block control still returned one whole DU with all its checksums valid. Its four packets matched the *displaced* Yokohama row and disagreed with the intended row. Checksums alone cannot assign an absolute time or counter. [All cohorts and controls](metrics.json)

| Native rows, Edogawa / Yokohama | q0 CRC calculated from original decisions, Edogawa / Yokohama | q0 CRC transmitted by both, also reproduced by the combined q0 | DU CRC |
|---|---|---|---|
| 106 / 109 | `20EE` / `B526` | `3AEF` | `4DE3` |
| 117 / 120 | `F442` / `93F9` | `EE87` | `085A` |

Each new q0 carries the expected packet header and passes its own transmitted CRC. The other three packets match accepted originals, including the independently received two-byte DU checksum in q3. The compact proof uses native row indices and treats all service data as opaque. [Wire fingerprints](proof.json) · [Four original wire rows](original-witnesses.msc.bin) · [Two combined wire rows](recovered.msc.bin)

## Check the compact proof

With Python 3, run from the repository root. The command checks the four source excerpts against the complete original station dumps, validates the packet headers and CRCs, assembles the DUs, and compares the bytes and checksums with the fingerprints. All record indices are zero-based.

```sh
case_dir=examples/nov28/same-6140-1232
fusion="$case_dir/diversity/fusion"
python "$fusion/proof.py" --msc "$case_dir/edogawa-msc.bin" "$case_dir/yokohama-msc.bin"
```

The two combined wire records each consist of a four-byte little-endian length and 728 bytes. Together their SHA-256 is `fdee4ceac212d4ea1a3ea180ced9ebc89dfe80c75a1ce0c37b0a39582ddc9117`.

## Regenerate from both IQ recordings

Build Dream and replay both FLAC recordings using the sibling observer. The observer writes `cells.bin` and `msc.bin` under each station name. The fusion driver links the stock MSC channel decoder from the same configured Dream build. The cell and decoder input files use little-endian int32 and IEEE binary64; the native harness checks the host layout. For the in-tree Linux build, use the commands below. For a separate build directory, set `build` to the directory containing the generated Makefile and set `DREAM_SOURCE` to the matching Dream source checkout. [Observer build and replay](../observer/README.md) · [Pinned Dream MLC source](https://github.com/mmjee/dream-patched/blob/895658c567d2fd47d6006065e75abf0c3157783f/src/mlc/MLC.cpp)

```sh
fusion="$PWD/examples/nov28/same-6140-1232/diversity/fusion"
build="$PWD/build/dream-src"
work=$(mktemp -d)
make -C "$build" -f "$fusion/harness.mk" fusion-decoder DREAM_SOURCE="$build" OUTDIR="$work"
python "$fusion/combine.py" --observer /path/to/replayed --decoder "$work/decoder" --out "$work/result"
for name in metrics.json proof.json original-witnesses.msc.bin recovered.msc.bin; do
    cmp "$work/result/$name" "$fusion/$name" || exit 1
done
```

Before combining, the driver verifies that every original native wire row has one exact, chronological observer match at its own site. It also re-decodes the original cell vectors with the stand-alone decoder and checks all 5,826 output bits per block. All 218 Edogawa blocks and 220 Yokohama blocks passed individually.

For matching coding geometry, the frozen rule weights each receiver's equalized cell by the square of its channel magnitude divided by the mean squared magnitude for that block, then scales by Dream's receiver SNR in linear units. The stock decoder receives the weighted complex average and the square root of the summed weights. This approximation was tested on this same-frequency pair and this independently aligned subset. [Fusion implementation](combine.py) · [Decoder entry point](decoder.cpp)
