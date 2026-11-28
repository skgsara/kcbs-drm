# Blind mask-byte recovery benchmark: protocol and pre-registered splits

Registered on 2026-11-28, before any recovery method was tuned on these data. [`split.json`](split.json) pins the SHA-256
of every input file, every output dataset file, the builder, the evaluator and this protocol. The splits, tasks and
primary metrics below are fixed. Any change requires a new registration with a new date. Overwriting this one is not allowed.

**Revision (same day, before any method was run or scored).** An independent label audit found 18 text labels that
copies of the same text one or more carousel passes away contradict: 4 DEV and 14 TEST groups, none of them strict. The decoder
check could not detect them. The builder now drops such labels (the carousel copy check below), and `real`, `tasks`,
`baselines` and `register` were rebuilt. The evaluator now also rejects non-finite probabilities, and its mode prior
always leaves a training capture out. Splits, tasks and metrics are unchanged. The numbers below are from the rebuild.

[Builder](../../../scripts/build_mask_benchmark.py) · [Evaluator](../../../scripts/eval_mask_predictions.py) ·
[Evaluator tests](../../../scripts/test_eval_mask_predictions.py) · [Builder tests](../../../scripts/test_build_mask_benchmark.py) ·
[DEV baselines](baselines-dev.json)

## What is being predicted

A 1.2 s group (one 32-bit counter) carries 60 EVS 13.2 kbps frames. The benchmark stores them in slot order
`slot = 20*phase + 4*cycle + (position-1)`. Each frame is 33 bytes, `[mode byte][32 payload bytes]`, ciphertext exactly as received.
The role is `slot % 4`. Mask index `m = 11*role + j` is XORed into payload byte `3j` (frame byte `1+3j`) of all 15 frames of
that role. A group therefore has 44 mask bytes. Index 43 (role 3, j = 10) is clear by convention and is always given as 0. The
masks change with every counter. The text tail reveals `ks[0..15]` = indices 0–15 when the scrolling text is known.

Mask arrays are `int16` with `-1` for unknown. Per-byte provenance codes (`mask_source`): 0 unknown, 1 text CRC-supported
(contrib archive), 2 March idle-tail CRC, 3 **inferred, development only**, 4 clear by convention, 5 synthetic exact.

## Tasks

| task | visible to the method | targets scored | where truth exists |
|---|---|---|---|
| **T1** | role 0 (indices 0–10) + index 43 | role-1 j = 0..4 (indices 11–15) | real, synthetic, nov27 |
| **T0** (control) | role-1 j = 0..4 (indices 11–15) + index 43 | role 0 (indices 0–10) | real, synthetic, nov27 |
| **TH** | indices 0–15 + index 43 | the 27 bytes the text never reveals (16–42) | synthetic (exact), nov27 (inferred) |

T1 mirrors the real situation for role 1: role 0 is known and roles 2–3 are not. T0 is a harder control with less side information.
TH is the real goal and has exact truth only on synthetic data.

The per-task inputs file contains every received group of the split in counter order, not only the labelled ones. Unlabelled
neighbours keep their frames and any trusted visible bytes, so decoders can warm up across consecutive groups. `run_id` marks
consecutive-counter runs. `present` (60 flags per group) marks frames whose mode byte and payload lie in CRC-good packets. Targets
are scored only on labelled groups, and only where the role has at least one received frame.

## Splits

| split | content | use |
|---|---|---|
| **dev** | Nov 25 04:48+04:57 KST 3205 kHz (hik) and Nov 25 12:46 KST 6140 kHz (merged) | development |
| **test** | Nov 25 22:42, Nov 26 05:00, Nov 26 06:42, Nov 26 10:08 | **sealed**: final verification only |
| **transfer** | all March 16 groups (`dumps/*.msc.bin`, idle-tail labels) | transfer check: a different month and label source |
| **syn-dev** | synthetic, 9 audio sources | development |
| **syn-test** | synthetic, 9 other audio sources (no source in both) | **sealed**: final verification only |
| **nov27-dev** | Nov 27 receiver groups with INFERRED P2–P4 masks | development only, never ground truth |

All six November captures and the March dumps built, so no split had to be adjusted. `contrib/kcbsdrm/reference/sf_signon_3205_2026-03-16.bin`
is not used separately. Its 702 complete groups are byte-identical to groups already in the March dumps.

### Real groups

November keys come from `contrib/kcbsdrm/keys/keys_*.npz`. A group counts as labelled when all 16 `crc_supported` bytes are true
and it passes both the carousel copy check and the decoder check below. March keys are `tail(phase 0) XOR 0xFF`, accepted only when phases 1–2 decrypt to
`68 f0 "TextMessage is sending..."` with a matching CRC-16 (`tail_fill_audit.idle_prefixes`, as in `kcbs_decode_fast.py`).

**Decoder label check.** A GCC build of the reference decoder adds one stderr trace line per frame. The decoder sources under
`work/ref` are compiled unmodified; the patched copy of `decoder.c` exists only in the build directory. Each candidate group's 15 role-0 frames are decoded alone, with
all other slots erased, using the label. A control decode of the same frames uses the role-0 label of another labelled group
in the same capture, half the list away. Modes, clear bytes, erasures and positions are unchanged. Any `bfi` or `BER_detect`
flag on a supplied frame drops the label.

**Carousel copy check.** The scrolling text repeats every carousel length (below), so the plaintext of a tail block (tail XOR its
group's key) must equal the plaintext of the blocks 1, 2 and 3 carousel lengths before and after it. Those blocks are decrypted
with other groups' keys. For every key byte position, the builder counts the comparisons that agree and disagree over the group's
three blocks (`carousel_copy_check`). A difference of exactly 0x80 in byte 0 is ignored, because the record-header item toggle
flips between passes. A label is dropped when some byte position disagrees with a copy and agrees with none. A wrong key
byte, for example from a garbled text record that still passes its 16-bit CRC (the contrib README warns of these), disagrees with every copy of
every block of its group. In most of the 18 dropped labels, the same XOR error appears in every block of the group, measured against copies in two
or more other groups. The disputed bytes fall in both role-1 j = 0..4 and role-0 j = 0..10 (32 TEST T1 items and 29 TEST T0 items, 0.35% and 0.15%). Decoding role 0 with the label or with the copy-corrected key gives zero flags in all 18 groups (including one with role-0 j = 0..7
wrong), so the decoder check cannot see them. Groups without copies (154 labelled, 78 of them in 05:00) are kept. March idle labels are exact and are not copy-checked.

| capture | split | groups | runs | 16-byte keys | copy-compared / confirmed all 16 | dropped (copy / flags) | labelled | strict | label flags | wrong-key control flags |
|---|---|---|---|---|---|---|---|---|---|---|
| nov25-0448+0457-3205-hik | dev | 1357 | 9 | 1114 | 1114 / 1113 | 10 (1 / 9) | 1104 | 1027 | 29 / 16710 | 7227 / 16710 (1000 groups) |
| nov25-1246-6140-merged | dev | 682 | 1 | 586 | 584 / 580 | 4 (4 / 1, overlapping) | 582 | 513 | 4 / 8790 | 2883 / 8790 (466 groups) |
| nov25-2242-3205-hl5ntr | test | 800 | 12 | 599 | 588 / 586 | 2 (2 / 0) | 597 | 508 | 0 / 8985 | 3040 / 8985 (491 groups) |
| nov26-0500-3205-hl5ntr | test | 507 | 60 | 221 | 143 / 143 | 0 | 221 | 125 | 0 / 3315 | 1400 / 3315 (196 groups) |
| nov26-0642-merged | test | 575 | 36 | 387 | 345 / 344 | 1 (1 / 0) | 386 | 294 | 0 / 5805 | 1332 / 5805 (253 groups) |
| nov26-1008-merged | test | 767 | 2 | 610 | 589 / 578 | 11 (11 / 0) | 599 | 531 | 0 / 9150 | 876 / 9150 (292 groups) |
| mar16-3205-hl5ntr | transfer | 902 | 14 | 865 | – | 0 | 865 | 865 | 0 / 12975 | 3488 / 12975 (610 groups) |

Flags count supplied role-0 frames. Depending on the capture's mode mix, the wrong-key control flags 10–43% of frames and at
least one frame in 48–90% of groups. It does not check role-1 bytes, and it barely checks role-0 bytes j ≥ 4. On four clean reference groups, 99.2% of
single-byte changes at j = 4..10 still decoded with zero flags (7080 of 7140), against 54.5% at j = 0..3 (2224 of 4080). This comes from a scratch
diagnostic that is not part of the build: 11 × 256 single-byte variants per group, copied to `work/benchmark/diagnostics/`.

**The ten decoder-flagged DEV groups.** All nine hik groups the decoder flags agree with their carousel copies at every one of the 16 byte positions (3–5
agreeing comparisons each). They also pass a fresh header/body CRC recheck and the repeat check, so their keys are almost certainly correct and the flags are
false alarms. They stay dropped, as the decoder rule requires. The tenth (12:46, counter 43703640) is also contradicted by its copies, as is its
neighbour 43703641: one garbled record spans both. The flags persist when five preceding keyed groups are decoded first. For 2 of the 10, no single-byte change of the role-0 label
removes the flags. For the other 8, some alternative value of a byte j = 0..3 removes them (1–100 of that byte's 255 alternative values).
Methods should not treat "zero flags" as necessary for a correct key, nor as sufficient. TEST has no decoder-flagged groups. The dropped
groups stay in the files as unlabelled neighbours with their labels blanked.

**Strict subset.** Strict labels are labelled groups whose 16 key bytes are all covered by text records that pass the CRC
recheck and the carousel repeat check (`review_supplied_records.review`). The repeat check needs a matching record
one carousel length away. That length is estimated per capture from the decrypted text and reproduces the README values: 969 blocks for hik, 700
for the 12:46, 22:42, 05:00 and 06:42 captures, and 878 for 10:08. All March labels are strict. Metrics are reported on all labelled groups (primary) and on the
strict subset (secondary).

### Synthetic groups

Each source is decoded to mono 32 kHz with FFmpeg. It is scaled to −20 dBFS RMS, with the peak kept at or below −1 dBFS, then encoded as one continuous stream:

```
work/evs_gcc_independent/EVS_cod -q -max_band SWB 13200 32 input.32k.raw out.192
```

DTX and channel-aware mode are off, because the broadcast census has no SID or RF frames. The stream is cut into consecutive 60-frame groups, so each
source is one run. Each group gets an independent uniform random 44-byte mask from a fixed seed (syn-dev 202611281, syn-test
202611282), with index 43 set to 0. The files store ciphertext, plaintext and mask. Input level matters: at −26 dBFS the bandwidth detector
coded 12–36% of frames in some music as WB/NB. At −20 dBFS almost every frame is SWB.

| mode family (%) | TCX20 | HQ | GEN-TBE | VOI-TBE | GSC-INA | TRA | GSC-AUD | GEN-BWE | WB/NB |
|---|---|---|---|---|---|---|---|---|---|
| broadcast census in the brief (1,448 groups) | 34.7 | 26.5 | 16.1 | 9.1 | 9.9 | 3.1 | 0.5 | – | 0 |
| all real groups built here (327,261 frames) | 33.0 | 21.9 | 15.9 | 11.4 | 13.6 | 3.3 | 0 | 0.8 | 0.09 |
| syn-dev (557 groups) | 45.9 | 9.9 | 14.0 | 13.5 | 10.5 | 2.8 | 1.7 | 1.6 | 0 |
| syn-test (595 groups) | 40.4 | 8.5 | 21.1 | 14.7 | 8.4 | 3.8 | 0 | 1.5 | 1.4 |

HQ is under-represented in the synthetic sets. Speech sources add GSC-AUDIO and GEN-BWE frames, which are rare in the broadcast.

| syn-dev source | groups | syn-test source | groups |
|---|---|---|---|
| nov27-programme (repo broadcast decode) | 25 | wangjaesan-03-skylark | 125 |
| wangjaesan-02-seashore | 125 | librosa-nutcracker | 75 |
| librosa-vibeace | 51 | librosa-pistachio | 58 |
| librosa-brahms | 38 | librosa-sweetwaltz | 41 |
| librosa-fishin | 75 | librivox-ko-na-04 (Korean) | 125 |
| librivox-ko-hyun-01 (Korean) | 125 | librivox-en-spc258 ×3 readers | 91 |
| librivox-en-spc160 ×3 readers | 118 | librivox-ja-dokoe-12 (Japanese) | 80 |

`split.json` records URLs and SHA-256 hashes. Downloads are verified against the hashes pinned in the builder. Licences: LibriVox items are public
domain, and the librosa examples are CC BY or CC BY-NC (BY-NC: fishin, sweetwaltz). The Wangjaesan tracks are an archive.org upload with no licence stated. They are used locally and not redistributed.
The repository's 16 kHz renders (`examples/nov27/radio.mp3`, `fully-supplied-12s.wav`, `examples/nov19/*`) are excluded. With no energy above 8 kHz, the encoder
codes 78–98% of their frames as WB, measured and recorded in the synthetic receipt. The two November 27 files are also renders of the same
performance as `nov27-programme`.

### November 27 (development only)

There are 26 receiver groups. 24 have text-CRC keys for all 16 bytes. The inferred masks contribute 500 further bytes (role 0: 22, role 1: 130, role 2:
198, role 3: 150). They were accepted only where the data-unit SHA-256 in `dumps/nov27-measured-masks.json` matches the received data unit. In 90
overlapping bytes (P2 j = 0..4), the inferred and text masks agree on all 90. These labels were inferred with FM/CD reference audio
([docs](../../../docs/nov27-mask-validation.md)). They may be used for development only. Never quote them as ground truth.

## Items per task file

| split.task | groups in file | groups with targets | items | strict items |
|---|---|---|---|---|
| dev.T1 / dev.T0 | 2039 | 1686 | 8430 / 18546 | 7700 / 16940 |
| test.T1 / test.T0 | 2649 | 1803 | 9015 / 19833 | 7290 / 16038 |
| transfer.T1 / transfer.T0 | 902 | 865 | 4325 / 9515 | all |
| syn-dev.T1 / T0 / TH | 557 | 557 | 2785 / 6127 / 15039 | all |
| syn-test.T1 / T0 / TH | 595 | 595 | 2975 / 6545 / 16065 | all |
| nov27-dev.T1 / T0 / TH | 26 | 24 / 24 / 22 | 120 / 264 / 468 | – |

## Rules

1. A method reads only `work/benchmark/tasks/<split>.<task>.inputs.npz` for the split it predicts. It must not read truth files, label files
   (`work/benchmark/real/*.npz`, `synthetic/*.npz`), text tails, the contrib key and record archives, or `dumps/*.msc.bin` for
   any group it is scored on. For T0 it must not use T1 inputs, and the reverse. Any decoder, encoder or public audio may be used.
2. Training and tuning may use DEV labels, syn-dev, nov27-dev and the evaluator's output on those sets.
3. TEST and syn-test are sealed. Each final method is frozen first: code commit, parameters and DEV-chosen confidence
   thresholds. It is then scored once with `--frozen-thresholds` taken from its DEV metrics. Every sealed run is logged, including failed ones.
   A method changed after a sealed run counts as a new method. TRANSFER may be used for checks but is reported separately.
4. The primary pre-registered numbers on TEST (T1) and syn-test (TH) are:
   - bits per group called at the DEV-frozen confidence threshold for 99.5% precision, with the precision achieved on the sealed set;
   - tie-aware top-1 byte accuracy over all target items.
   Secondary numbers: the same at 98%, the oracle at-precision counts, mean rank, log2 loss, per-(role, j) breakdowns and the strict subset.
   T0 is a control and is not a headline number.
5. Inferred nov27 bytes are never reported as ground truth.

## Predictions and scoring

Each prediction file entry is keyed by (group id, role, j). It gives either a 256-way `logp` vector or a ranked `candidates` list with
`candidate_probs` and/or a `confidence`. JSON and npz are both accepted; the evaluator docstring has the exact format. Missing items are scored
as uniform and counted.

```
python scripts/eval_mask_predictions.py --truth work/benchmark/tasks/dev.T1.truth.npz \
    --predictions my_dev_T1.npz --out work/results/my_dev_T1.json
# sealed run, thresholds frozen from DEV:
python scripts/eval_mask_predictions.py --truth work/benchmark/tasks/test.T1.truth.npz \
    --predictions my_test_T1.npz --frozen-thresholds work/results/my_dev_T1.json --out work/results/my_test_T1.json
```

Bit marginals are summed from each 256-way distribution, MSB first. "Bits at precision p" is the largest confidence-ranked set of
target bits whose empirical precision is at least p. The cut never splits equal confidences. Within-role consistency
counts (group, role) cells whose target bytes are all recovered at top-1, and all called and correct at confidence ≥ 0.98 / 0.995.

## Baselines (development sets only)

Both baselines are computed on the same items. The **uniform** baseline makes every byte equally likely. The **mode prior**
estimates P(clear bit = 1) per (exact mode byte, keyed payload bit), using only DEV labelled role-0 plaintext with +0.5 smoothing. Each mask bit is then a log-likelihood vote over the received
frames of its role. Bits are assumed independent and statistics are assumed the same at every position. DEV items are scored with their own
capture left out of the prior. Synthetic and nov27 items use the full DEV prior.

| set | items | uniform top-1 | prior top-1 | prior mean rank | prior bits/group @98% | @99.5% | target bits/group |
|---|---|---|---|---|---|---|---|
| dev.T1 | 8430 | 0.0039 | 0.0325 | 78.4 | 3.45 | 2.41 | 40 |
| dev.T0 | 18546 | 0.0039 | 0.0252 | 92.4 | 2.71 | 2.47 | 88 |
| syn-dev.TH | 15039 | 0.0039 | 0.0120 | 93.9 | 4.55 | 3.88 | 216 |
| syn-dev.T1 | 2785 | 0.0039 | 0.0151 | 84.9 | 1.99 | 1.78 | 40 |
| syn-dev.T0 | 6127 | 0.0039 | 0.0123 | 91.8 | 2.25 | 1.99 | 88 |

Uniform calls no bits at either precision. The prior is overconfident. On dev.T1, bits it gives probability ≥ 0.98 are right 86.6% of the
time, so its working thresholds sit near 0.9998 (98%) and 0.99999998 (99.5%). Small changes in its training set move rare-mode bits across these thresholds. Most of its signal sits in j = 0 (dev.T1 r1j0
top-1 0.098, mean rank 16.8) and in j = 10 of role 0. No (group, role) cell is fully recovered. Full numbers are in
[baselines-dev.json](baselines-dev.json). Per-item predictions are written to `work/benchmark/baselines/predictions/`.

## Rebuild

Prerequisites: the EVS build (`python scripts/build_evs_gcc_independent.py --out work/evs_gcc_independent`), FFmpeg, and HTTPS access to
librosa.org and archive.org.

```
cd scripts
python build_mask_benchmark.py real        # salvage, keys, decoder label check (about 2 min, 4 cores)
python build_mask_benchmark.py nov27
python build_mask_benchmark.py synthetic   # downloads into work/benchmark/sources/<name>/, verifies SHA-256
python build_mask_benchmark.py tasks
python build_mask_benchmark.py baselines   # writes baselines-dev.json
python build_mask_benchmark.py register    # writes split.json
python -m unittest test_eval_mask_predictions test_build_mask_benchmark
```

Each step writes into a new directory under `work/benchmark` and refuses to overwrite. Raw `.npz` file hashes include zip
timestamps. `content_sha256` in `split.json` hashes the arrays and is what a rebuild should reproduce.

## Known limitations

- Role-1 labels (T1 truth) are checked by text CRC and by the carousel copy check. The strict subset adds the record repeat check. The decoder check covers only role 0,
  and mainly role-0 bytes j = 0..3. The 154 labelled groups without carousel copies (78 of 221 in 05:00, 42 in 06:42, 21 in 10:08, 11 in 22:42,
  2 in 12:46) rest on the text CRC alone. The copies contradict 19 of the 3,363 fully supported groups that had copies, which suggests about one
  undetected wrong label among those 154.
- The mode prior assumes position-invariant statistics, which T1/TH apply to roles 1–3. The prior was trained on role 0.
- Synthetic sources under-represent HQ frames. They come from public speech and music, not from KCBS programme audio. The exception is the 30 s
  `nov27-programme` decode, which itself contains concealed slots.
- The TEST captures differ in mode mix: 10:08 is mostly speech (ACELP), while 05:00 has 60 short runs.
