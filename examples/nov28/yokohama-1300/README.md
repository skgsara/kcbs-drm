# November 28 scheduled reception, 13:00–13:20 UTC

The Yokohama receiver identified KCBS-2 on **3205 kHz**, service **`A00002`**, with the broadcast label **조선중앙제2라지오방송**. In the first ten minutes, none of 3,000 physical MSC packets passed CRC. The frozen test therefore had **no primary group and no partial control**. A separate pass over the rest of the recording received the three complete data units for **counter 43947653**. The recording establishes the 60 transmitted slots in that later group. It supplies no independent clear EVS words for them. [Blind protocol](protocol.md) · [Sealed blind score](results/primary/scheduled-fields.json) · [Later reception and counter](results/later/reception.json) · [Three data units](results/later/data_units.npz)

## Recordings and timing

The original WAVs contain stereo signed 16-bit I/Q at 48,000 complex pairs per second. The data branch carries the lossless recordings and the original per-packet timing CSVs. Its instructions reproduce the original long WAV and verify its SHA-256. [Download all recordings (ZIP)](https://github.com/skgsara/kcbs-drm/archive/2438fd2162cdeec41178d207d4b652fdf87bcd42.zip) · [Download instructions and individual files](https://github.com/skgsara/kcbs-drm/tree/2438fd2162cdeec41178d207d4b652fdf87bcd42) · [Original WAV, PCM and timing hashes](results/recordings.json)

| Site and file | Sample pairs | Duration | Station time on November 28 (UTC) |
|---|---:|---:|---|
| JL1EDU Yokohama, 3205 kHz, first connection | 54,720,000 | 1,140.0 s | 13:00:01.639512209–13:19:01.639396111 |
| JL1EDU Yokohama, 3205 kHz, reconnection | 2,625,600 | 54.7 s | First timestamp at 13:19:05.259396760, exclusive end 13:19:59.899391207 |
| 7L4IOU Edogawa, 6140 kHz, independent reference | 5,760,000 | 120.0 s | First timestamp at 13:00:02.426654946, exclusive end 13:02:02.406688449 |

Yokohama recorded **1,194.700 of 1,200 requested seconds** in acquisition order. The receiver supplied timestamps on every packet of the first file. After the upstream connection closed, nine packets covering the first 60 ms of the new file lacked timestamps. Extrapolating their start from sample 2,880 at the nominal rate gives a 3.560-second reconnect gap. The opening and closing gaps were approximately 1.640 and 0.101 seconds. Neither file had an internal timestamp step larger than one sample. The primary slice was exactly `[0, 28800000)` in the first WAV. [Capture receipt](results/capture-seal.json) · [Sample ledger and boundary evidence](results/sample-ledger.json) · [Receiver and segment hashes fixed before demodulation](results/primary/before-demodulation.json)

## Control channels and payload

| Yokohama source interval | FAC blocks passing CRC | SDC blocks passing CRC | MSC packets passing header and CRC | Complete groups with assigned counters |
|---|---:|---:|---:|---:|
| Frozen first 600.0 s | 1,109 / 1,422 | 7 / 479 | 0 / 3,000 | 0 |
| Next 540.0 s of first file | 1,102 / 1,284 | 32 / 430 | 22 / 4,308 | 1 |
| Reconnected file, 54.7 s | 133 / 134 | 8 / 46 | 0 / 524 | 0 |

Of the 2,344 CRC-valid FAC callbacks, 2,342 identified data service `A00002` with short ID 0. Two other IDs appeared once each in the first interval, `A67BAF` and `7DD19C`. Neither had SDC corroboration. All 47 CRC-valid SDC blocks carried the same Korean label for short ID 0. An auxiliary receiver saved the FAC and SDC bits before the CRC decision. In each of the three intervals, its MSC output matched the corresponding transport receiver byte for byte. [Primary signalling and service IDs](results/primary/signalling-assessment.json) · [Later signalling](results/later/signalling-assessment.json) · [FAC and SDC reader](../../../scripts/inspect_drm_signalling.py)

The post-test passes used fresh decoder states at the starts of the remaining two intervals. The intact group at 43947653 occupied MSC rows 135–137, counted from zero in the 540-second pass. A fourth whole data unit passed its CRC but lacked an assigned counter. Cold starts can lose reception near each interval boundary. The frozen run assigned zero counters, so it contributed no candidate for comparing against the inventory of 14,882 previous IDs. [Native packet checks](results/primary/physical.json) · [Later transport counts and source bounds](results/later/reception.json) · [Prior exposure check](results/primary/exposure.json)

The separately built signalling observer uses the project’s finite-input Dream sources with the standard receiver patches applied. To reproduce this auxiliary build, decompress the observer patch, apply it with `patch -p1` in the prepared Dream source tree, rebuild, and set `KCBS_SIGNALLING_BITS` to a new trace path for each invocation. The uncompressed patch SHA-256 is `f09aa6245afdde9976200b400ac65cbba7ad206d8d0a94dd64742192c1036414`. [Observer patch](signalling-observer.patch.gz) · [Base build recipe](../../../build/README.md)

## Independent 6140 kHz reference

The opening two minutes at Edogawa yielded **60 complete groups**, 71 assigned counters and 810 assigned physical packets. The receiver found 868 of 1,168 physical packets with a valid header and CRC, and 197 complete data units with a valid CRC. It could assign a counter and phase to 196 of those data units. The complete counter list and original MSC row numbers are in the receipt. The 3205 kHz blind interval supplied zero shared packet coordinates. [Peer protocol](peer-reception.md) · [Peer capture timing](results/peer/capture-seal.json) · [Counter list and raw row numbers](results/peer/transport-receipt.json) · [Comparison with the sealed score](results/peer/comparison.json)

## Replay

Use receiver revision `c7fab06936a3db08b36249c50b06b9ec4f5208c4` and the settings in the protocol for IQ demodulation. The first 28,800,000 sample pairs of the original first Yokohama WAV are exactly the blind input. Its PCM SHA-256 is `8724c561aaf7f319be28078454f0baf1015d0a274663a0cc8e921e8167f55ce1`. The frozen score was sealed at 13:20:14.978 UTC before the peer IQ was demodulated. [Original MSC output](results/primary/msc.bin) · [Score seal](results/primary/sealed-primary.json)

From the repository root, the following commands repeat the score from the accepted packets, the later exposure check, the peer comparison and the signalling checks.

```sh
case_dir=examples/nov28/yokohama-1300
r="$case_dir/results"
python "$case_dir/score.py" "$r/primary/transport" > /tmp/kcbs-scheduled-score.json
cmp /tmp/kcbs-scheduled-score.json "$r/primary/scheduled-fields.json"
python "$case_dir/exposure.py" "$r/primary/scheduled-fields.json"
python "$case_dir/compare_peer.py" "$r/primary/scheduled-fields.json" "$r/primary/transport/packets.npz" "$r/peer/packets.npz" --score-sha256 b1a69b61f1e23ec744eba198540c027557a8541891c5c96a363739259a9e6bc9
python scripts/inspect_drm_signalling.py "$r/primary/signalling.bits"
python scripts/inspect_drm_signalling.py "$r/later/chunk-000.bits"
python scripts/inspect_drm_signalling.py "$r/later/chunk-001.bits"
```
