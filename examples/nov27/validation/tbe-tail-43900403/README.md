# Can EVS field checks distinguish values at payload byte 30?

Two different inputs to the stock EVS encoder produced second-position
words that differ in exactly one bit of payload byte 30. The TCX20
example uses the same `FE` mode octet seen in the 43865914 handoff.
Both examples were found using 52 short, synthetic encoder runs at
13.2 kb/s. Each row below reproduces using just two of those runs.
No alternative bits were inserted into either encoder output.

| Native second-position words | Zero-based slot | Byte 30 in the two inputs' encoded words | Only differing bit of 264 (MSB first) | Other slots in the 60-frame group with equal 27-byte projections |
| --- | ---: | --- | ---: | ---: |
| SWB TCX20, mode FE | 25 | 59 / 5D | 253 | 12 / 59 |
| SWB GSC INACTIVE, mode 74 | 85 | 16 / 17 | 255 | 37 / 59 |

The byte values are hexadecimal. In each target slot the other **263
bits** agree, including all 27 octets available when the six late
payload octets are omitted. Any rule using only those 27 octets must
give the same answer to the two inputs and therefore cannot identify
the differing bit in both. Earlier and later frames from the two inputs
are distinguishable. These specimens leave open methods that use
other frames or broadcast data outside the word.
[Reproduce both native examples](../check_native_word_pair.py)

A further stock TCX20 example preserves both immediate neighbors. Change one input PCM sample of a 1 kHz tone by −4 or +4, then compare the two encoder outputs at the same second-position slot, 97. The two 264-bit words differ only at bit 255, giving payload octet 30 values `1C` and `1D`. Slots 96 and 98 match in full. Slots 95 and 99 distinguish the two streams on directly available coordinates. Run the linked reproducer with `--case tcx-neighbors` and the path to the stock encoder via `--encoder`. [Expected words, neighboring frames and hashes](../native-tcx-neighbors.json)

## Testing a field that spans the hidden octet

For SWB GENERIC and VOICED ACELP with time-domain bandwidth extension
(TBE), EVS line spectral frequency indices span byte 30 and 13
neighboring bits that are directly received. The reference decoder
checks the mirror frequency and the reconstructed line spectral
frequencies against the upper limit. Testing the complete synthetic
parameter space triggered one or both checks in 72 of 2,097,152 cases.

| Values rejected out of 256 for byte 30 | Number of 13-bit neighbor patterns |
| ---: | ---: |
| 0 | 8,152 |
| 1 | 28 |
| 2 | 8 |
| 7 | 4 |

Even the most restrictive pattern admits 249 octet values. Every one
of the eight individual bits can therefore be either 0 or 1. On 569
eligible stock words from three encoder runs (synthetic, speech and
music), all had a neighbor pattern that admits all 256.
[Reference-code replay](../check_tbe_tail_context.py)

## Held-out radio result

We froze the check and chose **43900403** using transport coordinates.
A fresh demodulation of the Edogawa IQ reproduced the stored
CRC-verified DUs. All 60 target slots arrived. None used the TBE modes
covered by this check. All four positions supplied zero complete clear
words. The 10,560 directly transmitted bits are available and the
other 5,280 bits remain unscored.
[Protocol](protocol.md) · [Slot-by-slot decisions](result.json)

Across all 73 selected complete groups, **275 of 4,380 words** used
one of the applicable TBE modes (68, 71, 67 and 69 words at positions
1 through 4). Every one of the 275 had a context admitting all
256 values. This held for retrospective checks on 1,959 text-supported
first-position words from the November 27 13:17 capture and 666 from
November 26 as well. The selected counter is included in the 73-group
count. [Per-counter coverage](coverage.csv)

To reproduce the on-air check, supply an unpacked floating-point EVS
reference source tree and use the three DUs in this directory. The tool
checks the source hashes before building the reference calculation.
[ETSI reference source](https://www.etsi.org/deliver/etsi_ts/126400_126499/126443/19.00.00_60/ts_126443v190000p0.zip)

```sh
case_dir=examples/nov27/validation/tbe-tail-43900403
python scripts/project_evs_group.py "$case_dir/data_units.npz" --counter 43900403 > projection.json
python examples/nov27/validation/check_tbe_tail_context.py --source /path/to/c-code --projection projection.json
python examples/nov27/validation/check_native_word_pair.py --case tcx
python examples/nov27/validation/check_native_word_pair.py --case gsc
```
