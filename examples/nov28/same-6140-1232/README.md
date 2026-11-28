# Two independent 6140 kHz recordings at 12:32 UTC

On November 28 the Edogawa and Yokohama receivers both captured counter **43945659**, the first complete three-phase group in Edogawa's native receiver output. We fixed the selection before decoding either recording. The counter was absent from the inventory of 14,811 previous counters. Both sites received the same 12 CRC-valid physical packets and three byte-identical data units for the group. [Selection and receiver settings](protocol.json) · [Comparison across both recordings](comparison.json)

| What can be checked for this counter | Result |
|---|---:|
| EVS slots received in full at both sites | 60/60 |
| Directly observable word bits agreeing across sites | 10,560/10,560 |
| Carried bit coordinates with unresolved clear values | 5,280 |
| Independently verified complete clear EVS words | 0/60 |

Each of the four positions contributed 15 slots and 2,640 directly observable bits under the frozen receiver's rules. Across the entire window the sites shared 17 complete groups. All 277 shared packet coordinates and all 65 shared complete data units matched byte for byte. [Primary slot detail](primary-slots.json) · [Edogawa native receipt](edogawa-native.json) · [Yokohama native receipt](yokohama-native.json)

Neither prespecified mode-based field rule applied at the primary counter. At seven later counters, the Edogawa mode byte predicted the high nibble of payload octet 4 for 184 INACTIVE slots. Every corresponding nibble received at Yokohama equalled `C`. Positions 1 through 4 supplied 47, 46, 45 and 46 such comparisons. All 184 comparisons had an independent receiver observation. No slot met the AUDIO rule. These fields travel in the clear. [Every comparison](field-rows.csv) · [Counts including ineligible and missing cases](fields.json)

## Replay

Each recording preserves 4,320,000 complex samples as two lossless signed 16-bit channels at 48 kHz. The station timestamps show 89.273 seconds in common. Five Yokohama packets and three Edogawa packets lacked a station timestamp. Both files replayed to the original byte-for-byte MSC outputs using receiver revision `41b4e2d`. [Edogawa IQ](iq/edogawa-6140khz-iq48.flac) · [Yokohama IQ](iq/yokohama-6140khz-iq48.flac) · [Station clocks and sample bounds](sealed-sources.json) · [Lossless distribution hashes](iq/verification.json) · [MSC replay hashes](iq/replay.json)

To reproduce the field results and slot counts from the two published transport snapshots, run from the repository root.

```sh
python examples/nov28/same-6140-1232/check.py --slots --out /tmp/same6140-replay.json
```
