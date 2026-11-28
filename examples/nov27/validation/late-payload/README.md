# What one EVS word tells us about the six unresolved payload octets

For each of the six unresolved offsets, two genuine stock EVS outputs can have identical values in the other 32 octets and different values at that offset. The table gives one pair per offset. Each pair comes from a separate comparison. A rule using only the rest of that word must return the same answer for both members of its pair. Specific encoding modes can still constrain individual bits, as the wideband GSC example below shows. Payload offsets start after the mode octet.

| Payload offset | Two observed values (hex) | Stock mode | Position in the synthetic four-word cycle |
| ---: | --- | --- | --- |
| 15 | `F7` / `FD` | TCX20 | P3 |
| 18 | `BF` / `6F` | SWB voiced ACELP | P2 |
| 21 | `39` / `37` | SWB voiced ACELP | P2 |
| 24 | `BC` / `BD` | SWB transition ACELP | P2 |
| 27 | `D2` / `D3` | SWB voiced ACELP | P2 |
| 30 | `1C` / `1D` | TCX20 | P2 |

The longer p15 example shows where other observations can help. The target words agree at all 22 directly transmitted octets. Across the first 60 frames of the two original streams, just six slots agree at those octets. Within P3 only the target itself agrees. The other 14 P3 slots distinguish these particular streams. The shorter p18 and p21 inputs each contain three frames. These experiments leave open whether the entire broadcast group can resolve a target word. [New p15, p18 and p21 inputs and replay](early-examples/README.md) · [p24 and p27 stock words](sender-pairs.json) · [p30 stock words and adjacent context](../native-tcx-neighbors.json)

Context has a different outcome in an earlier p24 GSC control. Two 240-word stock streams differed at one bit in frame 205, giving p24 values `67` and `77`. All 239 surrounding words were identical. Even the entire 4.8-second codec sequence with that bit withheld admits both originals. The test used the EVS sender only. It leaves the additional information carried by the broadcast transport untested. [Two original GSC streams and reproduction](../swb-gsc/README.md#two-different-stock-outputs-with-the-same-surrounding-bits)

## What can be scored on the recorded signals

The archived P1 exports for November 27 counters 43865914, 43869343 and 43876554 each contain 15 complete words. We checked their alignment against the received mode and the 21 directly readable payload octets in each slot. All 7,920 comparable bits agreed across the 45 words. The frozen projector made zero predictions at the six later offsets, including the 270 P1 octets for which an archived answer was available. Each P2, P3 and P4 slot in these three reference excerpts was an explicit erasure. Agreement on the readable bits establishes alignment. The accuracy of the six unpredicted octets remains unmeasured. [Capture clocks and export checksums](../../../nov28/airspy-150-gap/nov27-p1-control.sources.json) · [Projection and comparison commands](../../../nov28/bit-evidence/README.md#comparing-a-text-supported-handoff)

## Different source inputs can give identical visible bytes

Each row comes from two synthetic PCM inputs passed separately through the unmodified 13.2 kb/s sender. Each comparison targets the second position in a four-frame cycle. Only the listed bit differs anywhere in the current word. [Original words, input and output hashes](sender-pairs.json)

| Mode and zero-based slot | Payload byte and alternatives | Only differing bit | Identical complete words immediately before / after |
|---|---|---:|---:|
| SWB transition ACELP, slot 1 | 24, `BC` or `BD` | 207 | 1 / 0 |
| SWB voiced ACELP, slot 1 | 27, `D2` or `D3` | 231 | 1 / 0 |
| SWB TCX20, slot 9 | 27, `FF` or `FB` | 229 | 9 / 2 |

In the TCX20 example, changing a single PCM sample by one unit produced the difference. Any decision based only on the other 263 bits and the preceding frame must give the same answer for both members of each pair. Evidence shared across the 15 words at one broadcast position remains a separate question. [Stock encoder reproducer](sender_pairs.py)

## Two predictable bits in wideband GSC

In nine synthetic wideband GSC words, the prefix identified the final bucket of a pulse-vector codebook with 142,544 entries. Only residual indices 0–207 fit in that bucket. In this layout the residual occupies ten bits starting at physical bit 230, so its two high bits, the low pair of payload byte 27, must be `00`. All nine original words agreed. Four were second-position words. The native decoder started cold for each word and rejected each of the three alternative pairs, giving 27 actual rejections. The test supplied no bit of payload byte 24 in these controls. [Reference-codec check, stimuli and field geometry](gsc-control/README.md)

For a historical comparison, we selected all wideband GSC P1 words among 32,295 November 25–26 slots with repeated-text support and 10,530 March slots with fixed idle-text support. Two qualified, both at November 25 counter **43703439**, slots 0 and 4. We supplied only their established 16-byte prefixes. At slot 0 the index at bit 230 used bucket 64. At slot 4 the bounded reader established other index locations. Neither met the bucket-139 condition. We left the stored answers sealed. The archived words lack a continuous clear predecessor history, so this comparison used a cold decoder. [Prefixes, addresses and decisions](gsc-control/archived-prefixes.json)

## Three minutes of fresh 6140 kHz IQ

The separate frozen on-air test checked an ordinary super-wideband bandwidth-extension (BWE) class near payload byte 27. In the reference encoder a high speech-class bit suppresses the transient extension class. The transition tag and reserved padding determine where the two extension-class bits are carried. In 22 locally encoded SWB transition words using BWE, four had the high speech-class bit. In each of these four the extension class straddled bytes 27 and 28. Its directly carried low bit already excluded the transient class, leaving both possibilities for the bit in byte 27. [Stock sender field measurements](bwe-sender-control.json) · [Frozen test and scope](protocol.md)

At 23:44:41 UTC on November 27 we recorded 180 seconds from 7L4IOU in Edogawa, Tokyo. The receiver accepted 294 CRC-valid data units from a recording containing 123 previously unseen counter IDs. There were **81 complete groups and 4,860 frame slots**. The 1,876 SWB GENERIC and 204 SWB TRANSITION words all selected the other extension. The frozen BWE check therefore abstained on all 4,860 slots. The capture also had 274 SWB GSC words and zero wideband GSC words of the kind in the nine sender controls. The two checks have different mode requirements. [Lossless IQ recording](7l4iou-6140-20261127T2344Z-iq48.flac) · [CRC-checked data units](edogawa-data-units.npz) · [Receiver receipt and hashes](live-receipt.json)

Primary counter **43907255** supplied 15 frames at each of positions 1–4. The direct projection provided 2,640 bits per position and left 1,320 unresolved per position. All 60 complete clear words remain erasures. A second Dream build reproduced the exact MSC dump and data units from the lossless IQ file. A static check found a stale reporting lookup in the original CLI. The one-line fix was hashed before demodulation and published before results were opened. The predictor stayed identical. [Original freeze](https://github.com/skgsara/kcbs-drm/commit/d53f5402d99f87c0893e5afca02b08af445d9f22) · [CLI correction](https://github.com/skgsara/kcbs-drm/commit/b0f51235e2a65b48948714b55347254b107876e3)

## Reproduce

From the repository root, use the stock floating-point EVS encoder for the pairs. The GSC controls require the November 4, 2021 TS 26.443 source tree and GCC.

```sh
case_dir=examples/nov27/validation/late-payload
python "$case_dir/sender_pairs.py" --encoder /path/to/EVS_cod --out /tmp/kcbs-word-pairs.json
cmp /tmp/kcbs-word-pairs.json "$case_dir/sender-pairs.json"
python "$case_dir/gsc-control/check.py" --source /path/to/c-code --encoder /path/to/EVS_cod
python "$case_dir/gsc-control/archived.py" /path/to/c-code
```

Use the project's finite-file Dream build for the RF stage. The FLAC has two IQ channels and decodes to the original 8,640,000 sample pairs. Use fresh output directories.

```sh
python scripts/demod_iq_window.py "$case_dir/7l4iou-6140-20261127T2344Z-iq48.flac" /tmp/kcbs-late-rf --seconds 180 --reception-profile wiener --mlc-iterations 1
python scripts/salvage_msc_packets.py /tmp/kcbs-late-rf/msc.bin --transport-only --out /tmp/kcbs-late-transport
cmp /tmp/kcbs-late-transport/data_units.npz "$case_dir/edogawa-data-units.npz"
python "$case_dir/bwe.py" "$case_dir/edogawa-data-units.npz"
python scripts/project_evs_group.py "$case_dir/edogawa-data-units.npz" --counter 43907255 --format tsv
```
