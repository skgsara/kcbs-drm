# A TCX20 prefix that predicts two payload octets

For a particular 13.2 kb/s TCX20 spectral code, the reference encoder writes zero filler across payload offsets 15 and 18. A fresh 900-word synthetic stream produced **49 qualifying words, including 13 at position two**. A decoder given only the first 128 bits predicted both octets on all 49. The independent sender agreed on all 98 octets and all 1,764 predicted bits beyond the supplied prefix. [Expected sender result](expected.json)

## The rule

Number the 264 physical EVS bits from zero, most significant bit first, including the mode octet. Payload indices exclude that octet. Offsets 15 and 18 therefore occupy bits [128,136) and [152,160). The rule applies to ordinary primary TCX20 with harmonic context mapping off.

1. Parse the known prefix through TNS, harmonic signalling and any IGF fields to find the main spectrum. Read the tuple-count field, whose width depends on the coded spectrum length. An all-zero count means one coefficient pair.
2. Let `a` be the first arithmetic bit after that field. If bits [a,a+3) are `101`, the sole unsigned coefficient pair is (0,0). Its canonical reference encoding emits exactly those three bits. It has no nonzero signs or escaped magnitudes.
3. The reference encoder permits at most 100 residual parameters. If `a+3 < 164`, it fills [a+3,164) with zeros. The predictor checks all filler already visible in the prefix. It reports an octet only if the whole octet lies inside the interval.

The first unmapped pair starts with both context counters zero, with no previous pair, no escape level and a budget below 400 bits. At the initial positions the index selects model 1 in `ari_lookup_s17_LC`. Its zero-symbol cumulative counts are 16384 and 8983, so the initial inclusive 16-bit register interval is [35932,65535]. Every continuation of `101` lies in [40960,49151]. A single high-half renormalization emits `1` and leaves the lower bound at 6328. Termination then emits `01`. The build verifies the lookup, all 8,192 continuations, and the canonical termination against the pinned source.

The relevant source files are `lib_enc/enc_prm.c` (lines 590–657), `lib_dec/dec_prm.c` (660–748), `lib_com/rom_com.c` (17040 and 17556), `lib_enc/ACcontextMapping_enc.c` (103–118, 161–195 and 274–324), `lib_enc/ari_enc.c` (59–93 and 121–165), and `lib_com/cnst.h` (823). The encoder places arithmetic termination inside the spectrum, followed by signs, conditional filler, residual refinements and reverse-order escape bits. Offsets 21, 24, 27 and 30 lie past the proven filler. [Official TS 26.443 floating-point reference C source](https://www.etsi.org/deliver/etsi_ts/126400_126499/126443/19.00.00_60/ts_126443v190000p0.zip)

## Run the control

Use Python 3.10 or later, GCC on Linux, an unmodified reference encoder executable and the original-byte C source from the 4 November 2021 reference implementation. Run from this directory. The source directory contains `lib_com`, `lib_dec` and `lib_enc`.

```sh
python build.py /path/to/c-code /tmp/tcx-prefix-reader
python control.py /path/to/EVS_cod /tmp/tcx-prefix-reader /tmp/tcx-control-new
```

The control generates 18 seconds of 32 kHz chirps, pulsed noise and digital silence, then encodes it at 13.2 kb/s with the SWB cap. It writes a file containing only the 16-byte prefixes. A separate process predicts from that file and records its decision digest before the scorer compares against the original full words. An existing output directory causes the control to stop. The expected result pins the input PCM and original G.192 hashes. [Generator and scorer](control.py)

For a separate set of already established contiguous clear prefixes, supply JSON rows with a unique integer `slot` and a `prefix_hex` value containing exactly 16 physical EVS octets starting at the mode octet. Missing or tentative bits do not meet this input requirement.

```sh
python predict.py /tmp/tcx-prefix-reader /tmp/tcx-control-new/prefixes.json /tmp/my-decisions.json
```

The reader starts cold for each 128-bit word. A diagnostic G.192 record supplies those symbols and specifies the nominal 13.2 kb/s grammar. The reader guards sequential reads, absolute reads and cursor moves, and exits before spectral arithmetic decoding. The decision process independently reads the tuple count and three arithmetic bits from its prefix. It abstains if the native path crosses bit 128, if the mapped case is selected, or if it cannot confirm the expected frame size, reference configuration and available sanity checks. A raw receiver projection normally omits payload byte 0, which includes overlap signalling needed to locate later fields. Passing the check establishes the reference encoder's filler only under the stated prefix and configuration.

## Observed scope

| Input | Qualifying words / TCX20 words | Second-position result |
|---|---:|---|
| New 900-word synthetic SWB sender | 49 / 347 | 13 qualifying words, 26/26 predicted octets matched |
| Earlier 2,400-word synthetic SWB and WB encodes of the same waveform | 46 / 279 and 47 / 267 | 16 and 17 qualifying words, 66/66 predicted octets matched |
| Separate 1,260-word synthetic sender | 0 / 813 | No predicted octets |
| Previously exported P2 prefixes, development counter 43865914 | 0 / 15 | 70–122 coefficient pairs per word |
| Published November 27 music release, 265 P2 words labelled `position_two_signs` | 0 / 226 | 189 multi-pair and 37 mapped TCX20 words |
| 3,360 disjoint, previously recovered first-position TCX20 words | 0 / 3,360 | First-position controls |

The first-position total includes 1,854 archived controls and 1,506 from the November 27 13:17 recording. The bounded reader's spectral start matched earlier full-word observations on all 1,854 controls with archived cursor checks. At 13:17, 1,111 words had multiple coefficient pairs and 395 selected harmonic mapping. A November 26 control supplied no TCX20 first-position words. The rule supplied zero new octets on the received cases in this table.

The November 27 handoff already supplies the 15 text-supported second-position prefixes for `43865914`. The public prefix reader rejects 14 at the multiple-pair check and one at the earlier harmonic-mapping check. To reproduce from this directory, run the following after building the prefix reader.

```sh
python predict.py /tmp/tcx-prefix-reader 43865914-p2-prefixes.json /tmp/43865914-decisions.json
```

## Screen a new IQ recording before recovering its prefix

Of the 36 predicted bits beyond the prefix, 16 fall in payload bytes 15 and 18. The other 20 are directly received. Under this filling rule, payload bytes 16 and 17 and the high four bits of payload byte 19 must all be zero. A single received one excludes this case. Twenty zeros leave it possible. A missing required bit with the rest zero leaves the screen inconclusive.

| Recording | Complete groups | TCX20 words screened | Compatible with the required 20 zeros |
| --- | ---: | ---: | ---: |
| Nov 15, 3205 kHz | 109 | 1,983 | 0 |
| Nov 27, 3205 kHz, Edogawa | 74 | 2,308 | 0 |
| Nov 27, group member's 17:44 handoff | 295 | 4,106 | 0 |
| Nov 27, group member's 17:56 handoff | 644 | 4,959 | 0 |

The 1,122 groups have disjoint counters. All 13,356 screened TCX20 words contained at least one directly received one, including all 3,332 second-position TCX20 words. This test uses only the mode and the three directly received octets. It can rule out this special case on a new recording before any contiguous clear prefix is available. [Counts by recording and position](on-air-screen.json)

For a replay from the repository root, the archived Edogawa group below has four TCX20 words with an observed one. The other 56 slots use different modes.

```sh
python scripts/project_evs_group.py examples/nov27/validation/tbe-tail-43900403/data_units.npz --counter 43900403 |
  python examples/nov27/validation/tcx-zero-pair/screen.py -
```
