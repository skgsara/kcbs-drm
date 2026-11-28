# Two-station 6140 kHz field test at 14:22 UTC

Edogawa and Yokohama each captured the full 90 seconds of IQ. The frozen receiver emitted **zero native MSC service rows** at both sites. It had no physical packet available for cross-station alignment and assigned no counter. The primary group, partial control and independent EVS field comparison all had zero eligible observations. Clear-word accuracy has no denominator in this run. [Frozen protocol](protocol.md) · [Joint receiver report](result/joint/report.json) · [Field selections](result/fields/results.json)

| Receiver | Complex samples at 48 kHz | Deinterleaved MSC cell blocks | Native service rows |
|---|---:|---:|---:|
| Edogawa, 7L4IOU | 4,320,000 | 5 | 0 |
| Yokohama, JL1EDU | 4,320,000 | 2 | 0 |

All seven cell-block headers reported zero bytes allocated to the four service streams. These are observations of the receiver state during these passes. They do not establish the transmitter configuration. Both passes reached the end of their IQ files. [Edogawa observation](result/observations/edogawa/observation.json) · [Yokohama observation](result/observations/yokohama/observation.json) · [Hashed outputs](result/field-seal.json)

Both clocks directly cover the interval from 14:22:02.479188168 to 14:23:31.627480120 UTC on November 28, 2026. That is 89.148291952 seconds of overlap. The first 960 Edogawa samples and 1,920 Yokohama samples lacked timestamps. At the nominal sample rate their inclusion extends the estimated overlap to 89.188291952 seconds. Each lossless FLAC reproduced the original stereo PCM16 WAV byte for byte. [Clock coverage](capture/clock-coverage.json) · [Waveform and timing file hashes](iq/verification.json) · [Edogawa IQ](iq/edogawa-6140khz-iq48.flac) · [Yokohama IQ](iq/yokohama-6140khz-iq48.flac)

The receiver, development controls and inventory of 14,958 prior counters were published at `a20c6f1` before the recorder requests. Both raw inputs were available to the joint receiver. The separate comparison of native Edogawa forecasts with native Yokohama fields had zero predictions and zero verified targets. [Prior inventory sources](history-origins.json) · [Field comparison](result/fields/native-field-comparison.json) · [Release revision](https://github.com/skgsara/kcbs-drm/commit/a20c6f1b662138bf29d97f0b272a4d30e73517e9)

To replay from the lossless recordings, use the commands in the protocol with both sample counts set to 4,320,000. To check the post-demodulation steps directly from the archived observations, use a fresh `work` directory and the 16-QAM decoder from the build recipe.

```sh
case_dir=examples/nov28/dual-diversity-field
obs="$case_dir/result/observations"
python scripts/drm_diversity.py --left "$obs/edogawa" --right "$obs/yokohama" --decoder "$decoder" --out "$work/joint"
python "$case_dir/field.py" --left "$obs/edogawa" --right "$obs/yokohama" --combined "$work/joint" --out "$work/fields"
```
