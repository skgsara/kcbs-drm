# What repeated in the November 19 and 20 programme feeds?

Three ten-second windows in the two archived KCBS-2 feeds contain closely matching audio. At one fixed alignment, the strongest interval was **05:01:40–05:01:50 on the November 19 filename clock**. The November 20 copy ran 9.317375 seconds earlier on its filename clock. The signed waveform correlation was **0.987**, with correlations of 0.990, 0.982 and 0.822 in the separate 300–900, 900–1,600 and 1,600–3,000 Hz bands. Both clips measured about −22 dBFS across the analysis band. A single quiet interval or single-frequency tone cannot account for that result. The programme title and the relation of these file clocks to UTC are unknown. [Per-window scores, audio levels and source hashes](archive-audio.json)

The Internet Archive identifies both source files as original MPEG-4 audio for the corresponding day, credits 조선중앙방송위원회 and names KoryoFront as the feed source. They contain stereo AAC at 48 kHz. The November 19 file begins at 04:17:21 according to its filename and the November 20 file at 04:17:32. Their embedded comments describe concatenated hourly TVHeadend source files. These are two days of archived programme audio. No receiver location or simultaneous AM/DRM recording is established for either excerpt. [November 19 item and original file](https://archive.org/details/kcbs2.2026-11-19) · [November 20 item and original file](https://archive.org/details/kcbs2.2026-11-20)

The initial comparison used the first twenty seconds of each selected period to fit one delay within ±10 seconds. After fitting, the delay and polarity were held fixed across disjoint ten-second windows. Mono waveforms were sampled at 8 kHz and filtered to 300–3,000 Hz. A wrong-time control moved November 20 forward by 90 seconds before fitting. A positive software control delayed the same November 19 audio by 3.25 seconds. Both positive controls recovered that exact delay and gave correlation 1 in every subsequent window.

| Primary filename-clock test | Calibration correlation | Later ten-second windows | Correlation range |
|---|---:|---:|---:|
| 04:20:00–04:21:00 | 0.083 | 4 | −0.109 to 0.016 |
| 05:00:00–05:05:00 | 0.033 | 28 | −0.015 to 0.039 |

The first 05:00 validation window was very quiet on both dates, around −69 dBFS. We added an exploratory calibration on the subsequent audible interval from 05:00:40 to 05:01:00 and retained all 24 later ten-second windows. The fitted correlation was 0.744. The windows beginning at 05:01:00, 05:01:30 and 05:01:40 reached 0.850, 0.966 and 0.987. The other 21 had absolute correlation below 0.027 at that delay. All 24 wrong-time windows had absolute correlation below 0.032. The recording therefore supports a repeated passage at specific times. It leaves the rest of the five minutes and any relationship to the November 25/26 DRM excerpts unverified. [Reproducible results](archive-audio.json)

An additional comparison followed changes in energy in 18 frequency bands. It fitted an offset on 05:01–05:02 and found a second alignment at +10.45 seconds. All six ten-second windows used to fit the delay passed the descriptive threshold, as did the three immediately before and the three immediately after. At this delay none of the 13 evaluable windows from 05:02:30 to 05:04:40 passed. Within each day's recording a similar passage recurred about 19.75 seconds later. This explains why a different occurrence can also align well and limits our ability to infer a unique clock offset. The same-file control with filtering, attenuation and delay passed all 20 evaluable windows outside calibration. Randomly reordering five-second fragments passed none of 19. [Spectral measurements](spectral.json) · [Method](spectral.py)

To reproduce, install FFmpeg with ffprobe, NumPy and SciPy, then run these commands from the repository root. The script can use full original files under their archive names or fetch only three byte ranges per file, totalling 37,000,004 bytes across both sources. For partial downloads it creates sparse local files with the original extents, checks all source ranges against SHA-256 and verifies the byte extent of every AAC packet used in the waveform analysis. Both comparison outputs include decoded PCM hashes.

```sh
case_dir=examples/receiver-control/repeated-programme
OPENBLAS_NUM_THREADS=1 python "$case_dir/archive_audio.py" /tmp/kcbs-two-day-audio --fetch > /tmp/kcbs-archive-audio.json
cmp /tmp/kcbs-archive-audio.json "$case_dir/archive-audio.json"
OPENBLAS_NUM_THREADS=1 python "$case_dir/spectral.py" \
    /tmp/kcbs-two-day-audio/kcbs2.2026-11-19.04_17_21.m4a \
    /tmp/kcbs-two-day-audio/kcbs2.2026-11-20.04_17_32.m4a > /tmp/kcbs-spectral.json
cmp /tmp/kcbs-spectral.json "$case_dir/spectral.json"
```
