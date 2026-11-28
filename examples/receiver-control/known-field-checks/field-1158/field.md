# November 27 at 11:58 UTC on 6140 kHz

The receiver predicted the directly carried HQ switch bit correctly at all seven eligible group boundaries. Every forecast and every observed bit was zero, so the fixed-zero baseline also scored **7/7**. Using the group two counters back gave three matches, one mismatch and three unavailable comparisons. The 60 intact groups supplied 43 consecutive edges; the current mode supplied no HQ target on 36 of them. No eligible target was missing. [Sealed forecasts](boundary-plan.json) · [Per-boundary results and original packet checksums](boundary-score.json)

One nominal receiver pass processed all 1,464,832 complex samples from the WAV's declared data chunk, spanning 122.069333 seconds. It emitted 299 MSC rows, including 1,071 of 1,196 physical packets with valid headers and CRCs, and 236 complete native data units. The receiver assigned 978 packet coordinates across 89 counters. All 89 were absent from the 15,511-ID local history sealed before reception. The contributor had already reported aggregate results from this recording. Both sides of each boundary check come from the same antenna recording. Independent sender frames and a second reception were unavailable. [Input and receiver hashes](reception.json) · [Prior report](../../../../docs/november-2026.md) · [Frozen field protocol](../protocol.md)

| Selected group | Complete, partial, absent transported slots | Directly observed bits | Carried bits with unknown clear values | Bits without transport | Checked direct bits matching | Distinct conditionally fixed bits | Complete clear words |
|---|---:|---:|---:|---:|---:|---:|---:|
| First intact and first unregistered, 43871935 | 60, 0, 0 | 10,560 | 5,280 | 0 | 22/22 | 37 | 0/60 |
| First partial, 43871933 | 50, 4, 6 | 8,944 | 4,464 | 2,432 | 36/36 | 14 | 0/60 |

Counter 43871935 starts at native row 8. Each position contributed 2,640 directly observed bits. The codec rules conditionally fixed 9, 10, 9 and 9 bits respectively across positions 1–4. Counter 43871933 first appears at row 2, with 10 of 12 packets assigned. Its four positions contributed 2,336, 2,160, 2,160 and 2,288 observed bits. The conditional counts there were 3, 4, 3 and 4. Conditional bits express codec constraints within the carried-unknown column. [Selection record](group-seal.json) · [All 60 slots for each selection](group-fields.json.gz)

## Reproduce

From the repository root, use the released WAV, the finite-input Dream binary named in the receipt, and a new output directory. The two checksums below were published before scoring. An empty native-group cohort would give a null primary and zero boundary forecasts. The first partial control is selected independently. [Original WAV](https://github.com/skgsara/kcbs-drm/releases/download/samples-2026-11-28/2026-11-27T11_58_16Z_6140.00_iq.wav) · [Receiver freeze](https://github.com/skgsara/kcbs-drm/commit/551dcca647a99e70c2b4b8e4f2c10c56b7fcbecf) · [Published forecast hashes](https://github.com/skgsara/kcbs-drm/commit/071588f8e045fd705d57f17c691494b4bb628d42)

```sh
study=examples/receiver-control/known-field-checks
wav=2026-11-27T11_58_16Z_6140.00_iq.wav
out=/tmp/kcbs-1158-replay
python "$study/replay_1158.py" receive "$wav" "$KCBS_DREAM" "$out"
cmp "$out/receiver/msc.bin" "$study/field-1158/receiver/msc.bin"
python "$study/replay_1158.py" score "$out" \
  59653339a709e0bbbe5400c4550b0c0bd1a52bea4a25c716393ad8f7aa5c0852 \
  fe1ea5918d5a302ca09bddaeef0e20fbc1a8e3b0fe98befd128e7e5592539b2b
cmp "$out/boundary-score.json" "$study/field-1158/boundary-score.json"
gzip -dc "$study/field-1158/group-fields.json.gz" | cmp - "$out/group-fields.json"
```
