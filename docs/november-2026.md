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

## November 19 comparison

Two earlier broadcasts on 6140 kHz matched other performances. The 17:09:40 recording contained the Moranbong Band duet **그리움은 나의 행복 (*Longing Is My Happiness*)**, and the 17:31:39 recording contained Ryu Jina’s **어머니의 목소리 (*Mother’s Voice*)** with the same band. Their extended receiver excerpts supplied 750 of 1,620 frames in 32.4 seconds and 2,583 of 5,160 frames in 103.2 seconds, respectively. The weaker 17:00:52 excerpt remains unidentified. Times in this paragraph are the November 19 recording labels. [Duet performance](https://archive.org/details/moranbong-band-longing-is-my-happiness) · [Solo performance](https://archive.org/details/moranbong-band-mothers-voice)
