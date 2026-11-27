# KCBS-2 on shortwave, November 2026

On November 27, paired 6140 and 3205 kHz recordings captured **행복한 내 나라 (*My Happy Country*)** by the Wangjaesan Light Music Band (왕재산경음악단). The 30-second receiver audio follows the broadcast performance throughout. A continuous 12-second excerpt supplies every 20 ms codec frame. [Listen to the radio MP3](../examples/nov27/radio.mp3) · [12-second lossless excerpt](../examples/nov27/fully-supplied-12s.wav)

## What the receiver recovered

Both channels carried DRM Mode B and service A00002, labelled **조선중앙제2라지오방송**. Both advertised one packet-data service. The country field contained *kp* and the language field was unspecified. After acquisition, Dream passed all 72 Fast Access Channel CRC checks on 6140 kHz and all 71 on 3205 kHz. The receivers agreed on all 292 packet positions they both recovered. Together they supplied 300 distinct CRC-checked packets spanning 75 consecutive data units.

The published reconstruction covers 1,500 slots. Of the 1,150 supplied EVS frames, 355 were supported by checksummed broadcast text and 795 were inferred from the received words using codec checks and comparison recordings. The stock 3GPP decoder concealed the other 350 slots. Fourteen complete 1.2-second groups contain all 60 frames. The longest continuous run of supplied frames spans **5.16 to 17.22 seconds**. The WAV excerpt spans the ten whole groups from 5.20 to 17.20 seconds. [Frame-by-frame evidence](../examples/nov27/frames.csv) · [Counts and checksums](../examples/nov27/replay.json)

[Validation methods and blind controls](nov27-mask-validation.md) · [Reproduce the waveform from the receiver packets](../README.md#november-27-dual-frequency-recording)

## Programme identification

An archive search on the text-supported receiver audio found the same passage in an earlier Pyongyang FM broadcast. An independently titled release matched the instrumental performance on track 1 of the 1991 CD *Wangjaesan Light Music Band Vol. 1*, catalogue WJS-C-101. At 1.60 seconds in the published receiver audio, the passage is about 2:03.64 into the CD. Earlier frames fixed the time offset and polarity. Two later, disjoint windows agreed with both references. [1991 CD and track listing](https://archive.org/details/wangjaesangyongumaktan-che1chip) · [Pyongyang FM archive](https://archive.org/details/pyongyang-fm.2026-11-19)

At 785 comparable windows among the 795 additionally inferred frames, the receiver waveform scored **0.930 against FM** and **0.926 against the CD** on a signed similarity scale from −1 to 1. Shifting either reference forward by 740 ms gave −0.016. Shuffling the new frames within the same codec mode gave 0.035 and 0.034. The references also contributed to inference. These scores quantify agreement in the decoded waveform. The independent packet CRCs cover the transport layer. The radio WAV contains decoded receiver words and EVS concealment. [Comparison results and denominators](../examples/nov27/reference-comparison.json)

## Reproduce the radio WAV

The example includes two clear EVS streams in little-endian ITU-T G.192 format. From the repository root on Linux or inside WSL, build the floating-point reference decoder and replay either stream. Place the 3GPP TS 26.443 reference source used for the build under `work/ref/evs/src/c-code`. The decoder release used here is dated November 4, 2021. The replay script uses Python’s standard library. [Decoder build script](../scripts/build_evs_gcc_independent.py) · [Replay script](../examples/nov27/replay.py)

```sh
python scripts/build_evs_gcc_independent.py --out work/evs_gcc_independent
python examples/nov27/replay.py --out work/nov27-replay/programme.wav
python examples/nov27/replay.py --stream text-supported --out work/nov27-replay/text-supported.wav
```

Each WAV contains 480,000 mono samples at 16 kHz. The script verifies the compressed stream, G.192 data, raw PCM and WAV against their SHA-256 digests. To use an existing reference decoder build, pass its executable path with `--decoder`. [Programme bitstream](../examples/nov27/programme.192.gz) · [Text-supported comparison bitstream](../examples/nov27/text-supported.192.gz) · [Expected hashes](../examples/nov27/replay.json)

## Seven additional November 27 recordings

The listening group supplied seven more recordings from 6140 and 3205 kHz, totalling 30 minutes 53 seconds. All seven carried DRM Mode B and service `A00002`, labelled **조선중앙제2라지오방송**. Six yielded complete scrolling-text records. The 276 records contained 76 distinct bodies, including a marine weather forecast and science news. The audio programmes in these seven recordings remain unidentified.

| Capture time (UTC) | kHz | Data units passing CRC | Text records passing CRC | Frames supported by local text CRCs | Extra frames from repeated text | 20 ms slots |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Around 07:56 (HDSDR recording) | 6140 | 1,178 | 116 | 4,063 | 57 | 24,020 |
| Around 10:59 (from broadcast counters) | 6140 | 21 | 0 | 0 | 32 | 4,940 |
| 11:58:16 | 6140 | 285 | 20 | 718 | 34 | 5,980 |
| 12:00:34 | 6140 | 498 | 48 | 1,680 | 25 | 9,960 |
| 12:09:09 | 3205 | 243 | 15 | 521 | 24 | 6,360 |
| 12:11:22 | 3205 | 365 | 21 | 730 | 299 | 9,300 |
| 12:15:02 | 3205 | 932 | 56 | 1,872 | 922 | 30,360 |
| **Total** | | **3,522** | **276** | **9,584** | **1,393** | **90,920** |

The receiver checked the CRC on each accepted packet and again on each complete data unit. To recover an audio frame, it also needed the mask bytes shared with the text channel. For 9,584 frames, the decoded text passed a CRC transmitted in that same recording. For another 1,393 frames, two or more received text blocks agreed with a checked passage repeated in another recording. This second method supplied all 32 frames from the weakest capture. Across the seven timelines, the decoder received **10,977 complete frames (12.1%)** and used loss concealment for the remaining 79,943 slots. Each timeline runs from the first accepted data unit to the last and includes the gaps between them.

**A test on a recording received later.** The eight-minute HDSDR file arrived after the other six had been analysed. Its mono 48 kHz WAV carried a real intermediate-frequency signal 6 kHz above the receiver's 6134 kHz tuning. Its header clock read 07:55:48.790. The broadcast counters put the start around 07:55:55–07:55:59 UTC, in an interval preceding the other six. Using only bulletin templates saved before this file arrived, the decoder recovered **105 records** that passed the new recording's own CRCs. Analysis of the new file added 11 more. Four deliberately shifted template alignments yielded zero matches across 534 complete candidate spans in the final check.

**A check on frame reconstruction.** A short final text record and its adjacent fill block could exchange positions and still pass the text CRC. The metadata following the record established their order. With that order, the EVS reference decoder raised zero syntax flags on the 10,977 supplied frames. Four control runs shuffled the eleven restored bytes together between frames of the same codec mode, preserving the clear bytes and erasure positions. Those runs raised 656–681 flags. This checks the recovered frame structure. Identifying the programmes would also require matching the audio to an independent recording.

For holders of the local verification bundle, extract `KCBS-2026-11-27-listening-and-verification.zip` and run `python verify.py` in its top-level directory with NumPy installed. The verifier rechecks the packet, data-unit and text CRCs and rebuilds every supplied frame and erasure in the included G.192 streams. Its `README.md` links the listening files and per-capture evidence.

## November 19 comparison

Two earlier broadcasts on 6140 kHz matched other performances. The 17:09:40 recording contained the Moranbong Band duet **그리움은 나의 행복 (*Longing Is My Happiness*)**, and the 17:31:39 recording contained Ryu Jina’s **어머니의 목소리 (*Mother’s Voice*)** with the same band. Their extended receiver excerpts supplied 750 of 1,620 frames in 32.4 seconds and 2,583 of 5,160 frames in 103.2 seconds, respectively. The weaker 17:00:52 excerpt remains unidentified. Times in this paragraph are the November 19 recording labels. [Duet performance](https://archive.org/details/moranbong-band-longing-is-my-happiness) · [Solo performance](https://archive.org/details/moranbong-band-mothers-voice)
