# What the frozen receiver recovered from 20 seconds of Airspy IQ

The receiver found 152 CRC-valid packets and 38 complete data units in seconds [240,260) of the November 19 Airspy recording. All 14 assigned counters, 43288806–43288819, were absent from the frozen 13,103-counter inventory. The inventory includes 43912071, mentioned separately in the group's November 28 report. The file had been processed before. This 20-second interval falls between two documented receiver runs, and its byte range and receiver settings were published before retrieval. [Frozen protocol](protocol.md) · [Receipt](receipt.json) · [Lossless 6140 kHz IQ](flac-audit/nov19-6140-240-260s-iq48.flac)

The first complete counter was **43288806**. Each of its four positions contributed 15 received words and 2,640 directly transmitted bits. Each position also contained 1,320 masked bits. The receiver returned **zero complete clear words out of 60**. The frozen HQ neighboring-word check found zero eligible triples across the 720 slots in 12 complete groups. These groups included 70 `F8` words and no `F9` predecessor. [All 60 slots](primary.json) · [All-group HQ results](field-results.json)

In the primary counter, the stock SWB ACELP transition rule predicted 11 individual hidden bits across six words. Two further words excluded the pair `01` while leaving both individual bits ambiguous. The receiver measured the mode and the last payload byte for each case. The table gives the remaining possibilities for bits 8 and 9, counting from the high bit of the mode octet. Past P1/P2 labels include counterexamples to this stock-sender assumption. None of these eight words has an independent label for those bits here. [Transition rule and previous discrepancies](../../swb-transition/README.md)

| Position | Slot and allowed pair(s) | Individually predicted bits |
|---|---|---:|
| 1 | 0 → 00 or 01, 16 → 00, 24 → 00 | 5 |
| 2 | 5 → 00, 25 → 00, 10 or 11 | 2 |
| 3 | 6 → 00, 10 or 11, 18 → 01, 58 → 01 | 4 |
| 4 | No applicable transition word | 0 |

## A directly observable GSC field

As a secondary analysis after the primary run, we applied the receiver's previously published GSC prediction to every complete group. Modes `74`–`77` selected 241 INACTIVE/BWE words spanning nine counters. In **241/241** the four predicted bits of payload octet 4 were `1100`, the value independently read from that word's directly transmitted nibble. The four positions contributed 60, 61, 58 and 62 comparisons. Each observation excludes the other 15 nibble values at that location. This checks one field in this GSC subtype. Payload offsets 24 and 27 remain outside the test. [Scores and selection digest](gsc.json) · [Existing rule](../../gsc-fields/README.md)

## Replay

The released FLAC contains all 960,000 complex PCM16 samples of the 48 kHz Dream input. An independent cold replay with this input reproduced the MSC, transport archives and two field reports byte for byte. To start from the original wideband CS8 file instead, take the 36,480,000 bytes beginning at byte 437760000 and pass that slice to the demodulator with `--sample-rate 912000`. [Verification hashes](flac-audit/verification.json)

From the repository root, point `KCBS_DREAM` to the finite-file Dream build and use an empty working directory for the outputs.

```sh
repo=$(pwd)
study=$repo/examples/nov28/hq-neighbors/airspy-gap
mkdir gap-replay && cd gap-replay
gzip -dc "$study/history.json.gz" > history.json
python "$repo/scripts/demod_iq_window.py" "$study/flac-audit/nov19-6140-240-260s-iq48.flac" rf --seconds 20 --reception-profile wiener --mlc-iterations 1
python "$repo/scripts/salvage_msc_packets.py" rf/msc.bin --transport-only --out transport
python "$study/../check.py" transport/data_units.npz --provenance transport/provenance.json --history history.json > field-results.json
python "$repo/scripts/project_evs_group.py" transport/data_units.npz --counter 43288806 --field-checks > primary.json
python "$study/gsc.py" transport/data_units.npz > gsc.json
cmp field-results.json "$study/field-results.json"
cmp primary.json "$study/primary.json"
cmp gsc.json "$study/gsc.json"
```
