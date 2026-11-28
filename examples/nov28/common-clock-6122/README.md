# Receiving 6100 and 6140 kHz on one IQ clock

Edogawa's 7L4IOU recorded **180 seconds** of stereo PCM16 IQ at 48 kHz centered on 6122 kHz. The 6100 kHz AM carrier and 6140 kHz digital channel fit in one recording. AM audio sample `k` and digital baseband sample `k` both correspond to original IQ pair `4k`. The raw file contains 8,640,000 pairs. The first 1,920 pairs have no station timestamp. Direct timestamps cover 17:03:26.325913545–17:06:26.285562721 UTC with no step larger than one sample. [IQ, packet timestamps and audio](https://github.com/skgsara/kcbs-drm/tree/fc1cb68ceb10cabcdf7435603239fa3856a2e811/common-clock) · [Hashes and timing](recordings.json) · [Receiver grant and acquisition](recorder.json)

**6100 kHz AM.** The carrier was approximately 1 Hz above nominal and 34.9 dB above the local spectral floor. We retained the carrier and a passband extending from 1.2 kHz below to 3.8 kHz above it. The asymmetric passband preserves the upper sideband inside the recorded spectrum. The envelope gives three minutes of mono 12 kHz audio. A station identification and a digital simulcast remain unconfirmed. [Listen to the AM recording](https://raw.githubusercontent.com/skgsara/kcbs-drm/fc1cb68ceb10cabcdf7435603239fa3856a2e811/common-clock/6100-am.wav) · [Filter, carrier and audio measurements](am-receipt.json)

**6140 kHz DRM.** The frozen receiver used the full extracted 12 kHz channel from sample zero. The finite-input Wiener/MLC1 pass reached EOF and yielded zero MSC rows. There were zero packet CRC trials, zero assigned counters and no group to test. The executable exposed no FAC/SDC CRC counts or service ID. A separate post-seal Mode B cyclic-prefix check passed **zero of 18 ten-second blocks**. The programme timing comparison had no received digital mode octets to align to AM. [Receiver protocol](receiver-protocol.json) · [Channel extraction](channel-receipt.json) · [Receiver outcome](receiver-result.json) · [Mode B block scores](../paired-3250-1657/rf-check/6140-results.json) · [Programme timing outcome](programme-test.json)

**Offline geometry check.** We placed a known clear DRM test transmission and a two-tone AM signal at the same frequency offsets in a local file. After channel extraction the digital receiver reproduced the published 169 native rows byte for byte. Of the sender's 2,400 scored EVS words it emitted 2,113 exact words, zero wrong words and 287 erasures, matching the original centered test. The AM upper sideband reproduced the two-tone waveform at zero lag with a correlation of 0.99918. These controls check the channel offsets, filters and sample mapping. The on-air observations above supply no EVS word accuracy measurement. [Source of the control](../../receiver-control/README.md) · [Digital control](synthetic-check.json) · [Upper-sideband measurement](upper-sideband.json)

## Reproduction

Restore `7l4iou-6122-iq48.flac` to `edogawa-6122.wav` using the instructions on the data branch. Run the commands below from the repository root with `KCBS_DREAM` pointing to the pinned executable and fresh output directories. The receiver revision is `3250f175b96ad3c373e466b09bc2f082bdc044a1`. The extractor's floating-point WAV includes a creation time in its `PEAK` header. Use the float32 sample digest for cross-run comparisons. Two replays of the synthetic control differed only in that header and produced identical sample data, native rows and EVS outputs. [Data branch instructions](https://github.com/skgsara/kcbs-drm/tree/fc1cb68ceb10cabcdf7435603239fa3856a2e811)

```sh
case_dir=examples/nov28/common-clock-6122
python scripts/extract_iq_channel.py edogawa-6122.wav edogawa-6140-iq12.wav --offset-hz 18000
python scripts/demod_iq_window.py edogawa-6140-iq12.wav receiver-6140 --seconds 180 --reception-profile wiener --mlc-iterations 1
python "$case_dir/demod_am.py" edogawa-6122.wav "$case_dir/recorder.json" recovered-am
python examples/nov28/paired-3250-1657/rf-check/check_6140.py edogawa-6140-iq12.wav cp-6140.json
python "$case_dir/synthetic_check.py" . scripts "$KCBS_DREAM" synthetic-run
```
