# A blind receiver test on the November 19 wideband recording

From the same 22 seconds of recorded IQ, we extracted 6140 kHz DRM and a carrier near 6100 kHz. Two offline Dream builds produced the same 49 CRC-valid DRM data units. All 17 assigned counters were new relative to the frozen inventory, including the final partially received counter. Sixteen groups were complete. [Protocol committed before fetching the input](https://github.com/skgsara/kcbs-drm/commit/0d65f6055ffc6f861f65a6fba08aade47866ad97) · [Channel hashes, counters and per-slot fields](receipt.json) · [Byte comparison](replay-comparison.json)

**The first complete counter was 43288733.** All four positions had 15 received words each. At each position 2,640 bits were visible and 1,320 bits had unknown clear values. None of its slots used modes F9, FA or FB. The receiver returned 60 word erasures and zero complete clear EVS words. [All primary slots](primary.json)

## What the receiver could infer

Across 960 words in the 16 complete groups, the stock SWB HQ class rule made the following conditional predictions. Word bit zero is the high bit of the mode. Bit 8 is the high bit of the first payload octet.

| Eligible mode and field | Position 1 | Position 2 | Position 3 | Position 4 |
|---|---:|---:|---:|---:|
| F9, bit 8 equals zero | 6 | 5 | 5 | 9 |
| FA, bits 8–9 can be 00, 01 or 10 | 0 | 1 | 0 | 0 |

The first such word was counter 43288734, slot 23, position 4. We lack clear-bit labels for these 26 words. The F9 prediction excludes the opposite bit under the stock encoder rule. The FA restriction leaves both individual bits ambiguous. No late audio payload byte was recovered by this check. [Original rule and independently checked historical labels](../../nov27/validation/hq-class/README.md)

As a calibration, we demodulated the first 600 seconds of the earlier November 27 13:17:09 recording in one ordinary Wiener pass. Of 913 CRC-valid DUs, 256 groups were complete. Of 117 conditional words in those groups, 30 had a matching published slot label. All nine F9 predictions agreed with the labeled hidden bit (four P1, five P2). The observed high pair fell within the predicted set for all 21 comparable FA words (13 P1, eight P2). The remaining 87 eligible words lacked a comparison, including all P3 and P4 cases. The P1 comparisons reuse published development observations. Every P2 comparison has an ordinary text record witness. These are repeated measurements on labeled data. [Calibration coordinates and counts](1317-calibration.json) · [Scorer](calibration.py)

## What the second channel adds

The AM and DRM outputs each hold 264,000 complex samples at 12 kHz with source sample zero corresponding to the same instant. In all 20 interior one-second windows the strongest narrow carrier within ±200 Hz of nominal 6100 kHz was near −89 Hz. Its median level was 53.4 dB above the median sideband bin. Identifying a common programme would require a content match. The AM measurement contributed no bits to the receiver. [6100 IQ](6100.wav) · [6140 IQ](6140.wav)

## Replay

With the group's original 912 ksps CS8 file, extract bytes [280896000,321024000). From the repository root, run the following commands. The output directory must be new.

```sh
study=examples/nov28/iq-holdout
dd if=onair_drm_6.140MHz_0.912Msps_20261119-173139.cs8 of=holdout.cs8 bs=1824000 skip=154 count=22 status=none
gzip -dc "$study/historical-counter-ids.json.gz" > history.json
python "$study/replay.py" holdout.cs8 history.json /path/to/finite-input/dream replay
```

The CS8 interval SHA-256 is `c1bbf2b3551abc5379c9c7b24e7a8766ecbc6b027dcea174023e80c0c9d26404`. The receipt reports float32 sample hashes separately because WAV metadata can contain a creation time. The released channel WAVs can also be used directly with `scripts/demod_iq_window.py`. To inspect the first complete group's individual constraints without RF dependencies, use the released DU archive.

```sh
python scripts/project_evs_group.py examples/nov28/iq-holdout/data_units.npz --counter 43288733 --field-checks
```

For the historical calibration, demodulate the first 600 seconds of `30min-2026-11-27T13_17_09Z_3205.00_iq.wav` with the same profile and one MLC iteration. Run `scripts/salvage_msc_packets.py --transport-only` on its MSC dump. Generate predictions with `python examples/nov27/validation/hq-class/observe.py path/to/data_units.npz > predictions.json`, then run `python examples/nov28/iq-holdout/calibration.py predictions.json`. The input WAV SHA-256 is `c2c23a6768d836a71a25086ea0a6e4155a3657fab132e4ace0d132e3aa93560e`.
