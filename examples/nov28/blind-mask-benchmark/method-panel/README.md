# Method panel and independent review of the DEV reports

Four independent blind mask-byte recovery methods were built against the
pre-registered benchmark in `../protocol.md`. Each was frozen on DEV splits.
The session ended before the planned steps that follow:

- the advisor comparison,
- the adversarial verification,
- a single scoring run on the sealed `test` / `syn-test` splits.

The freezes report DEV method runs only. An independent review checked the
published aggregates and their units. The frozen method runs have yet to be
independently reproduced. The earlier registration separately documents label
quality checks on the original archive. [Registered protocol](../protocol.md)

| method | script | idea |
|---|---|---|
| rule-prior | `scripts/mask_method_rule_prior.py` | consensus of the existing EVS field rules plus a context-conditioned byte prior |
| params | `scripts/mask_method_params.py` | patched reference decoder exports per-field parameters; learned prior over decoded parameters |
| learned-disc | `scripts/mask_method_learned_disc.py` | small discriminator over context and candidate-decoder features |
| acoustic | `scripts/mask_method_acoustic.py` | candidate-decoder PCM continuity scoring (fork-snapshot decoder) |

Each method's `*.freeze.json` in this folder records hashes of its script,
model and decoder. Model files and per-run metrics stay under `work/methods/`,
which is not tracked.

## Results reported by the original panel

T1 scores the first five P2 bytes hidden for this exercise, where text supplies
comparison labels. The six later P2 bytes have exact labels only in the
synthetic TH benchmark. November 27 TH uses inferred labels. The table below
retains the original panel's reported values for the other methods. Dashes mark
the acoustic byte counts and log losses omitted by its freeze.
[Original panel report](https://github.com/skgsara/kcbs-drm/blob/f79d70f85d0caf2e5c5f380c9c69d3781e048121/examples/nov28/blind-mask-benchmark/method-panel/README.md)

| split.task | method | items | top-1 | log2 loss | bytes called at 99.5% precision |
|---|---|---|---|---|---|
| dev.T1 | ModePrior baseline | 8430 | 0.033 | 8.60 | 0 |
| dev.T1 | rule-prior | 8430 | 0.332 | 4.82 | 1050 |
| dev.T1 | rule-prior, wrong-group control | 8430 | 0.005 | 18.31 | 0 |
| dev.T1 | params | 1000 | 0.638 | 2.47 | 272 |
| dev.T1 | params, 20-group rerun | 100 | 0.45 | 9.94 | 18 |
| dev.T1 | learned-disc (full) | 2500 | 0.194 | 5.59 | 19 |
| dev.T1 | learned-disc, wrong-group control | 500 | 0.004 | 16.40 | 0 |
| dev.T1 | acoustic | 500 | 0.168 | — | — |
| dev.T1 | acoustic, wrong-key control | 100 | 0.02 | — | — |
| dev.T0 | rule-prior | 18546 | 0.176 | 6.25 | 1140 |
| syn-dev.TH | rule-prior | 15039 | 0.104 | 6.67 | 214 |
| syn-dev.TH | params | 1080 | 0.219 | 5.71 | 82 |
| nov27-dev.TH | rule-prior | 468 | 0.083 | 7.01 | 10 |
| nov27-dev.TH | learned-disc | 468 | 0.103 | 6.85 | 8 |

Rule-prior capture transfer on dev.T1:

| trained on → scored on | top-1 | bytes called at 99.5% precision |
|---|---|---|
| 6140 → 3205 | 0.43 | 1099 / 5520 |
| 3205 → 6140 | 0.14 | 19 / 2910 |

## What the public receipts verify

The acoustic freeze includes a baseline and a derangement control for the
same 500 DEV byte items. Under tie-aware top-1 scoring the acoustic method ranks
higher than the baseline here. At the empirical precision cutoff the baseline
calls more individual bits. Each cutoff was selected on this DEV sample.
[Acoustic freeze](acoustic.freeze.json)

| DEV T1 run | Groups | Byte items | Byte top-1 | Individual bits called at 99.5% empirical precision |
|---|---:|---:|---:|---:|
| Acoustic | 100 | 500 | 0.168 | 34 |
| Mode prior on the same subset | 100 | 500 | 0.024 | 228 |
| Derangement control on the same subset | 100 | 500 | 0.004 | 1 |
| Wrong-key control on a separate subset | 20 | 100 | 0.020 | 2 |

The acoustic receipt gives 0.34 bits per group across 100 groups. It omits the
number of whole bytes called and the log loss for this run. The full DEV
baseline uses 1,686 groups and 8,430 byte items. Its reported 4,058 bit calls
apply to that larger sample. The four headline T1 runs have different sample
sizes, and their published aggregates do not establish a ranking on common
items. Models and per-item predictions needed for a full replay are only
partially represented by the published freezes. [Full DEV baseline](../baselines-dev.json)

From the repository root, run
`python examples/nov28/blind-mask-benchmark/method-panel/audit_dev.py`
to check the four method script hashes, the four registration file hashes and
the arithmetic above. It uses the committed DEV summaries and Python's
standard library. [Receipt audit](audit_dev.py)

## Independent controls

**Scoring an abstention.** On an invented 200-item example, 199 predictions are
certain and correct, and the last is missing. The registered evaluator assigns
the missing item a uniform distribution. Its largest set with at least 99.5%
empirical precision includes all 200 bytes and all 1,600 bits. A fixed 0.995
confidence threshold includes 199 bytes and 1,592 bits. A reported bit-call
count therefore needs its threshold definition and the number of supplied
predictions. The CLI's short summary prints empirical counts, including when a
frozen threshold is supplied. The full JSON carries the separate frozen result.
[Statistical control](check_metric_control.py)

**Decoder history.** Two stock synthetic encodes differ by one bit in frame
205 and have 34 byte-identical frames after it. At 32 kHz their decoded PCM
differs in 33 of those later frames. Decoding both identical suffixes from
reset produces identical PCM. A score based on continuity can measure the
history entering a frame as well as that frame's contents. An acoustic
comparison should identify how the decoder obtained its starting state.
[Inputs, sample hashes and replay](../../evs-state-control/README.md)

## Caveats to settle before any TEST run

- **params** has no wrong-group control. Its 20-group rerun (top-1 0.45,
  log2 loss 9.9) disagrees sharply with its 1000-item run (0.638, 2.47).
  Treat its headline as suspect until both are explained.
- **rule-prior** transfers well in one direction across captures and poorly in
  the other. Part of its dev.T1 gain may be capture-specific.
- The uniform top-1 expectation is 1/256 (0.00390625). The acoustic
  wrong-key control scored 0.020 on 100 items and its separate derangement
  scored 0.004 on 500. The published panel has no params wrong-group result.
  These comparisons alone cannot establish that the methods are free of
  label leakage.
- Methods were scored on different subsets of dev.T1. Compare like-for-like
  before fusing.

## Next steps

1. Rerun all four methods on one common dev.T1 subset.
2. Add a params wrong-group control.
3. Run an adversarial verifier on each method, checking for label leakage and
   in-sample training.
4. Fuse the methods and freeze the result.
5. Score once on `test` and `syn-test`.
