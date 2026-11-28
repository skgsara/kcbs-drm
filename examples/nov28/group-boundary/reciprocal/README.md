# A four-bit forecast across a damaged RF packet

Across the 119 counters shared by the Edogawa 6140 kHz and member 3205 kHz receivers, five first-position words had an eligible codec field in a packet that failed the 6140 reception checks. The 6140 mode octet remained available for all five. From that mode, the published empirical SWB GSC INACTIVE rule predicted the high nibble `C` of payload octet 4. Independent CRC-accepted 3205 packets carried `C` in all five words, giving **20/20 individually predicted bits**. The accompanying stock GSC range check allowed low nibbles 0–10 and excluded 11–15. All five low nibbles fell in range. [Complete ledger](ledger.json) · [Published field rules](../../../../scripts/evs_gsc_fields.py) · [Stock GSC range](../../../../scripts/evs_intra_word.py)

| Counter | Slot (0–59) | 6140 mode | Rejected 6140 target octet | Accepted 3205 target octet |
|---|---:|---:|---:|---:|
| 43908167 | 56 | 74 | C1 | C1 |
| 43908169 | 12 | 76 | C0 | C0 |
| 43908169 | 16 | 76 | C0 | C0 |
| 43908181 | 32 | 76 | 27 | C3 |
| 43908181 | 36 | 76 | C1 | C1 |

The first row was the preselected primary. The previously examined RF recordings included 7,140 chronological slots, 1,785 at each position. Of 3,547 eligible direct-field events on 6140, 3,537 already had accepted 6140 target bytes. The other ten events were the two nibble checks on each of the five words above. P2, P3 and P4 had zero eligible checks with a missing target. Coordinates and domains were selected from 6140 alone and hashed before the reciprocal pass opened 3205 target bytes. Both archives and their physical overlap had already been examined. [Fixed procedure](protocol.md) · [Original 3205-to-6140 audit](../dual-rf.json)

The secondary case at **43908181, slot 32**, shows why the two receiver outputs matter. In Edogawa row 78, the accepted q0 mode was `76`. At phase 1, cycle 3, P1, the q2 hard decision at DU offset 404 was `27`. The q2 header was `07` and its transmitted CRC `DE0C` disagreed with the computed `4F0E`. Member row 764 carried the same mode and an intact q2 with header `02`, CRC `DE0C` and target `C3`. Three of the four predicted high bits differ in the failed 6140 byte. Both low nibbles, 7 and 3, satisfy the range check. The other four rejected 6140 octets happened to agree with the member. These results concern directly transmitted fields. They supply no hidden-bit labels or complete EVS words.

## Reproduce

With Python 3 and NumPy, run from the repository root.

```sh
python examples/nov28/group-boundary/reciprocal/check.py --out /tmp/reciprocal.json
cmp /tmp/reciprocal.json examples/nov28/group-boundary/reciprocal/ledger.json
```

The checker reads both existing [6140 packet receipts](../dual-6140.npz) and [3205 packet receipts](../dual-3205.npz). It checks CRCs, reconciles complete DUs against the published archives, and verifies the stored 6140-only prediction digest before opening the member targets. Native excerpts contain two chronological stretches per receiver, with seven then four original length-prefixed 728-byte records. Rows are zero-based. Edogawa contributes rows 35–41 and 77–80, and the member contributes 721–727 and 763–766. Phase-zero counter bytes and phase headers bind the target rows to the transmitted counters. The checker also substitutes the failed `27` for the received `C3` in a copy of the good q2, preserving its transmitted CRC. The computed CRC changes to `6B49`. To verify each byte of the excerpts against the original receiver outputs, provide `--edogawa-msc PATH` and `--member-msc PATH` (member MLC1 window 0). IQ and native dump SHA-256 values are in the ledger. [6140 native excerpts](6140.msc.bin) · [3205 native excerpts](3205.msc.bin) · [Original capture identities](../../member-3205-20min/cross-frequency.json)
