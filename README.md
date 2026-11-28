# November 28, 2026 · 13:00 UTC KCBS-2 I/Q recordings

Two public receivers in Japan recorded during the agreed 13:00–13:20 UTC window. JL1EDU in Yokohama recorded 3205 kHz. The independent opening reference is from 7L4IOU in Edogawa on 6140 kHz. Every file contains stereo signed 16-bit PCM at 48,000 complex sample pairs per second, with I on channel one and Q on channel two. [Download the complete ZIP](https://github.com/skgsara/kcbs-drm/archive/refs/heads/data-nov28-1300-iq.zip) · [Capture protocol](https://github.com/skgsara/kcbs-drm/blob/c7fab06936a3db08b36249c50b06b9ec4f5208c4/examples/nov28/yokohama-1300/protocol.md)

| Receiver and recording | Approximate station time, UTC | Sample pairs | Recorded seconds |
| --- | --- | ---: | ---: |
| Yokohama 3205 kHz, segment 1 | 13:00:01.640–13:19:01.639 | 54,720,000 | 1,140.0 |
| Yokohama 3205 kHz, segment 2 | 13:19:05.199–13:19:59.899 | 2,625,600 | 54.7 |
| Edogawa 6140 kHz | 13:00:02.407–13:02:02.407 | 5,760,000 | 120.0 |

Yokohama recorded 1,194.7 seconds. On the station clock, approximately 1.640 seconds preceded the first file, 3.560 seconds elapsed during reconnection and 0.101 seconds followed the second file. Segment 2 begins with 60 ms of recorded samples whose timestamps are blank. The first 20 ms at Edogawa also have blank timestamps. Both start estimates use the next timestamp and the sample offsets. Each end time is the exclusive end of the final packet on the station clock. The CSVs retain the original timing fields, including blanks. Each CSV's sample offsets refer to its original recording. [Original timing CSVs and two shorter WAVs](iq/) · [File sizes, sample counts and original SHA-256 digests](recordings.json)

## Restore the original files

Download and extract the ZIP, then run the following from its top-level directory with Python 3. The output directory must be new.

```sh
python3 restore.py recovered
```

The script produces all three original WAVs, their three timing CSVs, and the original manifest. It validates each file's length and SHA-256 against the sealed manifest. The 218,880,044-byte first Yokohama WAV is distributed as five individually playable 228-second parts. The script checks the order and hash of each part, copies its PCM samples, writes the original 44-byte WAVE header and verifies both the PCM digest and the complete original WAV digest. It preserves the separate recording after the reconnect. [Five WAV parts](parts/) · [Part order, sample offsets and digests](parts.json) · [Restoration script](restore.py)
