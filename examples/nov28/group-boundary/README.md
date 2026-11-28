# Checking EVS fields with two radio receivers

At counter **43908300**, the 3205 kHz receiver could read a frame's mode byte from one valid packet. The packet carrying the target field failed CRC. An existing receiver rule predicted the high nibble of the target byte would be `C`. A separate Edogawa reception on 6140 kHz supplied a CRC-valid byte `C1` at that location. Both receptions carried the same digital programme. [Original packets and reproducible four-bit check](four-bits/README.md)

The target is slot 8, phase 0, cycle 2, position 1. Mode `74` supports two different checks on payload octet 4. The empirical high-nibble rule singles out 12 and rejects the other 15 values. The low-nibble rule allows 0 through 10 and rejects 11 through 15. Its observed value of 1 satisfies that range. The first rule determined four bits in one field. The original rejected 3205 packet also happened to carry `C1` at this offset. Its damaged bits were elsewhere. Withholding every byte in that packet left both predictions unchanged. [Packet CRCs, byte differences and controls](four-bits/expected.json)

A separate two-site check measures what happens when three consecutive MSC callbacks are missing. Depending on where the loss occurred, the same counter jump leaves 20, 40 or all 60 slots correctly placed. [Received group boundaries and omission control](row-continuity/README.md)

## Coverage across the shared counters

The two recordings had 119 assigned counters in common, comprising 7,140 chronological frame slots. At 1,056,088 directly received bit coordinates the receivers agreed exactly. Among those, 56,408 lay outside data units received whole by both stations. The stock and empirical field checks below used predictions from the 3205 recording and scored only where the 6140 receiver had the target. Most of these fields were also received directly on 3205. The four bits described above were the only exact predictions checked using a target packet missing from the accepted 3205 input. [Full denominators, rule outcomes and capture hashes](dual-rf.json)

In the reciprocal check, five first-position words had an accepted 6140 mode and a rejected 6140 target packet. All five high nibbles predicted from the modes matched the independent 3205 reception. At counter 43908181, slot 32, the failed packet actually contained `27`. The intact packet on 3205 carried `C3`, confirming all four high bits even though three differed in the failed reception. The low-nibble rule allowed both 7 and 3. [Five checks and both native packet excerpts](reciprocal/README.md)

| Frame position | Direct bits received at both stations | Individually predicted and checked against 6140 | Conditional hidden-bit predictions with no reference |
| --- | ---: | ---: | ---: |
| 1 | 265,432 | 1,723 | 211 |
| 2 | 263,744 | 1,678 | 202 |
| 3 | 263,264 | 1,688 | 243 |
| 4 | 263,648 | 1,666 | 232 |

All 6,755 independently comparable predictions matched. All 888 conditional predictions on hidden coordinates still lack clear-bit labels. The counts apply to this previously studied reception. To repeat the comparison, run `python examples/nov28/group-boundary/check_dual_rf.py` from the repository root. The two snapshots contain original radio packets, including transmitted CRCs and native row numbers. [Comparison script](check_dual_rf.py) · [3205 packets](dual-3205.npz) · [6140 packets](dual-6140.npz)

## A transmitted flag at the group boundary

The checker takes the mode at the end of one counter and the upper six mode bits at the start of the next. For eligible HQ starts, it predicts word bit 6 from the preceding core. Its packet-input mode requires the two endpoint packets and preserves erasures at gaps. In the member recording 285 HQ starts were eligible. The independent 6140 receiver supplied the current target for only three of them, at 43908220, 43908221 and 43908275. All three predictions were zero and all matched. Always predicting zero therefore scores equally well on these three. Flipping the target gives 0/3, and shifting the predecessor by one counter gives 1/3. The sole predicted one in the member recording lacked an independent target. [Predictions, packet CRCs and replay instructions](paired-hq.json) · [Checker](../../../scripts/check_evs_group_boundary.py)

## A separate prospective 90-second capture

The Edogawa receiver delivered all 4,320,000 complex samples from **02:57:56 UTC on November 28** at 6140 kHz. The receiver settings and eligible fields were published before demodulation, followed by the input hash. The independently recorded member comparison above used older counters. [Frozen protocol](protocol.json) · [Field selection](scoring.md) · [Input seal](sealed-source.json) · [Lossless IQ](edogawa-0257-iq48.flac)

The frozen receiver saw 206 native data units. Of 824 physical packets, 96 passed header and CRC. Fourteen entire native data units passed their checks. Two complete units and three further packets could be assigned to a counter. The three assigned counters were absent from the 14,737-counter inventory. No counter had three complete phases, so the prospective test had **no eligible primary and no complete-group boundary score**. The four-iteration sensitivity pass assigned six more packets and two more partial counters, still with no complete group. [Frozen result](reception.json) · [CRC counts](native-crc.json) · [Second pass](second-pass.json)

Outside the primary test, the frozen run gave 20 complete wire slots each for 43916921 and 43916972, and 14 complete plus three partial wire slots for 43916933. The first and last counters each had 19 conditional hidden-bit expectations without a clear reference. None of the three yielded a complete clear EVS word. [Per-position evidence](partial-reception.json) · [Native rows](native-chronology.csv)

To reproduce the receiver's packet-level erasures from the frozen native output, run from the repository root.

```sh
case_dir=examples/nov28/group-boundary
out=work/edogawa-0257
python scripts/salvage_msc_packets.py "$case_dir/msc.bin" --transport-only --save-packets --out "$out"
python scripts/project_evs_group.py --packets "$out/packets.npz" --counter 43916933 --evidence
python scripts/check_evs_group_boundary.py --packets "$out/packets.npz"
```
