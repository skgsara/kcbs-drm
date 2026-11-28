# What the DEV score receipts establish

The acoustic method reported **34 individual bit calls** at its 99.5% empirical precision cutoff on 100 development groups. Its published receipt gives 0.34 bits per group. The whole-byte call count and log loss for this run are absent from that receipt. The original panel reports that the session ended before independent verification and sealed scoring. It records no acoustic-specific exit status or cause of interruption. [Original panel](https://github.com/skgsara/kcbs-drm/blob/f79d70f85d0caf2e5c5f380c9c69d3781e048121/examples/nov28/blind-mask-benchmark/method-panel/README.md) · [Acoustic receipt](https://github.com/skgsara/kcbs-drm/blob/f79d70f85d0caf2e5c5f380c9c69d3781e048121/examples/nov28/blind-mask-benchmark/method-panel/acoustic.freeze.json)

DEV T1 hides five P2 bytes per group for which broadcast text supplies comparison labels. Byte top-1 credits a tied highest-ranked value fractionally. A bit call counts one individual bit selected at the cutoff. The reported scores have different units and answer different questions. [Scoring protocol](https://github.com/skgsara/kcbs-drm/blob/f79d70f85d0caf2e5c5f380c9c69d3781e048121/examples/nov28/blind-mask-benchmark/protocol.md)

| DEV T1 comparison | Groups | Byte items | Byte top-1 | Individual bits called at 99.5% empirical precision |
|---|---:|---:|---:|---:|
| Acoustic | 100 | 500 | 0.168 | 34 |
| Mode prior, same subset | 100 | 500 | 0.024 | 228 |
| Derangement control, same subset | 100 | 500 | 0.004 | 1 |
| Wrong-key control, separate subset | 20 | 100 | 0.020 | 2 |
| Mode prior, full DEV set | 1,686 | 8,430 | 0.032508 | 4,058 |

On the shared subset, acoustic scored higher on byte top-1, while the mode prior called more bits at its empirical cutoff. The four methods used different DEV subsets. The aggregate reports alone cannot rank them on the same items or independently verify their predictions against the labels. [Full DEV baseline](https://github.com/skgsara/kcbs-drm/blob/f79d70f85d0caf2e5c5f380c9c69d3781e048121/examples/nov28/blind-mask-benchmark/baselines-dev.json)

## A missing prediction in a 200-item control

An earlier run of the registered evaluator used 200 invented groups with one target byte each. It received 199 certain, correct predictions and assigned a uniform distribution to the one missing prediction. The evaluator reported these counts. [Original evaluator control and checks](https://github.com/skgsara/kcbs-drm/blob/d04a029113dd7e3bdd647c005f8db54cf4670c66/examples/nov28/blind-mask-benchmark/method-panel/check_metric_control.py)

| Cutoff | Bytes called | Bits called | Bits per group |
|---|---:|---:|---:|
| Largest set achieving 99.5% precision against the sample labels | 200 | 1,600 | 8.00 |
| Fixed confidence of 0.995 | 199 | 1,592 | 7.96 |

At the empirical cutoff, the uniform byte earns 1/256 credit and each of its eight bits earns half credit. The resulting precisions are 0.99502 for bytes and 0.9975 for bits. At the fixed cutoff, the missing item stays below threshold. The historical evaluator's short summary reported 8.00 even in the fixed-threshold run. Its full JSON reported 7.96 under the frozen threshold. This distinction matters whenever predictions are missing.

## Verify from a clone

Run from the repository root with Python 3 and Git. The checker reads the pinned Git objects locally, verifies the SHA-256 hashes of four registered inputs and four method scripts, and compares the published aggregate arithmetic and toy calculation with the expected receipt. Historical program files are read solely to compute their digests. [Checker](check.py) · [Expected results and all eight hashes](expected.json)

```sh
python3 -I -B examples/nov28/dev-score-audit/check.py
```

A clone must contain historical commit `f79d70f85d0caf2e5c5f380c9c69d3781e048121` and its blobs. If a shallow or single-branch clone lacks them, fetch the public commit explicitly, then rerun the command.

```sh
git fetch origin f79d70f85d0caf2e5c5f380c9c69d3781e048121
```
