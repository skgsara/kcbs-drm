# Comparing 3250/6100 kHz AM with 3205/6140 kHz DRM

A group member reported that the two AM waveforms aligned to milliseconds in their recording, and that **311 DRM data units** matched byte for byte at the same counter and phase. In a later listening update they reported **different AM and DRM programmes at the time of listening**, and a period of shared programming the previous day. Their messages give no exact UTC interval for either observation or for the 311 DUs. We cannot place the listening report in the 311-DU interval. The digital count and within-AM alignment describe agreement between carriers of the same modulation.

For programme comparison, qualify AM as a reference for a specific time interval by comparing it to independently supported DRM audio. The November 27 11:05 UTC handoff passes that test. The IQ-only receiver uses the DRM channel throughout.

## The group's 09:19:50 Beijing recording

In a subsequent report the group observed a shared programme again. Two Airspy HF+ receivers recorded three minutes beginning at **09:19:50 Beijing time** (01:19:50 UTC). They report agreement between AM at 3250/6100 kHz and the first-position DRM audio at 3205/6140 kHz in all nine comparison windows, with a file offset near −5.79 s. The signed lag belongs to their files and convention. Our Edogawa capture began at 01:25:09 UTC, over two minutes after the reported interval ended. We have the group's summary. Its two recordings and per-window comparisons were absent from the shared folder at 01:39 UTC.

On already known first-position words, the group separately hid the low two bits of payload bytes 24 and 27 and offered four candidate values per test. Joint AM scoring put the correct value **uniquely first in 3/15 and 1/15** held-out groups, respectively. The report gives neither ties nor all four scores. Those results support using the reported simulcast for programme timing and leave the byte choices unresolved.

The group's separate EVS field test reports one surviving 13-bit combination in each of two groups at position two. The 15 position-two frames at counter **43912071** were all classified as GSC. Under the group's field assumptions, they report **35 bits still unresolved** in each group. The original bytes and candidate ledger will be needed to reproduce that result. Counter 43912071 is recorded as disclosed for subsequent blind tests.

One reproducible GSC check is already available for comparison if the reported frames use modes `74`–`77`. In a separate Airspy recording the prior mode-based prediction for word bits 40–43 agreed with their directly received value on 241/241 eligible words, including 61 at position two. The member's summary gives the GSC class only, so the number eligible at 43912071 is unknown. [IQ, field and counters](../hq-neighbors/airspy-gap/README.md)

## The group's 09:42:39 Beijing recording

The group recorded another 45 seconds, **09:42:39–09:43:24 Beijing time (01:42:39–01:43:24 UTC)**. They report that 3250 and 6100 kHz AM still carried the same programme and that 3205 and 6140 kHz DRM still carried the same data stream. They compared 3250 AM to 3205 DRM using 420 text-CRC-supported first-position frames. Those frames span 8.4 seconds of encoded audio distributed through the 45-second window. Their cross-programme comparison was inconclusive and they did not start the proposed five-minute follow-up.

This check began 19 minutes 49 seconds after the earlier three-minute recording ended. The report gives no correlation scores, lag search or acceptance threshold for the later window. It leaves open whether the programmes differed or the comparison lacked enough usable audio. Keep the earlier −5.79 s file offset with the earlier recording.

## The group's 10:02:39 Beijing recording

The group subsequently shared five-minute 6100 and 6140 kHz IQ files. They report a programme match in the first 126 seconds, through **10:04:45 Beijing (02:04:45 UTC)**. Our independent check compared the directly received EVS mode bytes with the frequency content of the AM audio. One held-out 38-second window inside that interval passed. Two windows after 126 seconds did not pass. [Source hashes, separate interval replays and programme scores](member-100239/README.md)

## Comparing wideband recordings

Two sufficiently wide Airspy HF recordings can contain all four channels. The lower pair is 45 kHz apart and the upper pair is 40 kHz apart. When those pairs are recorded on different receivers, retain both start times, sample rates and channel frequencies. Independently tune each RF channel. The two AM outputs can then be aligned by audio content; the two DRM receptions can be aligned by their transmitted packet coordinates. A common computer can start two devices with different sample clocks.

## What we could verify

| Reception | Comparison | Result |
|---|---|---|
| Nov 27, 06:17 UTC | 3205 and 6140 DRM | All 292 shared packets matched, including headers and CRCs. The union yielded 300 packets and 75 data units. Compared with either individual reception, the second frequency added one data unit (20 transported EVS slots). All 24 complete counter groups were already present on both frequencies. |
| Nov 27, 11:05 UTC | 3250 AM against 3205 DRM audio decoded from text-supported first-position words | A lag of −3.12 s (752 of 791 training words overlapped at this lag) also matched 521 held-out words, with spectral correlation 0.401. The highest of 199 displaced comparisons was 0.058. Removing counter 43869343 from the fit left the lag unchanged, and its 15 known first-position words scored 0.653. |
| Nov 28, 00:42 UTC | All four frequencies, independently recorded | Edogawa yielded usable 6100 AM and 6140 DRM. Yokohama lacked sufficient signal at 3250 and 3205 for either pairwise comparison. |

The first row uses the fixed acquisition preview and drain replay on the two original 30-second IQ files. Each individual capture produced 296 packets and 74 complete data units. All 53,144 shared packet bytes agreed. With the ordinary start and end, 3205 and 6140 yielded 68 and 69 data units, respectively, and combining them gave 69. The released IQ extracts were recorded at 12 kHz; the source metadata reports original acquisition at 192 kHz. A 12 kHz extract centred on one frequency omits its partner 40 or 45 kHz away. [06:17 receipt](nov27-digital.json) · [Digital comparison and replay](digital.py)

The second row establishes a shared programme in the 11:05 handoff. The −3.12 s is an offset between the files, which includes receiver and alignment delays. The comparison used supplied words backed by text checks and omitted concealed slots. The 06:17 music capture finished more than four hours before this AM capture began. [11:05 handoff comparison](known-1105/README.md)

## The four-frequency reception at 00:42 UTC

We recorded two ordinary 12 kHz IQ channels at each public receiver for 90 seconds. The four receiver timestamp ranges overlapped from **00:42:08.843 to 00:43:37.683 UTC**, or **88.840 seconds**. Each WAV holds 1,080,000 complex samples. No packet interval departed from nominal by a full sample. The stations' relative absolute clock error is unknown. [UTC ranges, sample counts and hashes](capture.json)

* **DRM.** On 6140 kHz, 198 CRC-checked packets had distinct assigned coordinates, yielding 48 complete data units and 13 complete groups. The first complete group was 43910137. On 3205 kHz there were zero decoded FAC or SDC blocks and no MSC output, so the shared-packet denominator was zero. An independent RF check found all three Mode B reference pilots on 6140 with a consistent −15 Hz offset; 3205 supplied no reproducible pilot triplet or cyclic prefix. [Packet and service results](nov28-digital.json) · [RF diagnostics](nov28-spectrum.json)
* **AM.** The waveform test fixed the lag search, polarity, drift fit and held-out windows using synthetic controls. On each of the three early windows the 6100 carrier was about 39 dB above the reference sideband bin level. On 3250 it was 1.2–1.7 dB, below the preselected 10 dB threshold. Correlation peaks across the ±4 s search were at most 0.031 in magnitude. The recordings yielded no reliable lag, so the later windows remained unscored. [AM results](nov28-analog.json) · [Synthetic controls](analog-self-test.json)
* **AM versus DRM.** The 6140 archive covers 988 physically complete EVS slots, including slots from two partial data units. None of its 21 observed counters occurred in the 90 available text-CRC label archives. There were zero independently supported clear words to use for an audio comparison from this reception. [Frame coverage](nov28-digital.json)

We repeated the two-channel AM reception on the **same Edogawa receiver** at 00:46 UTC. The files shared 88.960 seconds of receiver time. All 4,448 overlapping packet timestamps coincided after aligning the streams by 12,480 samples. The 6100 carrier passed the quality gate in all three windows; 3250 reached 6.4–7.8 dB and qualified in zero windows. The frozen comparator again gave an inconclusive result. This second period tests receiver location as a possible cause and supplies no simultaneous digital comparison. [Scores](same-site-am/analog.json) · [Capture hashes and times](same-site-am/verified.json) · [6100 IQ](same-site-am/edogawa-6100.wav) · [3250 IQ](same-site-am/edogawa-3250.wav)

An older, wideband IQ recording also supports the frequency assignment. In seconds 260–320 of the November 19 17:31 recording centred at 6140 kHz, a separate carrier was detected at 6099.9113 kHz on the receiver's nominal scale. Both sidebands contain corresponding modulation. This recording provides no simultaneous 3250 audio. [Carrier and sideband measurements](nov19-6100.json)

## Replay the independent four-channel recording

Download the four original IQ files. [6100 AM, Edogawa](edogawa-6100.wav) · [6140 DRM, Edogawa](edogawa-6140.wav) · [3250 AM, Yokohama](yokohama-3250.wav) · [3205 DRM, Yokohama](yokohama-3205.wav)

```sh
case_dir=examples/nov28/four-frequency
python "$case_dir/analog.py" --self-test
python "$case_dir/analog.py" "$case_dir/edogawa-6100.wav" "$case_dir/yokohama-3250.wav"
python scripts/demod_iq_window.py "$case_dir/edogawa-6140.wav" /tmp/kcbs-four-6140 --seconds 90 --reception-profile wiener --mlc-iterations 1
python scripts/salvage_msc_packets.py /tmp/kcbs-four-6140/msc.bin --transport-only --out /tmp/kcbs-four-6140-du
```

## Replaying two wideband Airspy files

Two stereo I/Q WAV files suffice if one contains both lower channels and one contains both upper channels for the same interval. Keep the original center frequency, nominal sample rate and start time for each. Derive signed offsets from the actual centers. For example, for centers **3227.5 kHz** and **6120 kHz**, use the following commands.

```sh
python scripts/extract_iq_channel.py lower.wav 3205.wav --offset-hz -22500
python scripts/extract_iq_channel.py lower.wav 3250.wav --offset-hz 22500
python scripts/extract_iq_channel.py upper.wav 6140.wav --offset-hz 20000
python scripts/extract_iq_channel.py upper.wav 6100.wav --offset-hz -20000
```

Run Dream and transport-only salvage separately on each digital file. Compare the resulting complete CRC-checked DUs by transmitted counter and phase.

```sh
python scripts/compare_dus.py left/data_units.npz right/data_units.npz --out comparison.json
```

The report lists one-sided coordinates, exact matches and each differing byte offset. If 311 distinct 716-byte DUs all match, the report will show **222,676 matching bytes** representing 124.4 seconds of transported slots. A 30-second capture cannot supply that many distinct DUs. The two per-frequency DU archives suffice to check the digital count. Testing the cross-programme claim also needs the corresponding AM interval and independently supported EVS slots. A comparison of two builds on a single file checks repeatability. Two RF receptions additionally test carrier-to-carrier agreement. [Wideband example on a previously unused source interval](../iq-holdout/README.md)
