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

## Locating an EVS export without a frame list

All 66,700 slots in the 3,335 complete 3205 kHz data units had distinct combinations of the mode and 21 directly transmitted payload octets. We looked up each of 5,840 slots from the independent Edogawa 6140 kHz recording using those 22 octets alone. We then compared the returned coordinates with Edogawa's recorded counter, phase, cycle and position. Both recordings had already been examined.

| True coordinate in the complete 3205 kHz data units | Edogawa slots | Unique correct coordinate | Unique wrong coordinate | Multiple candidates | No candidate |
|---|---:|---:|---:|---:|---:|
| Present | 5,680 | 5,680 | 0 | 0 | 0 |
| Absent | 160 | 0 | 0 | 0 | 160 |

Each frame position contributed 1,420 correct matches and 40 unmatched slots in the complete-DU check. Some incomplete 3205 kHz data units also retained every packet needed for a slot's 22 octets. Including these added 194 searchable slots across the recording. All 66,894 combinations remained distinct. The same 6140 kHz queries then returned **5,731 unique correct coordinates**, zero wrong coordinates and 109 unmatched slots. Among those 109, the member had some of the 22 octets for 13 slots and none for 96. [3205 kHz data](member-dus.npz) · [Accepted packets from incomplete units](partial-packets.npz) · [6140 kHz data](../../nov27/validation/swb-gsc/edogawa-data-units.npz)

A unique match establishes where the observed 22 octets occur within the indexed data. If a broadcast repeats these same octets and the index lacks the true occurrence, the reported coordinate can be wrong. The comparison leaves the eleven masked payload octets untested. A separate check on the published 12-second music excerpt located all 600 G.192 words at their listed coordinates on each frequency. The release labels the 150 first-position words as text-supported and the 450 other words as inferred. [Locator](../../../scripts/locate_evs_slots.py) · [Music excerpt frame list](../../nov27/frames.csv)

From the repository root, reproduce the comparison or substitute a supplied G.192 or EVS storage export.

```sh
corpus=examples/nov28/member-3205-20min/member-dus.npz
packets=examples/nov28/member-3205-20min/partial-packets.npz
peer=examples/nov27/validation/swb-gsc/edogawa-data-units.npz
python scripts/locate_evs_slots.py "$corpus" --peer-dus "$peer"
python scripts/locate_evs_slots.py "$corpus" --extra-packets "$packets" --peer-dus "$peer"
python scripts/locate_evs_slots.py "$corpus" --extra-packets "$packets" --export supplied.192.gz > locations.jsonl
```

The export report retains the zero-based input slot, its outcome and all candidate coordinates. Positions run from 1 through 4. Erasures and repeated input words keep their original slots. The final JSON line gives the counts after the entire input has been read.

The packet supplement contains the 14 ticks of the frozen 3205 kHz packet archive with one to three accepted packet ordinals. We preserved the ticks, packet order and receipt flags, and zeroed storage for rejected packets. All 41 included packet bodies match their original receiver rows, whose packet headers and CRCs passed. The parent archive's SHA-256 is recorded in `union.archive_sha256`. [Frozen receiver receipt](reception.json)

## Checking the contributor's November 28 handoff

The contributor supplied six purported EVS words for counter 43907925 and three clear text records from the same IQ recording. The six 33-byte rows concatenate to **exactly the first 198 bytes of the phase-zero data unit**, whose transmitted CRC is `0612`. They start at DU offsets 0, 33, 66, 99, 132 and 165. The first two bytes, `40 00`, are the DU header. Its five first-position mode bytes at offsets 2–6 read `52 51 58 51 51`; the corresponding 32-byte payloads start at offsets 7, 138, 269, 400 and 531. Each submitted row had zero matches on its 22 directly observable EVS octets in the 66,894-slot index. This identifies a framing error in the six-row sample. Only the actual decoder input can show whether the playback pipeline shared that error. [Member data units](member-dus.npz) · [DU layout](../../../scripts/render_continuous.py)

We replayed those six known wrong rows in slots 0, 4, 8, 12, 16 and 20, marking the remaining 54 slots as losses. A control used the same six P1 coordinates, deinterleaved with the contributor's submitted candidate. Each cold 16 kHz reference decoder run exited successfully and produced 19,200 samples. A trace of the wrong input showed **five of the six supplied words raised neither a bad-frame flag nor a bit-error flag**. Only slot 8, the third slice starting with `9F`, raised a bit-error flag. All six aligned control words had both flags clear. A third cold run containing only 60 loss markers exited successfully with zero samples. The six wrong rows demonstrate why PCM duration and a clean flag count cannot establish that the input words came from the claimed radio slots. [Known wrong G.192 input](misframed-43907925.192) · [Per-slot flags and input and output SHA-256 values](decoder-input-check.json)

To reproduce the stock output for the known wrong input, run `EVS_dec -q -no_delay_cmp 16 misframed-43907925.192 wrong.pcm` from this directory with the reference decoder on the path. The 38,400-byte PCM file has SHA-256 `606b2f1d962a8e78750b0cbaac4ceaa3ee16f4aeed083eeb9500e2a3b2380df0`.

| First text block | Counter / phase | Recomputed and submitted CRC | Physically received blocks |
|---|---|---|---:|
| 131723777 | 43907925 / 2 | `730B` | 7/7 |
| 131723805 | 43907935 / 0 | `7BE3` | 7/7 |
| 131723812 | 43907937 / 1 | `2612` | 7/7 |

Each literal contains a two-byte header, 92 bytes of UTF-16LE weather text, the transmitted record CRC and 16 fill bytes. The submitted candidate for counter 43907925 reproduces the first literal's opening 16 bytes from the received tail. We also compared the changes between already supplied text blocks to the changes in the on-air tails at adjacent phases of the same counter. All **13/13 pairs** agreed on all 16 bytes, including the join between the second and third records. Shifting the radio coordinates one counter earlier or later gave 0/13 complete agreements in either direction. The independent Edogawa reception started at 43908156, after these examples. The handoff contains three of the reported 286 literals and six of the reported 45 example words. [Text parser](../../../scripts/parse_text_records.py) · [Reproduce these checks](check_member_handoff.py)

All 30 named counter examples have three complete DUs in the member IQ. The last observed counter is 43909062. The full counter lists and pre-decoder export were absent from the note. If 397 counts all fill candidates and 101 counts fill-only candidates, 296 overlap the 686 phrase candidates, giving 787 distinct candidates. The reported 5,955 words equal 397 × 15. Establishing which words reached the decoder requires the input stream or a per-slot receipt.

With the original contributor note, run the following from the repository root.

```sh
python examples/nov28/member-3205-20min/check_member_handoff.py skgsara-crosscheck-20261128.md
```

### Comparing the handoff with the earlier blind predictions

Before this handoff arrived, the IQ-only receiver had published predictions for counter 43907925, the first complete group in the member recording. The counter was absent from its frozen inventory. Replaying the three archived DUs reproduces the published per-slot evidence SHA-256 `433b76398e950d2dc4a329e1c09cbc88e8fad5b6d50bf7e73ef964de7198711d`. We compared **every conditional field at P1 and P2** with the value computed using the contributor's single submitted candidate and the published word layout. All nine fields target the first payload octet. The text record with CRC `730B` supports the submitted comparison data. [Original IQ result](primary.json) · [Comparison values for all eligible fields](candidate-43907925-early-fields.csv)

| Position and zero-based slots | Word bits, MSB first | Allowed by the frozen receiver | Value from submitted candidate |
|---|---|---|---|
| P1, 32 | 8–9 | `00`, `01`, `10` | `00` |
| P1, 36 | 8–9 | `00` | `00` |
| P1, 48, 52, 56 | 8 | `1` | `1` at all three |
| P2, 17 | 8–9 | `00` | `00` |
| P2, 33 | 8–9 | `00`, `10`, `11` | `11` |
| P2, 49, 53 | 8 | `1` | `1` at both |

Seven fields had a single allowed value, covering nine individually predicted bits. All nine bits agreed. Two further fields excluded just one pair each. The submitted values fell within both allowed sets. The nine fields depend on only four distinct bits of one candidate, two for P1 and two for P2. This measures agreement with that candidate on this counter. It provides no independent estimate of clear-bit accuracy. The P3 and P4 predictions still lack labels here. The IQ-only score remains zero complete clear words out of 60.

```sh
case_dir=examples/nov28/member-3205-20min
python scripts/project_evs_group.py "$case_dir/data_units.npz" --counter 43907925 --field-checks > /tmp/43907925-fields.json
python scripts/compare_evs_evidence.py /tmp/43907925-fields.json "$case_dir/candidate-43907925-early-fields.csv" --bit-labels
```

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

The 3,335 accepted DUs also give a way to test whether three published EVS checks for payload octets 24 and 27 apply to this recording. The checks require a narrowband transition with mode `13`, wideband GSC AUDIO, or one of the specified super-wideband ACELP modes with the BWE selector. All three counts were zero among the 16,675 received mode octets at each of P1, P2, P3 and P4. The counters with all three phases accounted for 16,530 slots per position. No late bit was scored by those checks. [Mode requirements and stock examples](../../nov27/validation/late-payload/README.md) · [Narrowband p24 rule](../nb-transition/README.md)

```sh
python examples/nov27/validation/late-payload/count_modes.py examples/nov28/member-3205-20min/member-dus.npz
```

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
