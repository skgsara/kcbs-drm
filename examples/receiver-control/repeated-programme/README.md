# Does daily programme repetition produce identical EVS frames?

The 3205 kHz archive already contains two mornings whose recorded **time of day overlaps for 15 minutes 11 seconds**. On November 25 Korean time, HIK received 04:48:00–05:15:29. On November 26, HL5NTR received 05:00:18–05:16:02. The common interval is 05:00:18–05:15:29 KST. These are contributor-reported capture times and the dates are local to Korea. [Nov 25 capture header](../../../contrib/kcbsdrm/reference/KCBS2_text_2026-11-25_0448KST_3205kHz_hik.iptime.org.txt) · [Nov 26 capture header](../../../contrib/kcbsdrm/reference/KCBS2_text_2026-11-26_0500KST_3205kHz_hl5ntr-sdr.ddns.net.txt)

We compared the first-position frame's mode and 21 directly readable payload bytes in every completely received, CRC-checked data unit in the three source files. This included extra time outside the clock overlap and allowed any relative playback delay. The first day yielded 20,190 distinct 22-byte values and the second day 7,185. **Zero values occurred on both days.** The count covers P1-to-P1 comparisons only. Two independent sites receiving the same 6140 kHz transmission provided a positive control with 400 distinct matching P1 values and 80 matching sequences of five successive first positions. [Inputs, denominators and controls](daily-p1.json) · [Reproduction script](daily_p1.py)

This rules out an identical complete P1 word in the two observed P1 sets: at least one directly transmitted octet differs in every comparison. The same piece of music can still produce different bytes. The public first-day listening example includes concealment and inferred material. We did not locate a corresponding continuous listening export for the second day's 05:00 recording that would establish whether the programme in these particular files matched acoustically. [First-day listening release](https://github.com/KoryoFront/kcbs2-drm-decode/releases/tag/november-quiet-review)

## Same music under controlled encoding

Two builds of the stock EVS encoder reproduced the experiment on the same six seconds of generated music at 13.2 kbit/s. Each run produced 300 words. The following results compare the same programme position, allowing for the known sample-grid change. In this example the 22 readable octets gave the same counts as complete 33-byte words. [Exact source and encoder configuration](stock_control.py) · [Encoder outputs, levels and interior-window controls](stock-control.json)

| Change to the encoder input | Identical complete words out of 300 |
| --- | ---: |
| Identical PCM, grid and reset state | 300 |
| Frame grid displaced by 1 ms | 0 |
| Frame grid displaced by 10 ms | 0 |
| Same grid, amplitude halved | 0 |
| Same grid and programme PCM, different preceding second | 245 |

The 1 ms test used identical overlapping source samples. A different alignment with the transmitter encoder's 20 ms frame boundaries changed every compared output word in this melody. Starting an SDR recording early or late affects which transmitted words it captures; it cannot move the transmitter's encoder grid. There is also a real cross-date example at the audio level: the November 27 DRM excerpt of *My Happy Country* matched both a November 19 Pyongyang FM recording and the 1991 Wangjaesan CD performance. Neither analogue comparison supplies a second day's received DRM word for that excerpt. [Programme identification and shifted-time controls](../../../docs/november-2026.md#programme-identification)

From the repository root, run `python examples/receiver-control/repeated-programme/daily_p1.py` to reproduce the radio comparison. The stock check accepts `--encoder /path/to/EVS_cod`. A matching programme is most usefully documented with the original station timestamps, gaps, a matched interval of audible programme, and a separate report of which received bytes actually agreed.
