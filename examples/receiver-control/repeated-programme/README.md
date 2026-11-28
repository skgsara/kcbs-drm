# Does daily programme repetition produce identical EVS frames?

We found repeat audio in two consecutive days of public KCBS-2 programme archives. On the November 19 file clock, the ten seconds at 05:01:40 matched a passage 9.32 seconds earlier on the November 20 file clock, with a waveform correlation of 0.987. The opening contains a recurring passage, so more than one time offset can align parts of it. The two archives carry AAC audio. Separate 3205 kHz DRM recordings from November 25 and 26 let us test whether the directly transmitted bytes of an EVS frame repeated at any position on the other day. [Archive audio and controls](archive-audio.md)

## First-position frames from two mornings of 3205 kHz DRM

The 3205 kHz archive already contains two mornings whose recorded **time of day overlaps for 15 minutes 11 seconds**. On November 25 Korean time, HIK received 04:48:00–05:15:29. On November 26, HL5NTR received 05:00:18–05:16:02. The common interval is 05:00:18–05:15:29 KST. These are contributor-reported capture times and the dates are local to Korea. [Nov 25 capture header](../../../contrib/kcbsdrm/reference/KCBS2_text_2026-11-25_0448KST_3205kHz_hik.iptime.org.txt) · [Nov 26 capture header](../../../contrib/kcbsdrm/reference/KCBS2_text_2026-11-26_0500KST_3205kHz_hl5ntr-sdr.ddns.net.txt)

We compared the first-position frame's mode and 21 directly readable payload bytes in every completely received, CRC-checked data unit in the three source files. This included extra time outside the clock overlap and allowed any relative playback delay. The first day yielded 20,190 distinct 22-byte values and the second day 7,185. **Zero values occurred on both days.** The count covers P1-to-P1 comparisons only. Two independent sites receiving the same 6140 kHz transmission provided a positive control with 400 distinct matching P1 values and 80 matching sequences of five successive first positions. [Inputs, denominators and controls](daily-p1.json) · [Reproduction script](daily_p1.py)

This rules out an identical complete P1 word in the two observed P1 sets: at least one directly transmitted octet differs in every comparison. The same piece of music can still produce different bytes. The public first-day listening example includes concealment and inferred material. We did not locate a corresponding continuous listening export for the second day's 05:00 recording that would establish whether the programme in these particular files matched acoustically. [First-day listening release](https://github.com/KoryoFront/kcbs2-drm-decode/releases/tag/november-quiet-review)

## Could the same word appear at a different position the next day?

We compared each of the four positions on November 25 with all four positions on November 26, allowing any playback delay. The 94,600 observed frames on the first day gave 80,760 distinct 22-byte values. The 33,480 on the second day gave 28,740. **Every pair of values from opposite days differed in at least six of the 22 directly observable bytes.** This rules out an identical complete EVS word anywhere in the two sets of received frames, including a first-position word recurring at the second position. The missing frames and the rest of each day's broadcast remain untested. [Per-position counts, source hashes and distance check](role-comparison.json)

To check the six-byte lower bound across 2,321,042,400 possible pairs, we split each 22-byte value into six disjoint sets of offsets. If two frames differ at five or fewer offsets, at least one set must agree in full. Only 462 cross-day pairs shared even one complete set. We compared all 22 bytes in each of those pairs and found at least six differences every time. [Distance counts and constructed controls](role-comparison.json)

Two stations receiving the same transmission recovered 1,600 distinct exact matches, 400 at each corresponding position. The longest match continued through 500 consecutive frames, or 10 seconds. To reproduce both comparisons from the repository root, run `python examples/receiver-control/repeated-programme/role_comparison.py --check`. [Comparison script](role_comparison.py)

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
