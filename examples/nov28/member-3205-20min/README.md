# A 22-minute member recording of KCBS-2 on 3205 kHz

The member's `IQ-3205khz-20261128.wav` contains **22 minutes 48.286 seconds** of 44.1 kHz stereo PCM16. We treated left as I and right as Q and took the nominal frequency from the filename. The WAV header contains no UTC start or tuner setting. The whole recording yielded the DRM service ID `A00002` and the Korean label **조선중앙제2라지오방송**. The original WAV's SHA-256 is `bda3f500aaab2032de0e93c493e87650767be1504b29085679cf7082e4b5b952`. [Receiver settings published before demodulation](protocol.json) · [Reception and CRC counts](reception.json)

## What the receivers recovered

| Source and processing | Complete 716-byte data units | Complete 1.2-second groups |
| --- | ---: | ---: |
| Member's 3205 kHz IQ, frozen receiver | 3,335 | 1,102 |
| Same IQ, including a second pass with four decoding iterations | 3,337 | 1,103 |
| Both frequencies, including the timestamped Edogawa 6140 kHz recording | 3,343 | 1,106 |

The frozen pass received 13,381 distinct CRC-good packets across 1,121 counters. Of the 1,138 counters in the span from 43907925 through 43909062, 17 had no assigned packets and 19 had only part of a group. The two processing-window overlaps contained 164 repeated packets, all byte-identical. The second pass on the same IQ restored phases 1 and 2 of 43908298. [Reception details and gaps](reception.json) · [Second pass](second-pass.json)

The independent 6140 kHz reception shared 1,201 original packets with the 3205 kHz baseline. All 182 bytes agreed in every shared packet, including the transmitted CRC. All 284 common complete data units agreed. Compared with the frozen 3205 kHz pass, Edogawa supplied eight further complete data units and filled groups 43908227, 43908228, 43908298 and 43908300. Two of those eight data units were also recovered in the second 3205 kHz pass. Each of the four groups was received whole on 6140 kHz. [Comparison and provenance of the eight additions](cross-frequency.json) · [Earlier 6140 kHz reception](../../nov27/validation/swb-gsc/README.md)

The FAC in this recording signals short interleaving and 16-QAM for both MSC and SDC. SDC assigns 728 bytes per 400 ms to stream 0, or 14.56 kbit/s including packet overhead. The four 182-byte packets each carry 179 data bytes. Their bodies form a 716-byte DU including its final two CRC bytes. [Received FAC and SDC fields](reception.json) · [Dream's FAC field mapping](../../../patches/dream/FAC.cpp) · [Packet and DU checks](../../../scripts/salvage_msc_packets.py)

Using the Edogawa receiver's timestamps and the shared counter sequence places the start of the member file at about **23:58 UTC on November 27** (07:58 Beijing time on November 28). This is a minute-level estimate assuming the transmitters carried the same data with negligible relative delay at that precision. [Clock evidence and assumptions](timing.json)

## Five places to test the text carousel

A different recording had shown a bulletin period of 798 data units (319.2 seconds). Applying that spacing to this capture gives **five intervals of 33.6 seconds** with all 84 successive data units present in each interval. The first four also have an uninterrupted 48.4-second stretch. These counts describe which data arrived. Confirming a text repeat requires checking the bulletin contents and their own record CRCs. [Exact coverage, denominators and gaps](carousel-coverage.json)

| Interval | Start counter, phase 0 | Seconds from the start of group 43907925 |
| ---: | ---: | ---: |
| 1 | 43907971 | 55.2 |
| 2 | 43908237 | 374.4 |
| 3 | 43908503 | 693.6 |
| 4 | 43908769 | 1,012.8 |
| 5 | 43909035 | 1,332.0 |

We compared the original 16-byte text tails at every available pair of starts separated by 798 data units. **Zero of 2,514 pairs** were byte-identical. At each of the 193 starts with five observations, all five tails differed. A bulletin could still carry the same underlying text under different masks. We also passed all 53,360 received tail bytes through the ordinary text-record parser, preserving gaps. Of 65 ordinary-looking record starts with a complete span, zero passed the transmitted text CRC. Including the eight additional data units produced the same result. A historical clear text record with CRC `A2C0` passed the same check, and changing one body bit caused it to fail. [Literal-text checks and results](literal-text.json)

## The blind audio check

The receiver selected the first complete group, **43907925**, according to the published protocol. Its 60 received frame slots contain 10,560 directly readable bits and 5,280 bits whose clear values remain unresolved. The receiver produced **0/60 complete clear EVS words**. Thirteen checks on directly received codec fields agreed. Seventeen other bit coordinates had conditional predictions with no independent clear labels. Of the 1,121 counters in the full recording, 119 occurred in our earlier transport inventory, all in the Edogawa recording. The remaining 1,002 include the primary. The historical reference tables supplied no labelled first-position words or second-position bits for these counters. [Primary group evidence](primary.json) · [Prior counter inventory](history.json.gz)

## Using the group data

The [3205 kHz data archive](member-dus.npz) contains all 3,335 complete data units from the frozen pass. The [eight further data units](extra-dus.npz) are disjoint and use the same format. Each archive holds three aligned NumPy arrays, `counters`, `phases` and `du`. The last array contains 716 received bytes per row. Retain the coordinates when joining or comparing data. Gaps in the counter and phase sequence identify missing transmissions.

The three DU headers in the baseline archive were `40 00` (1,116 units), `40 10` (1,111) and `40 20` (1,108). Each DU carries five successive cycles of positions P1, P2, P3 and P4. A complete counter therefore contains 15 slots of each position, spread across its three DUs. For zero-based slot numbers the row is `slot = 20 * phase + 4 * cycle + (position - 1)`. This lets two receivers compare the same slot even if they dropped different packets. [EVS slot projector](../../../scripts/project_evs_group.py)

When comparing audio results, count the distinct `(counter, slot)` coordinates with a supported 33-byte word, the words actually supplied to EVS, and the slots for which the decoder used concealment. Each supplied word represents 20 ms. The output WAV duration includes concealment. For a text comparison, a start counter and phase locate the record in this archive. Its full header, UTF-16LE body, transmitted text CRC and following padding allow a separate record check. [Text-record checker](../../../scripts/parse_text_records.py)

To replay the first complete group from the small [three-unit excerpt](data_units.npz), run from the repository root with NumPy installed.

```sh
python scripts/project_evs_group.py examples/nov28/member-3205-20min/data_units.npz --counter 43907925 --evidence
```

To check for ordinary text records directly in the received tails, the following reads the full member archive in counter order and splits at every gap. It prints `3335 DUs, 22 continuous runs, 0 literal records`.

```sh
PYTHONPATH=scripts python - <<'PY'
import numpy as np
from parse_text_records import scan_records

with np.load('examples/nov28/member-3205-20min/member-dus.npz', allow_pickle=False) as data:
    ticks = 3 * data['counters'].astype('int64') + data['phases']
    order = np.argsort(ticks)
    gaps = np.flatnonzero(np.diff(ticks[order]) != 1) + 1
    runs = np.split(data['du'][order, 698:714], gaps)
    records = sum(1 for run in runs for _ in scan_records(run.tobytes()))
    print(f'{len(ticks)} DUs, {len(runs)} continuous runs, {records} literal records')
PY
```
