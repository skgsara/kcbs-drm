# Can one CRC syndrome correct a damaged DRM packet?

Two of ten one-bit corrections reproduced the full 182-byte packet at an independent receiver. The other eight each added one wrong bit. This retrospective check covered 237 damaged packets across two same-frequency receiver pairs. In each comparison, the source packet failed its CRC, a separate intact packet identified the peer row, and the target packet at the peer passed its original header and CRC checks. [Per-packet outcomes and hashes](historical.json)

| Transmission | Source → comparison receiver | Matched rows | Failed source packets with a valid peer | Proposed | Exact | Wrong |
|---|---|---:|---:|---:|---:|---:|
| Nov 28 12:32 UTC, 6140 kHz | Edogawa → Yokohama | 135 | 88 | 4 | 0 | 4 |
| Same transmission | Yokohama → Edogawa | 135 | 6 | 0 | 0 | 0 |
| Nov 27 21:26 UTC, 3205 kHz | Yokohama → Edogawa | 118 | 110 | 5 | 2 | 3 |
| Same transmission | Edogawa → Yokohama | 118 | 33 | 1 | 0 | 1 |

The proposal uses only the failed source packet. A matching one-bit syndrome locates a proposed change, and the corrected header must match the packet ordinal. The peer verifies the complete wire after that decision. The earlier rule also required exactly one failed packet in the source row and a passing data-unit CRC after correction. Among these peer-checkable packets it retained two incorrect proposals at 12:32 and neither correct proposal at 21:26. The packet and data-unit CRC use the same polynomial. [Earlier rule and synthetic counterexample](../../nov28/packet-bit-repair/README.md)

## The two exact wires

The following offsets are zero-based, and bit zero is the most significant bit. Each independent Edogawa comparison row retained all four original packets and passed the 716-byte data-unit CRC. [21:26 original files and provenance](../../nov28/packet-bit-repair/peer-2126/protocol.md)

| Yokohama row → Edogawa row | Corrected packet and wire bit | Location in the broadcast | What the peer establishes |
|---|---|---|---|
| 191 → 206 | q0, bit 533 | Phase 2, slot 41, position 2. DU octet 65, EVS payload octet 25, word bit 213. | The source carried `BC` at this directly transmitted octet. Flipping the proposed bit restored the peer's `B8`. Source q2 provided the independent row match. |
| 255 → 270 | q1, bit 306 | Counter 43900433, phase 0, slot 6, position 3. DU octet 216, payload octet 12, word bit 106. | This position carries a masked octet. The peer confirms the transmitted wire bit. Its clear value remains unknown. Source q2 and q3 both matched the peer row. |

The first row sits outside a fully received phase-0/1/2 triple at Edogawa. Its intact phase header establishes phase 2. The source itself retained one complete packet in row 191 and two in row 255.

The 237 count covers the two same-frequency pairs above. A separate historical three-pair census additionally counted 129 opportunities on the November 28 00:02 cross-frequency pair, nine with the member's 3205 kHz recording as source and 120 in reverse. That wider denominator is 366. The June 16 full dumps are also recorded in the evidence file. Their repeated row sequences gave 331 candidate pairs with crossed chronological order, so the strict alignment admitted zero comparisons there. [November cross-frequency recording](../../nov28/member-3205-20min/README.md) · [June receiver files](../../jun16/transport/README.md)

## Reproduce the two same-frequency comparisons

Run from the repository root. Each JSON output includes the original file hashes, alignment counts, both receiver directions and every peer-checkable proposal. The script leaves the native streams untouched.

```sh
study=examples/receiver-control/packet-repair
a=examples/nov28/same-6140-1232
b=examples/nov28/packet-bit-repair/peer-2126
python "$study/paired_syndromes.py" "$a/edogawa-msc.bin" "$a/yokohama-msc.bin" > /tmp/repair-1232.json
python "$study/paired_syndromes.py" "$b/primary.msc.bin" "$b/witness.msc.bin" > /tmp/repair-2126.json
```
