# KCBS-2 DRM decoder

Tools for decoding the **KCBS-2** Digital Radio Mondiale shortwave broadcast
from KiwiSDR IQ WAV and signed 8-bit IQ recordings. The receiver extracts
DRM service information, checks received data packets, recovers Korean
scrolling text and decodes supported audio frames using the 3GPP EVS reference
decoder. Recovery varies with radio reception and the available text evidence.

This work builds on KoryoFront’s KCBS-2 receiver and Martyn’s independent
KCBS DRM analysis. KoryoFront documented the transport layout and shared
the March recordings in collaboration with Martyn. Martyn (martynw) contributed the variable-length text
record parser, November data and a March satellite-audio check of the EVS
framing. Amateur operators contributed the November 19 and November 27
recordings used below. [KoryoFront’s original decoder](https://github.com/KoryoFront/kcbs2-drm-decode) ·
[Martyn’s KCBSDRM](https://github.com/martynw/KCBSDRM) · [Credits](docs/CREDITS.md)

Planned receiver integrations are listed in the [KiwiSDR, Dream and DecDRM roadmap](docs/roadmap.md).

We compared 3250/6100 kHz AM and 3205/6140 kHz DRM using simultaneous
four-channel IQ. The November 27 11:05 handoff also supports a shared AM/DRM
programme on 521 held-out first-position EVS words. The new November 28
four-channel recording had too little low-frequency signal to repeat that
comparison. A later group listening report describes different AM and DRM programmes.
The exact interval of that observation is unknown. [Frequency pairs, IQ files and replay tests](examples/nov28/four-frequency/README.md)

On a separate 120-second IQ holdout the SWB ACELP transition tag gave 228
conditional hidden-bit predictions across 35 complete groups. A historical
P2 check agreed on 230 of 231 exact pairs. Replaying the disputed counter from
its original IQ confirmed both received bytes used by the predictor.
[Blind reception, scores and counterexamples](examples/nov28/swb-transition/README.md)

A frozen IQ-only test on a previously unused 22-second interval received all 60
slots at counter 43288733, with zero complete clear words. Across 16 complete
groups, the stock EVS HQ mode predicted one hidden bit in 25 words. A separate
narrowband ACELP rule constrained payload octet 24 in three stock sender words.
Its required mode appeared in zero of 24,280 archived broadcast slots.
[IQ holdout and checked bits](examples/nov28/iq-holdout/README.md) ·
[ACELP control and on-air coverage](examples/nov28/nb-transition/README.md)

The current blind receiver milestone uses raw IQ as its only input and aims
to recover all 60 EVS words of an unseen, CRC-good counter. The November 15
test fixes the target. Its protocol covers checks against evidence held
back from the same broadcast and an optional comparison with a clear export.
[Four-position milestone and target receipt](examples/nov15/validation/README.md)

For **43865914**, the handoff's TCX spectrum check accepts all 15 known
first-position words even after the low bit of payload byte 30 is changed
in every word. The second position remains unresolved.
[November 28 search update and same-counter controls](examples/nov27/validation/tcx-zero-pair/43865914-review.md)

On November 28, three minutes of **6140 kHz** IQ yielded 85 complete groups.
The first complete counter, **43908156**, had all 60 slots and zero complete
clear EVS words. Across two recordings, a prediction of four directly
transmitted bits agreed in all **1,871** eligible SWB GSC INACTIVE slots.
The data include one counter with 15 observations at each of the four positions.
[IQ recording, field checks, stock encoder examples and replay](examples/nov27/validation/swb-gsc/README.md)

The group projector can also check one required zero bit in a particular
SWB GSC pulse-codebook layout. The bit matched in 274 eligible development
words. A fresh 00:28 UTC recording yielded 32 complete groups with zero
eligible padding checks and eight matches on the four-bit INACTIVE field.
[Per-slot field report, new IQ and reproducible controls](examples/nov28/gsc-fields/README.md)

Stock ACELP examples reproduce the exact one-bit ambiguities at payload
bytes 24 and 27. In a narrower wideband GSC case, the first 128 bits
correctly predicted two bits of byte 27 in nine stock words. Neither
of the two eligible archived P1 prefixes selected that case.
[Late payload checks, original encoder outputs and fresh 6140 kHz IQ](examples/nov27/validation/late-payload/README.md)

On a held-back minute of 6140 kHz IQ, two directly received EVS fields each
singled out the published frame order from 96 alternatives across 42 complete
groups. The first group alone left two orders possible. Its 60 slots were
present and all 60 complete clear words remain unresolved.
[Frame-order test and replay data](examples/nov27/validation/frame-order/README.md)

In a fresh three-minute 3205 kHz recording from 7L4IOU Edogawa, a following
ACELP frame narrowed the speech class of its predecessor four times. All four
agreed with the withheld, directly received bits. At the preselected counter
43903388 the check abstained and all 60 complete-word values remain unresolved.
[IQ-only check, capture and replay](examples/nov27/validation/acelp-class-history/README.md)

For SWB HQ mode `F9`, the clear mode octet predicts one bit of masked
payload octet 0. It agreed with 175 first-position and 17 second-position
words whose supporting text record covered the relevant byte in its header
or body. The six unresolved late octets are outside this field.
[Mode bits, archive comparisons and IQ replay](examples/nov27/validation/hq-class/README.md)

A fresh three-minute **6140 kHz** IQ recording is available in full. The
frozen receiver recovered 35 complete groups. At the first unseen counter,
43904973, it received all 60 slots. Its conservative projection marked
10,560 bits as directly received and left the other 5,280 unresolved.
[Download the IQ and reproduce all 35 groups](examples/nov27/validation/rf-iterations/README.md)

## November 27 dual-frequency recording

**행복한 내 나라 (*My Happy Country*)**, performed by the Wangjaesan Light Music
Band, aired on KCBS-2 at **06:17:22 UTC** (14:17:22 Beijing, 15:17:22 Pyongyang).
Amateur receivers on **6140 and 3205 kHz** captured the same 30 seconds.
Each reproduced all 264 packets in the contributor’s demodulated file. The
two frequencies agreed byte for byte on all 292 packets received on both.
Together they yielded 300 distinct packets and 75 consecutive data units.
[1991 CD, track 1](https://archive.org/details/wangjaesangyongumaktan-che1chip) · [November results and identification](docs/november-2026.md)

**Listen to the radio capture.** Of 1,500 EVS frames, 355 used mask bytes
supported by received text checksums and another 795 used experimentally
inferred mask bytes. The stock decoder concealed the remaining 350.
It played 603 consecutive frames without concealment from **5.16 to 17.22 s**.
The short WAV covers 600 of those frames. Separately archived FM and CD
recordings supplied comparison audio during the analysis. The listening
files contain only the decoded radio stream and the decoder’s concealment.
[Full 30-second MP3](examples/nov27/radio.mp3) ·
[12 seconds with every frame supplied](examples/nov27/fully-supplied-12s.wav) ·
[Frame-by-frame evidence](examples/nov27/frames.csv) · [Mask validation](docs/nov27-mask-validation.md)

To reproduce the 16 kHz mono WAV from the included receiver data, install the
Python requirements and build the EVS reference decoder as described in the
[March quickstart](#play-or-render-the-bundled-1906-recording). Run this command from the
repository root.

```bash
python scripts/render_measured_evs.py examples/nov27/receiver \
    --masks dumps/nov27-measured-masks.json --received-span --out work/nov27-replay
```

The renderer checks the recorded data-unit hashes against the capture-specific
mask table. It writes `programme.192` (G.192 binary EVS frames), `programme.wav`
and `coverage.json`. The expected SHA-256 of the G.192 file is
`2ae4c7d6f186558db6f96cfc9c4c613e4d9702175f3980c855784fb3b4b32738`.

Seven later November 27 recordings on 6140 and 3205 kHz yielded 276 checksummed Korean text records and 10,977 complete EVS frames across 90,920 slots. In an eight-minute recording received last, previously saved bulletin templates recovered 105 records that passed the new recording's own checksums. [Per-recording results and verification](docs/november-2026.md#seven-additional-november-27-recordings)

## November 19 recordings on 6140 kHz

Both recordings identify service `A00002`, 조선중앙제2라지오방송. Separate
passages matched the released performances at the times predicted from the
first match. The excerpts preserve the original time gaps and use standard
EVS concealment for missing frames.

| Capture filename time (likely UTC+8) | Song and performance | Radio excerpt | Frames supplied |
| --- | --- | --- | ---: |
| 17:09:40 | **그리움은 나의 행복** (*Longing Is My Happiness*), Jo Kuk Hyang and Kim Yu Kyong with the Moranbong Band | [32.4 s MP3](examples/nov19/longing-is-my-happiness.mp3) | 750 / 1,620 |
| 17:31:39 | **어머니의 목소리** (*Mother’s Voice*), Ryu Jina with the Moranbong Band | [103.2 s MP3](examples/nov19/mothers-voice.mp3) | 2,583 / 5,160 |

For an uninterrupted comparison, the short solo WAV supplies all 420
consecutive frames. [8.4-second radio WAV](examples/nov19/mothers-voice-fully-supplied-8s4.wav) ·
[Duet reference](https://archive.org/details/moranbong-band-longing-is-my-happiness) ·
[Solo reference](https://archive.org/details/moranbong-band-mothers-voice) ·
[November 19 mask table](dumps/nov19-measured-masks.json)

For two synchronized 16 kHz mono PCM16
reconstructions beginning on a fully recovered frame, this command combines
the received-frame and listening renders and interpolates the spectrum between
neighboring received frames. All output samples are derived from the radio
inputs. Sections silent in both input files remain silent.

```bash
python scripts/interpolate_evs_audio.py role0-excerpt.wav listening-excerpt.wav rf-interpolated.wav
```

## Play or render the bundled 19:06 recording

[**Download the quieter listening WAV**](https://github.com/KoryoFront/kcbs2-drm-decode/releases/download/march-19m-quiet/KCBS2_MARCH_UNVERIFIED_REPLAY_QUIETER_32k.wav)
(19:06, mono 32 kHz PCM, −24.4 LUFS). It is a reconstruction from three adjacent
Daegu 3205 kHz captures from March 16, 2026, not a verified broadcast decode.

To reproduce it from the bundled MSC dumps without rebuilding the DRM demodulator:

1. On Linux or Windows with WSL2 Ubuntu, install Python 3.10+ and run
   `pip install -r requirements.txt`.
2. Obtain the 3GPP TS 26.443 EVS floating-point reference source (not bundled)
   and place it at `work/ref/evs/src/c-code`. Build with:

   ```bash
   python scripts/build_evs_gcc_independent.py --out work/evs_gcc_independent
   ```

3. From the repo root in Git Bash, run:

   ```bash
   python scripts/kcbs_decode_fast.py recordings/*_iq.wav --out work/march_1906 \
       --replay-nearby --attenuate-db 2.2
   ```

This writes `KCBS2_MARCH_UNVERIFIED_REPLAY_QUIETER_32k_25463783-25464737.wav`
and `report.json`. Use a new `--out` directory for each render.

- **865 of 955** timeline groups (90.6%) have a CRC-supported 16-byte mask prefix.
  That gives **12,975 fully unmasked frame slots out of 57,300**, not 90.6%
  verified audio.
- Within a keyed four-frame cycle, the first slot is fully unmasked and the
  second has six substitute bytes. With `--replay-nearby`, the third copies the
  second, and the fourth copies the next fully unmasked frame when available
  or falls back to the second. These copies do not restore missing frames.
- The quieter edition uses a fixed **2.2 dB attenuation** relative to the raw
  replay render, with no compression or peak limiting.
- Counter gaps retain their duration. Gaps of up to four groups use decoder
  concealment; longer gaps are digital silence with 20 ms fades at the edges.
  The longest silence is **3:18–4:00**. `--merge-gap 0` silences every gap.
- Omit `--replay-nearby` to use decoder concealment in the last two slots of each
  keyed cycle instead. `--rate` accepts 16000, 32000, or 48000. `--fresh` ignores
  the bundled dumps and requires patched Dream.

## Record and decode your own captures

Use **IQ**, not the KiwiSDR’s audio output. A good starting point is
`hl5ntr.ddns.net:8074` in Daegu on **3205 kHz**. **6140 kHz** can carry the same
payload and can be better under different reception conditions. Our pooled
windows yielded 76% CRC-good on 3205 and 30% on 6140; those are sample results,
not intrinsic properties of the frequencies. Daejeon (`hik.iptime.org`) and
Japanese receivers are also useful for simultaneous captures. Current reported DRM
hours are **05:00–23:00 KST** (20:00 UTC the previous day to 14:00 UTC), confirmed
on 2026-11-26. A failed lock does not prove the transmitter was off-air.

```bash
python kiwirecorder.py -s hl5ntr.ddns.net -p 8074 -f 3205 -m iq \
    --tlimit=1800 --station=drm -d ./captures
```

`kiwirecorder.py` is from [kiwiclient](https://github.com/jks-prv/kiwiclient).
For new IQ captures, install FFmpeg and build patched Dream with `bash build/build.sh`
in WSL Ubuntu (see [build/README.md](build/README.md)). The patch writes the MSC
stream via `KCBS_DUMP_MSC`. The general pipeline demodulates the IQ, salvages
packets, and writes `text/kcbs2_text.txt` and experimental audio:

```bash
python scripts/kcbs_decode_audio.py captures/mycapture_iq.wav --out work/mycapture
```

On 2026-11-27 at 20:28 UTC, JL1EDU in Yokohama supplied live IQ at
**3205 kHz**. The public UberSDR endpoint granted `iq48` through
`/connection`. We recorded its version 4 WebSocket stream and used the
upstream PCM decoder to write 48 kHz stereo PCM16 WAV, with I and Q as the
two channels. The WAV goes into the same decoder command above.
[JL1EDU receiver](https://ubersdr.jl1edu.freeddns.org/) ·
[UberSDR IQ protocol](https://github.com/madpsy/ka9q_ubersdr/blob/8134b1fa5d989de776999ae80145c9a0b8d46e2e/clients/iq-recorder/main.go) ·
[PCM decoder](https://github.com/madpsy/ka9q_ubersdr/blob/8134b1fa5d989de776999ae80145c9a0b8d46e2e/clients/python/pcm_v4.py)

To record a new WAV, install `websockets>=15` and point the recorder at a local
checkout of the linked UberSDR source. The command prints a JSON receipt with
the actual sample duration, wall time and receiver timestamp checks. An early
disconnect leaves the samples received in the WAV and returns a nonzero exit status.

```bash
python scripts/record_ubersdr_iq.py https://ubersdr.jl1edu.freeddns.org \
    --frequency-hz 3205000 --seconds 180 --ubersdr-source ./ka9q_ubersdr \
    --out jl1edu-3205.wav
```

The first three minutes identified service `A00002` (**조선중앙제2라지오방송**)
and yielded one complete data unit with a verified counter. The next 20 minutes
of IQ span two files with an 8.620-second reception gap. The baseline recovered
120 complete groups. Combining CRC-checked packets from additional receiver
passes raised that to 126 distinct groups. A simultaneous three-minute 6140 kHz
recording confirmed the same service ID and yielded no MSC payload.

Group `43897717` arrived near 20:34 UTC. All 60 received mode octets indicate
TCX20. An independently sourced EVS export at this counter would allow a
bit-for-bit check of the clear audio payloads.
[Reception counts and SHA-256 hashes](examples/nov27/jl1edu-2028-reception.json)

To reproduce that group, demodulate the included 24-second sample with the
[patched Dream receiver](build/README.md). In the reference run, records
32–34 of the resulting `msc.bin` (counting from zero) matched the three
published records byte for byte. All 12 packet CRCs and all three data-unit
CRCs passed. [IQ sample](examples/nov27/jl1edu-3205-43897717-iq12.wav) ·
[Three received MSC records](examples/nov27/jl1edu-3205-43897717.msc.bin)

```bash
python scripts/demod_iq_window.py examples/nov27/jl1edu-3205-43897717-iq12.wav \
    work/jl1edu-43897717 --seconds 24
```

To see which EVS bytes are directly available at a counter, use the
CRC-checked data units from the same receiver pass. The example below
starts from the 24-second recording demodulated above.

```bash
python scripts/salvage_msc_packets.py work/jl1edu-43897717/msc.bin --transport-only \
    --out work/jl1edu-43897717/units
python scripts/project_evs_group.py work/jl1edu-43897717/units/data_units.npz \
    --counter 43897717 --format tsv
```

The output keeps all 60 slots in phase, cycle and position order. Each
row contains the mode octet followed by 32 payload octets. Hex values
are directly transmitted bytes, `??` marks a received octet whose clear
value is unknown, and `--` marks a phase without a verified data unit.
The JSON output also counts those slots and the total number of directly
available bits. A fully received group exposes 10,560 of 15,840 bits
under this layout. Two RF receivers can independently compare those
10,560 bits.

On a later 3205 kHz transmission, two receivers in Yokohama and Tokyo
independently reproduced all 10,560 directly comparable bits at counter
`43900392`. The original IQ excerpts and replay commands are available
for both receivers. [Paired IQ test](examples/nov27/validation/paired-43900392/)

The published November 19 and 27 mask tables and the November 27 text
archive contain no entry for `43897717`. With all 60 slots physically
received, replay using this evidence supplied zero complete EVS words
at each of the four positions. The G.192 stream contains 60 erasures.
The stock EVS decoder returned zero PCM samples. The renderer marked the
elapsed 1.2 seconds with silence and recorded its source in the
[coverage report](examples/nov27/validation/jl1edu-43897717/coverage.json).
To reproduce the report from the 12 received packets, run from the
repository root after building the EVS decoder.

```bash
case_dir=examples/nov27/validation/jl1edu-43897717
run_dir=work/jl1edu-43897717-replay
mkdir -p "$run_dir"
cp "$case_dir/packets.npz" examples/nov27/receiver/keys.npz "$run_dir/"
python scripts/render_measured_evs.py "$run_dir" --masks dumps/nov27-measured-masks.json \
    --received-span --excerpt 43897717 43897717 --decoder work/evs_gcc_independent/EVS_dec \
    --out "$run_dir/render"
cmp "$case_dir/coverage.json" "$run_dir/render/coverage.json"
```

The pipeline can resume in the same output directory. It checks the selected
MSC dumps and decode options before reusing their combined result. When the
input set changes, earlier products are retained under `previous-runs/` and
the receiver processes the new set.

The text output distinguishes CRC-supported records from heuristic candidates.
`--allow-candidate-keys` explicitly permits heuristic keys only when no full
CRC-supported prefixes are available. The `--montage` timeline respects the
same rule and labels heuristic audio `HANGUL_CANDIDATE`, never `CRC_PREFIX`.

The same pipeline accepts headerless signed 8-bit IQ directly. For the two
0.912 Msps captures, run this from the repository root with their local paths.
Set `KCBS_DREAM` to select a specific KCBS-patched receiver. Otherwise the
Linux pipeline checks `work/dream-build/dream` for a prebuilt receiver,
then uses the receiver built at `build/dream-src/dream`. The EVS binary belongs
at `work/evs_gcc_independent/EVS_dec`. Windows uses the WSL receiver.

```bash
python scripts/kcbs_decode_audio.py capture1.cs8 capture2.cs8 --sample-rate 912000 --phrase-keys --montage --out work/cs8
```

`--phrase-keys` tries eight-character fragments from the contributed November
bulletins. Each group gets one mask proposal before the decoder checks the
received text CRC, header and padding or fill. A mask column occurring only in
padding or fill is supported by that structure. Existing CRC-supported prefixes
remain available. This helps on short weather recordings where the text does
not complete a carousel repetition.

`--offset-hz` selects a channel away from the recording center (station minus
center, in Hz). The receiver checks the fixed idle message and its CRC when it
is present. To export just the 48 kHz stereo I/Q for Dream, use
`python scripts/resample_iq.py capture.cs8 capture48.wav --sample-rate 912000`.

To combine simultaneous length-prefixed MSC dumps without re-demodulating:

```bash
python scripts/salvage_msc_packets.py receiver-a.msc.bin receiver-b.msc.bin \
    --out work/msc_salvage
```

Salvage merges packet-CRC-good payloads at the same counter and phase, rejects
conflicting copies, and requires the reassembled data unit to pass its CRC.
The March fast path instead uses complete CRC-good groups in the cached dumps.
On the longest bundled March capture, both paths independently return the same
708 counters and data units; salvage adds zero, so it does not explain the
reported 702 count. Martyn’s 702 groups are a byte-identical subset of those
708; his dump lacks the other six. For June, combining CRC-good packets across the two
frequencies yields **410 complete groups instead of 408**.
The two added groups are not additional verified text prefixes.

## Render the contributed November recording

[**Download the quieter 17:40.8 listening WAV**](https://github.com/KoryoFront/kcbs2-drm-decode/releases/download/november-quiet-review/KCBS2_NOV25_UNVERIFIED_QUIET_17m40_32k.wav).
It uses the same counter span as the previous November 24 UTC / November 25 KST
sample. This time **671 of 884 timeline groups** have full 16-byte prefixes checked
against repeated records. This is group coverage, not a percentage of verified
speech or music. Role 2 is concealed; role 3 can replay the next fully unmasked
frame. The copy measures **−26.7 LUFS**, with a **−2.6 dBTP** true peak and
11 silent gaps of their original durations. The March release is unchanged.

[Martyn’s contribution](contrib/kcbsdrm/README.md) supplies six matching groups of
dumps, prefix archives, record reports and Korean text. All **3,517** exported full prefixes matched complete received groups by
counter; the six captures contain **4,421** complete groups in total. Rechecking header/body CRC, padding, fill, and matching records
at the same position in the carousel kept **3,007 full prefixes**. Repeat agreement
is an extra consistency check, not authentication; the exports are not a source
of keys for future broadcasts.

With FFmpeg and the EVS build from the March quickstart, reproduce the release
from the contributed data (Git Bash):

```bash
python scripts/salvage_msc_packets.py \
    contrib/kcbsdrm/reference/sf_2026-11-25_04*3205_hik.bin --out work/november
python scripts/review_supplied_records.py \
    --data-units work/november/data_units.npz \
    --keys contrib/kcbsdrm/keys/keys_2026-11-25.npz \
    --repeat-blocks 969 --out work/november_review
python scripts/render_supported_nonidle.py \
    --groups work/november/groups.npz --keys work/november_review/keys.npz \
    --timeline --start-counter 43679908 --end-counter 43680791 \
    --loss-policy future --attenuate-db 2.2 --out work/november_audio
python scripts/finish_listening_wav.py \
    work/november_audio/NONIDLE_CRC_PREFIX_UNVERIFIED_FUTURE_TIMELINE_32k.wav \
    --report work/november_audio/report.json --gain-db 2.2 \
    --out work/november_audio/KCBS2_NOV25_UNVERIFIED_QUIET_17m40_32k.wav
```

Use a new output directory or filenames for reruns. Omit `--timeline` for an
excerpt reel with half-second separators. `--loss-policy replay` matches the
quieter March playback policy; `--loss-policy plc` uses concealment instead of
frame replay. None of the options recovers the missing payload or guarantees
natural music. Each render writes a counter and timing report.

To check for a pre-programme RF pulse from two overlapping recordings, use
`python scripts/rf_pulse_check.py --help`. In one June pair on 3205 and 6140 kHz
no shared pulse persisted across adjacent 40-second windows of the common
interval. A planted 0.8 Hz modulation passed the same check. A listener reported
pre-start pulsing. This must not be equated to the narrow component in the March
EVS output below.
This two-frequency power test does not check what is audible in programme
content. A confirmed audio pulse can help align recordings of the same programme;
it does not recover missing frame bytes. The capture layout audit reports exact
mode-edge counters without mistaking gaps for transitions:

```bash
python scripts/audit_capture_layout.py work/mycapture/salvage/groups.npz
```

## Container and partial mask

- An MSC record has a four-byte little-endian length, then normally four 182-byte
  packets. Each packet has a one-byte header, 179 payload bytes, and a two-byte
  CRC. The concatenated 716-byte data unit (`du`) has its own CRC at `du[714:716]`.
  CRC-16 uses polynomial `0x1021`, initial value `0xFFFF`, and final XOR `0xFFFF`.
- Three data units with `du[1] >> 4` equal to 0, 1, and 2 make a 1.2 s group.
  The big-endian counter in phase 0 at `du[664:668]` increments once per group.
- Each data unit has 20 nominal 20 ms frames. The four 32-byte payloads in cycle
  `c` start at `7`, `40`, `73`, and `106` plus `131*c`, for `c=0..4`. The
  first mode byte is at `du[2+c]`; the others immediately precede their payload.
- The nominal mask positions in each frame are payload bytes 0, 3, 6, …, 30.
  For a masked position the receiver applies
  `plain[3*j] = cipher[3*j] XOR ks[11*role+j]`, where
  `role = frame_index % 4`. Each 1.2 s group repeats the same mask across
  fifteen cycles. The 21 intervening bytes are received in the clear.
- In the fourth frame, payload byte 30 behaves as an additional clear byte.
  Its data-unit offsets are 136, 267, 398, 529 and 660. A model trained on
  verified first-position plaintext chose a zero mask for this byte across
  819 held-out groups, with a similar distribution of ranks for naturally
  clear first-position controls. Checks on other dates, frequencies and EVS
  coding modes independently support this interpretation. The 131-byte cycle
  contains 43 complete triplets and a two-byte remainder. The observed byte
  lies at the start of that remainder. In a cross-date check, the fourth-position
  byte matched a text-supported first-position comparison with the same local
  codec fields in 438 of 1,665 cases, versus 58 in a shifted control. Of the
  438 matches, 402 came from one GSC mode. The transmitter implementation is
  unknown. [Fourth-position byte tests](examples/nov27/validation/position-four-tail/README.md)

The text tail `du[698:714]` shares `ks[0..15]` with the audio layout. This covers
all 11 role-0 mask bytes and five of role 1’s 11. Counting the fourth-position
terminal byte as clear leaves **27 unknown mask bytes per group** in the current
transport model: six in role 1, eleven in role 2 and ten in role 3. The earlier
44-position model counted 28. The programme-reference experiments produce
additional inferred role-1 frames in selected November 19 groups. The packet
CRC checks their received masked payload. A one-step change of counter changes about 64 of the
128 known bits on average; that does not identify AES-CTR, establish cipher
strength, or locate a secret in receiver hardware. Byte-identical payloads across
two transmitters support a common upstream masked stream.

The November 25 recording contains the same complete, CRC-checked bulletin
record at two different counters. An identically aligned 48-byte passage
spans the three phases of counters 43679914 and 43680560. All 16 published
mask-prefix bytes differ between those counters. In each copy all 16 bytes
also change at the next counter, while the same 92-byte record body is still
being sent. The bulletin text and its alignment alone cannot determine the
prefix. Changes can occur within a record.
[Replay this comparison from the archived broadcast](examples/nov27/validation/hq-class/check_bulletin_repeat.py)

**Opaque trailer.** This layout immediately before the text tail matched all **2,310** complete
groups checked across the March, June, November 24, and November 25 samples:

| Phase | Layout, starting at `du[662]` |
|---|---|
| 0 | 2 zero bytes, 4-byte counter, `du[668:698]` (30 variable bytes) |
| 1 | 3 zero bytes, `du[665:698]` (33 variable bytes) |
| 2 | 2 zero bytes, `du[664:697]` (33 variable bytes), 1 zero byte |

The resulting 96-byte blocks are distinct within each sample, with bit-one
fractions from 0.4994 to 0.5022. Their function is unknown. Simple mappings tested so
far did not produce supported recovery of additional mask bytes.

## Text recovery and validation

**Idle text:** In bundled March groups the phase-0 plaintext tail is sixteen
`0xFF` bytes. The mask derived from it makes phases 1 and 2 match the framed
`TextMessage is sending...` placeholder and its CRC. This validates the 16-byte
prefix, not codec identity or the resulting audio.

**Scrolling text:** The implemented path uses `0xBB` fill and repeated text to
recover prefixes. It checks a common 112-byte layout: header `05` or `85`, then
`(seq << 4) | 0x0C`, 92 bytes of UTF-16LE text, a big-endian CRC over the header
and text, and 16 bytes of `0xBB` fill. CRC is an integrity check, not authentication.
Hangul density is only a heuristic: even the fill word `0xBBBB` counts as a Hangul
syllable, and forcing a fill biases this score.

**Variable-length records:** `scripts/parse_text_records.py` checks already-available
plaintext using the reported block-aligned header, length `((b0 & 7) << 4) | (b1 & 0x0f)`,
last-record flag, sequence number, CRC, zero padding and a fill block after a non-final
record. The optional same-length `--known-bytes` map (0 or 1 per input byte) prevents
unknown bytes from being treated as evidence. Title and item signalling are not parsed.

```bash
python scripts/parse_text_records.py plaintext.bin --known-bytes known_mask.bin
```

In the contributed archives, the parser rechecked **1,324** full records,
including **42** final records. Observed bodies span 8–92 bytes rather than a
fixed 92. The reported ~93% figures count records; the group counts above use
a different denominator. `review_supplied_records.py` only narrows existing
masks to observations that pass the review; it never infers new mask bytes.

Observed carousel repetition depends on the recording: **969**, **700**, and
**878** 16-byte blocks (6:27.6, 4:40, and 5:51.2 at 0.4 s per block). The item
toggle can require two loops for byte-identical headers, so the repeat check
compares body, sequence, final flag and position without requiring the toggle.

## Audio evidence and limitations

- The `[mode byte][32-byte payload]` reading gives 264 bits, consistent with
  EVS 13.2. A traced GCC decoder flagged **0 of 12,975** March role-0 frames.
  Across 24 trials per control, shuffling each keyed byte column within the same
  exact mode flagged **2,983–3,117**; moving whole keyed vectors within mode
  flagged **2,963–3,116**; draws from matched bit frequencies flagged
  **3,154–3,329**. November gave **0/255** versus **17–29** for the column
  shuffles. Modes, clear bytes, frame positions and erasures were unchanged.
  So uniform wrong-key statistics do not explain the separation in these tests.
  Flags are not a universal check: some shuffles of known EVS controls also had
  zero flags. Independent song matches for the two November 19 captures are documented above.
- The candidate did not beat wrong-key controls against the simultaneously
  recorded November comparison stream. Its programme identity was not established
  by the channel label alone. At the selected lag, held-out correlation was
  **−0.025**. Known EVS audio provided a positive control; a successful round-trip
  validates the build, not that the broadcast uses EVS.
- Martyn’s March spectral result reproduces independently on both raw dumps.
  From 20–80 s on the longest capture’s counter timeline, a role-0-only EVS
  render has a **1,000 Hz** peak containing **98.15%** of the 100–7,000 Hz
  power in the 980–1,020 Hz band. Wrong-prefix and exact-mode shuffled controls
  show 0.77% and 3.20–4.24%, respectively. The candidate then falls to roughly
  six PCM counts RMS at 100–220 s. This is evidence for EVS on those particular
  inputs. It does not identify a separate satellite programme or the usual
  pre-start cue. The satellite WAV is not bundled, so its reported correlation
  was not checked. The RF mode edge is counter **25464052**, phase 0, zero-based
  slot 1 (82.82 s from the longest capture’s first group, 322.82 s in the merge).
  `scripts/audit_march_contribution.py` reproduces the RF-only test.
- The original role-1 continuity pilot inserted a constant plaintext byte across
  different frames. The corrected `scripts/role1_key_search.py --pilot` plants
  one shared XOR mask and starts a fresh EVS decoder for every candidate. In
  a synthetic encode of a 1.2 s excerpt from *Longing Is My Happiness*, the
  true mask ranked first at four of six individually hidden positions. The
  other two ranked seventh and 104th. Every candidate passed the decoder's
  flag checks. The other five byte values were supplied in each trial.

## Playback controls

The replay method improved held-out eSTOI from **0.437 to 0.520** on four genuine
EVS speech excerpts with the March loss pattern. The metric compares against the
full EVS encode, not the broadcast. Three synthetic instrumental controls showed
no meaningful gain in spectral similarity. Music in the listening copy remains
rough on these controls. The November 19 music comparisons above use independent recordings of the recovered performances.

To benchmark your own local speech material after building the codec, install
FFmpeg and `pystoi`, then run:

```bash
python scripts/benchmark_loss_handling.py --speech local_speech.wav --out work/replay_controls
```

The benchmark needs at least 18 minutes of audio for the selected offsets. It
encodes independent controls locally, compares seven strategies, and keeps its
selection and held-out slices separate.

## Can this run live?

The audio stage is fast enough to prototype. On one desktop, a 17:40.8 render
with the prefixes already on disk took about 30 seconds. An offline 16-group
check took a median **0.15 s** to decode each **1.2 s** group, but opening WSL for
one group stalled for **4.84 s**. A live listener would need a persistent decoder
and a playout buffer, with missing groups passed as losses on the original clock.
These are decoder measurements, not an end-to-end live test.

A live receiver also needs stable RF lock and usable prefixes for the incoming
counter before playout. The November archives apply only to the recordings they
match. For new scrolling-text broadcasts the demonstrated workflow is delayed
review and playback, not immediate audio. No live capture is started by these
scripts. The reported operating hours remain **05:00–23:00 KST**.

## Tests and licensing

```bash
python -m unittest discover -s scripts -p 'test_*.py'
```

The tests use synthetic inputs to check CRC and salvage, key evidence, alignment,
frame placement, donor-byte coordinates, gap length, and fades. The bundled March and November
commands are end-to-end checks.

The project's original code is licensed under the [GNU General Public License,
version 3](LICENSE) (`GPL-3.0-only`). For the Dream and FAAD2 sources, see the
[third-party notices](docs/NOTICE.md) and [upstream license](docs/COPYING.FAAD2).
The [KCBSDRM contribution](contrib/kcbsdrm/README.md) carries its own license notice.
The 3GPP EVS reference codec is not redistributed here.
