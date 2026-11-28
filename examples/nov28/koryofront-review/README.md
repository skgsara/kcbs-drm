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

## Which music-demo words can the paired recordings verify?

The 06:17 UTC packet companion covers **22 complete on-air groups**, counters 43854888–43854909. Both Airspy recordings reproduced the same 264 physical packets in these groups. The released music reconstruction supplies words in 990 of the 1,320 slots. Every supplied word agrees with its packet at the mode octet and the 21 directly transmitted payload octets, for **174,240 matching bits and zero disagreements**. The remaining 330 slots are erasures in the reconstruction. [Dual-frequency IQ replay](../four-frequency/nov27-digital.json) · [Group-by-group comparison](music-overlap.json)

| Frame position | Words supplied in the reconstruction | Erasures | Directly transmitted bits checked |
|---|---:|---:|---:|
| 1 | 330 text-supported | 0 | 58,080 |
| 2 | 240 inferred | 90 | 42,240 |
| 3 | 225 inferred | 105 | 39,600 |
| 4 | 195 inferred | 135 | 34,320 |

Twelve of the 22 overlapping groups have all 60 words supplied. The earliest, **43854890**, starts at 5.20 seconds in the released stream and is the opening group of the 12-second music excerpt. All 10,560 directly carried bits agree. The comparison would detect a change to any one of those bits. The other 5,280 bit coordinates fall outside this check. The slot ledger credits 15 first-position words to text evidence and the other 45 to audio-assisted inference. Neither recording provides independent clear labels for those 45 words. This is a historical playback comparison. [Slot ledger](../../nov27/frames.csv) · [Published excerpt and stream hashes](../../nov27/replay.json)

To reproduce the comparison from the repository root, extract the [06:17 UTC capture companions](https://github.com/skgsara/kcbs-drm/releases/download/samples-2026-11-28/KCBS2_20261127T061722Z_companions.zip) and run the following commands, substituting the path of the extracted packet file.

```sh
d=examples/nov28/koryofront-review
python "$d/music_overlap.py" /path/to/KCBS2_CRC_verified.msc.bin > /tmp/music-overlap.json
cmp /tmp/music-overlap.json "$d/music-overlap.json"
```

### Does identical EVS input reproduce identical audio for an isolated group?

We fed the stock 16 kHz EVS decoder the exact same target words three ways. First we decoded from the start of the published stream to establish the reference PCM. Then we started at the target counter, or 60 slots earlier. The reference replay reproduced the published SHA-256 for all 480,000 PCM samples. All three trials used the same target G.192 bytes, including their original order. [Decoder build and release](../../../docs/november-2026.md) · [Replay script](music_state.py)

| Start of playback | Groups with any differing sample | Differing PCM samples out of 230,400 | Affected 20 ms slots out of 720 |
|---|---:|---:|---:|
| At the first target word | 12 of 12 | 31,653 | 592 |
| One group earlier | 9 of 12 | 10,420 | 415 |

For counter 43854890, starting at the first word changed 2,083 of 19,200 samples. Including the preceding group reproduced this target exactly. In the nine groups that still differed after one preceding group, every remaining sample difference was at most five signed 16-bit PCM counts. No listening test was performed. For a bit-exact playback comparison, start both decoders from the same state and feed them the same preceding slots, including erasures. A sample mismatch with different decoder histories can occur even with identical target words. [First group](music-state.json) · [All 12 groups](music-state-overlap.json)

```sh
d=examples/nov28/koryofront-review
python "$d/music_state.py" --decoder work/evs_gcc_independent/EVS_dec --overlap "$d/music-overlap.json" > /tmp/music-state-overlap.json
```

The report includes the executable digest. When comparing builds, check that digest and the full-stream PCM digest before comparing the sample counts.
