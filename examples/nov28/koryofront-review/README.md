# KoryoFront receiver update, November 28

KoryoFront reports first-position audio in **817 of 884 groups** on the November 25 KST listening timeline. The preceding parser reached 717. The new receiver can use an individual received phase, which contributes five first-position words even if the other two phases are missing. Over the longer 04:48 and 04:57 recordings together, the authors report **1,114 → 1,268** text prefixes. We verified the starting count in the supplied archive. The final 817-group and 1,268-prefix counts are the authors' results. Their published procedure uses supplied prefixes and a reference directory containing previously decoded bulletins and titles. [Upstream results and inputs](https://github.com/KoryoFront/kcbs2-drm-decode/blob/2fc071b76e42f0627f2a406e5c2d1151576802b9/README.md#L115-L175)

The upstream renderer substitutes six payload bytes in each second-position word. It uses concealment or replay for positions three and four. Its default setting also bridges runs of up to four missing groups. The reported 7.2-second silent stretch describes the listening copy. A different statistic, the number of groups without supported first-position audio, is 67. The November 27 music example predates this update. Its slot ledger, both archived EVS streams and reference-comparison JSON match skgsara's files byte for byte. The ledger counts 355 text-supported slots, 795 acoustically inferred slots and 350 erasures. [Upstream renderer](https://github.com/KoryoFront/kcbs2-drm-decode/blob/2fc071b76e42f0627f2a406e5c2d1151576802b9/scripts/render_supported_nonidle.py#L41-L72) · [Grouping of playback runs](https://github.com/KoryoFront/kcbs2-drm-decode/blob/2fc071b76e42f0627f2a406e5c2d1151576802b9/scripts/kcbs_decode_fast.py#L221-L225) · [Original slot ledger](../../nov27/frames.csv)

## A complete data unit in the reported silent stretch

Counter **43680333** identifies itself in a complete phase-zero data unit at the start of the reported silent interval (43680333–43680338). In the 04:57 dump, its zero-based record index is **1277** and its four-byte length header begins at file offset **934764**. The four physical packet headers are `80 01 02 43`. Their transmitted and recomputed CRCs agree at `3A6F CCD5 8827 2E15`, and the 716-byte unit passes its own CRC, `9CBB`. The supplied prefix archive has no row for this counter. This receipt establishes that reception succeeded for at least one phase during the gap. [Original MSC dump](../../../contrib/kcbsdrm/reference/sf_2026-11-25_0457KST_3205_hik.bin) · [Upstream description of the gap](https://github.com/KoryoFront/kcbs2-drm-decode/blob/2fc071b76e42f0627f2a406e5c2d1151576802b9/README.md#L117-L123)

## Checking the new counter assignments on two independent recordings

We applied the upstream counter-assignment rules retrospectively to the November 28 **12:32 UTC, 6140 kHz** MSC dumps. Each receiver's original packet snapshot was already published. We compared every proposed addition with the other site's original, independently assigned complete units. A match requires all 716 bytes and a unique coordinate at the other site. [Both original receipts and recordings](../same-6140-1232/README.md) · [Upstream coordinate assignment](https://github.com/KoryoFront/kcbs2-drm-decode/blob/2fc071b76e42f0627f2a406e5c2d1151576802b9/scripts/salvage_msc_packets.py#L79-L98)

| Site | Originally assigned complete units | With upstream rules | Additions fully matched at other site | Complete three-phase groups before and after |
|---|---:|---:|---:|---:|
| Edogawa | 67 | 82 | 15 of 15 | 17 → 17 |
| Yokohama | 200 | 206 | 0 of 6 | 65 → 65 |

All 15 Edogawa additions can also be located by comparing each CRC-valid native record directly with Yokohama's original snapshot. For example, Edogawa record 24 matches Yokohama counter 43945660, phase 1. Of the six Yokohama additions, one has three matching packets at Edogawa and five have no matching packet available there.

The phase-one and phase-two units carry no group counter of their own. In a controlled file where group 101 was repeated and group 102 was missing, the distance between the outer anchors stayed exactly as expected. The upstream rule assigned two intact units from 101 to 102. Both still passed CRC. This is why our cross-site check compares the bytes at an independently assigned coordinate.

Run `python examples/nov28/koryofront-review/check.py` from the repository root to list the November 25 phase-zero receipt and the two independent file comparisons, with raw row numbers and SHA-256 digests. This check reads the original MSC and packet files directly. The 12:32 comparison adds evidence about where received units belong. The prospective blind-decoding scores continue to use their registered inputs and counter rules.

## A text repeat that changes phase

The November 26 10:08 KST text archive provides a control for comparing record starts across phases. Its 299 records marked both `ok` and `complete` have unique block-aligned starts. Divide the archive's `pos` by eight UTF-16 units per block to obtain the block index. For each spacing below, we paired observed starts and compared the published text, sequence number and final-record flag. The record status comes from the contributor's archive. [Original record positions and text](../../../contrib/kcbsdrm/reference/items_2026-11-26_1008KST_merged.json)

| Start-to-start spacing in data units | Pairs with both starts recorded | Pairs matching all three fields |
|---:|---:|---:|
| 797 | 21 | 0 |
| 798 | 32 | 0 |
| 878 | 178 | 178 |

One example runs from counter **43767451, phase 2** to **43767744, phase 1**. The start distance is `3 × (43767744 − 43767451) + (1 − 2) = 878` data units. The 178 matching pairs cover all three phase transitions, with 58 from 0 to 2, 57 from 1 to 0 and 63 from 2 to 1. A 797-unit interval would produce the same phase transitions. A separate November 27 recording has a measured 798-unit interval and preserves phase. Each comparison applies to its own recording. [November 27 record comparison](../../nov27/validation/tcx-zero-pair/43865914-review.md#two-observations-available-directly-from-the-signal)
