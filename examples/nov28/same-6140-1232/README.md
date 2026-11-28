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

## Can a wrong slot pass the same check?

After scoring the recording, we shifted the Yokohama target along the slot clock while keeping each Edogawa observation fixed. One slot is 20 ms and 60 slots are 1.2 seconds. Every tested target was received at both stations, including when the shift crossed a counter boundary.

| Yokohama shift | Matching INACTIVE high nibble | Matching mode and 21 direct payload octets on those same slots | Matching mode and 21 direct payload octets at primary |
|---:|---:|---:|---:|
| −60 slots | 49/184 | 0/184 | 0/60 |
| −1 slot | 179/184 | 0/184 | 0/60 |
| 0 | 184/184 | 184/184 | 60/60 |
| +1 slot | 180/184 | 0/184 | 0/60 |
| +60 slots | 68/184 | 0/184 | 0/60 |

With a 20 ms error, the high nibble alone still agreed in at least 97% of these slots. Comparing all 22 directly observable octets rejected every tested wrong offset on both sets of slots. This tests the placement of an EVS word against the recording. The masked octets have no clear labels in this comparison. [Replay the slot shifts](check.py)

## Wire bytes and station timing

The native MSC dumps retain the packet headers and transmitted CRCs that were stripped from the packet snapshots. Across the 17 complete groups received in order at both sites, all 204 wire packets and all 51 data units matched byte for byte. For primary counter 43945659, the three on-air DU CRCs were `7A4D`, `6B82` and `8325` in phase order. [Edogawa MSC dump](edogawa-msc.bin) · [Yokohama MSC dump](yokohama-msc.bin) · [Wire verifier](native_groups.py)

All 17 shared groups appeared three native output rows later in Yokohama's file. To check the station clocks separately, we compared the received modulation in eight 0.4-second windows spaced ten seconds apart. The strongest matches placed the signal 5.3–5.6 ms earlier on Yokohama's reported clock. In all eight windows the correlation exceeded the control displaced by 1.2 seconds. This measures the combined difference in receiver timing and propagation for these two recordings. [Waveform and counter timing check](verify_timing.py)

## Replay

Each recording preserves 4,320,000 complex samples as two lossless signed 16-bit channels at 48 kHz. The station timestamps show 89.273 seconds in common. Five Yokohama packets and three Edogawa packets lacked a station timestamp. Both files replayed to the original byte-for-byte MSC outputs using receiver revision `41b4e2d`. [Edogawa IQ](iq/edogawa-6140khz-iq48.flac) · [Yokohama IQ](iq/yokohama-6140khz-iq48.flac) · [Station clocks and sample bounds](sealed-sources.json) · [Lossless distribution hashes](iq/verification.json) · [MSC replay hashes](iq/replay.json)

From the repository root, these commands reproduce the field and slot checks, the native wire checks, and the independent waveform comparison. The waveform calculation uses NumPy, SciPy and SoundFile.

```sh
case_dir=examples/nov28/same-6140-1232
python "$case_dir/check.py" --slots --out /tmp/same6140-replay.json
python "$case_dir/native_groups.py" "$case_dir/edogawa-msc.bin" "$case_dir/yokohama-msc.bin"
python "$case_dir/verify_timing.py"
```
