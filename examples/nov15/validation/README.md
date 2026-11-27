# Blind four-position receiver milestone

The goal is to obtain all four KCBS-2 masks for a previously unseen counter
from broadcast data alone and reproduce its 60 clear EVS words. The first
test target is **43004924**, the earliest complete counter in a single pass
over the November 15, 2026, 10:58 UTC recording on 3205 kHz. We chose it
using packet coordinates and checksums alone. Its four masks and an
independent clear EVS export are still outstanding.

## Identify the recording and group

The IQ file contains 2,398,720 stereo sample pairs at 12 kHz (199.89 s).
A fixed Wiener receiver pass assigned 1,507 CRC-good packets and reconstructed
366 complete data units, including 109 whole three-phase groups. Within the
first and last assigned phases, 7,524 word slots had all 33 transport octets,
39 had partial receipt, and 2,277 had none. Replaying the first 40 seconds
of the same recording gave identical bytes at all 302 overlapping accepted
packet coordinates.

For the target itself, all 12 packets and all three data units passed their
transmitted CRCs. In phase order the DU CRCs are `F8A4 / 9CDB / 9C4F`.
The receipt gives the IQ file hash and a SHA-256 for each 716-byte DU,
including its transmitted checksum. Times for individual frames follow
the received group counter and phase. [Target receipt](target-43004924.json)
· [All 109 complete counters](complete-counters.csv)

## What the historical counter matches establish

The November 25–26 contribution contains six sets of counters. Each has
an original prefix archive and an export. Comparing the twelve files by
counter reproduces **4,412 identical prefix rows**. All 4,412 matches
are between an archive and its own export. The support flags agree on every
row. Of those rows, 3,517 mark all 16 bytes as supported and 895 mark none. Across the
15 pairs of different capture sets there are **zero shared counters**.
These matches verify the export process. They leave open whether a
receiver can obtain the mask for a fresh counter from the counter alone.
[Contributed archive formats and capture list](../../../contrib/kcbsdrm/README.md)

## What to record before opening a reference

1. Record the receiver version or commit, input IQ SHA-256, the data used to
   initialize its state, and the three target DU hashes. Describe any required
   acquisition history. This target is near the start of the recording.
2. Save the four predicted 11-byte masks, labelled by position 1–4. Reapply
   them to the three identified DUs and verify that the result matches the
   60 ordered words in the submitted G.192 stream. Save the receiver-to-audio
   replay command. Report any unresolved offsets, missing transport bytes,
   input erasures and observed concealment. Keep each erased slot on the clock.
3. Record SHA-256 digests of the prediction files and publish the digests or
   give them to an independent reviewer before opening the reference. The
   reviewer records the origin of the clear export, receiver version, its
   first slot and file hash. An independently operating service receiver can
   supply such an export. The file comparator checks equality at the stated
   coordinates. Provenance and the order of disclosure are separate checks.

A complete pass requires **15 exact 264-bit words at each position**, 60
out of 60. The following command assumes both files start at the first slot
of the target. For a continuous stream, pass its actual starting counter,
phase (0–2), cycle (0–4) and position (1–4). Matching AM or music can
corroborate timing and programme identity after the prediction is frozen.

```sh
python scripts/compare_evs_group.py prediction.192 independent-reference.192 \
    --counter 43004924 --candidate-start 43004924 0 0 1 \
    --reference-start 43004924 0 0 1
```

The tool accepts little-endian G.192 or mono EVS storage at 13.2 kbit/s,
including gzip-compressed files. It reports matches, mismatches, erasures
and coordinates outside a file's extent. Exit status 0 requires all 60
words to agree, 1 means a difference or incomplete coverage, and 2 means
invalid input. [Comparison tool](../../../scripts/compare_evs_group.py)

## Check the origin of an independent export

After the prediction is frozen, an operator with the original decoder input
can check the export against the published fingerprints. This check needs
only the export and two small JSON files. Each position is identified by the
mode byte and 21 directly transmitted payload bytes of each of its 15 words.
The four fingerprints cover 1,320 received bytes. The full-word comparison
above checks the remaining 660 bytes as well.

```sh
case_dir=examples/nov15/validation
python scripts/check_evs_origin.py "$case_dir/origin-43004924.json" independent-reference.192 \
    --target "$case_dir/target-43004924.json" --start 43004924 0 0 1
```

Use the externally recorded origin of the first slot if the file starts
earlier. The tool counts erasures and slots outside the file separately.
In a control with the published November 27 stream, all four positions of
counter 43854890 matched their received fingerprints. Displacing the
declared origin by one four-frame cycle made all four fail. The
text-supported stream matched only position one. This makes a wrong
origin detectable when the directly transmitted bytes differ. The recording
chain and the full 264-bit comparison still require independent evidence.

Anyone with the three 716-byte target DUs can regenerate the fingerprint
file. Concatenate them, including their transmitted CRCs, in phase order
0, 1, 2 and run the commands below. The full-file pass and the earlier
40-second pass over the same IQ produced identical fingerprints.

```sh
python "$case_dir/build_origin_receipt.py" three-dus.bin > rebuilt-origin.json
cmp "$case_dir/origin-43004924.json" rebuilt-origin.json
```

### Programme reference leads

Koryo Front lists a public KCBS-2 listening stream. A listening report
published on November 15 describes comparing a recording of that stream
with a partial 3205 kHz decode. It gives no UTC start or file hash tying
the comparison to the 10:58 capture. The original 60-word EVS export for
this target is still sought. [Koryo Front radio](https://koryofront.org/radio)
· [November 15 monitoring report](https://mediumwave.info/2026/11/15/north-korea-12/)

For a fresh joint capture, the useful pairing is a time-stamped SDR IQ file
and a separate service receiver's original EVS input with frame order and
counter. Record through the same interval on both devices. Preserve any
erasures and the method used to establish the first counter and phase.

## Evidence from the November 27 captures

The 12-second excerpt has 150 second-position words labelled
`position_two_signs`. Across the 30-second release that label covers 265
words in 18 groups. All 90 mask bytes that overlap the text-supported
prefixes agree, while all 18 six-byte suffixes are distinct. Comparing
the released text-supported and combined G.192 streams at counters
43854890–43854899 gives 150 matching words at position one. The
text-supported stream has erasures at all 150 words of each other position.
The authors describe using the aligned Pyongyang FM and CD performances in the inference.
Their worked sign example is for position three. The exact fields, rejected
candidates and acceptance criteria used at position two are unavailable in
the release. [Author's validation notes](../../../docs/nov27-mask-validation.md)
· [Published evidence](../../nov27/validation/evidence.json)
· [Companion project's description](https://github.com/KoryoFront/kcbs2-drm-decode/blob/9794ddbf5f0daa5551ff04e8d9b863288e052f69/docs/measured-masks.md)

Two other November 27 handoffs each contained all 60 transmitted words of a
group. In the text-supported replay, each supplied 15 first-position words.
Positions two through four had 45 explicit input erasures and zero slots
missing transport bytes in each group.

| Counter | Observed second-position modes | Complete second-position words from text evidence |
| --- | --- | ---: |
| 43865914 | 15 TCX20 | 0 of 15 |
| 43869343 | 8 GSC and 7 other ACELP | 0 of 15 |

In the TCX20 group, re-encoding the high-frequency extension (IGF) parameters
reproduced 485 bits across the 15 second-position words. The furthest actual
read was bit 112, counting the first mode bit as zero. The first unknown
payload byte begins at bit 128. Every suffix sharing that prefix therefore
gives the same IGF result for these words. These handoffs provide
development cases for complete transport with unresolved audio.

For contributors, the outstanding question is which of the six suffix bytes,
if any, were fixed using receiver inputs before the FM/CD recordings were
consulted. An author-provided field trace from a published group or a
documented receiver or transmitter test vector with known inputs and outputs
would let us check that distinction. A new public SDR IQ capture is most
useful when it can be paired with a simultaneous independent clear EVS
export, or when a documented acquisition requirement calls for more history.
