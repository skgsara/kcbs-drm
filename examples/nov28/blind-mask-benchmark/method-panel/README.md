# Method panel, DEV only (interrupted, unverified)

Four independent blind mask-byte recovery methods were built against the
pre-registered benchmark in `../protocol.md`. Each was frozen on DEV splits.
The session ended before the planned steps that follow:

- the advisor comparison,
- the adversarial verification,
- a single scoring run on the sealed `test` / `syn-test` splits.

**Nothing below has touched a sealed split. These are DEV numbers only, and no
independent check has confirmed them.**

| method | script | idea |
|---|---|---|
| rule-prior | `scripts/mask_method_rule_prior.py` | consensus of the existing EVS field rules plus a context-conditioned byte prior |
| params | `scripts/mask_method_params.py` | patched reference decoder exports per-field parameters; learned prior over decoded parameters |
| learned-disc | `scripts/mask_method_learned_disc.py` | small discriminator over context and candidate-decoder features |
| acoustic | `scripts/mask_method_acoustic.py` | candidate-decoder PCM continuity scoring (fork-snapshot decoder) |

Each method's `*.freeze.json` in this folder records hashes of its script,
model and decoder. Model files and per-run metrics stay under `work/methods/`,
which is not tracked.

## DEV results (hidden-byte recovery)

| split.task | method | items | top-1 | log2 loss | bytes called at 99.5% precision |
|---|---|---|---|---|---|
| dev.T1 | ModePrior baseline | 8430 | 0.033 | 8.60 | 0 |
| dev.T1 | rule-prior | 8430 | 0.332 | 4.82 | 1050 |
| dev.T1 | rule-prior, wrong-group control | 8430 | 0.005 | 18.31 | 0 |
| dev.T1 | params | 1000 | 0.638 | 2.47 | 272 |
| dev.T1 | params, 20-group rerun | 100 | 0.45 | 9.94 | 18 |
| dev.T1 | learned-disc (full) | 2500 | 0.194 | 5.59 | 19 |
| dev.T1 | learned-disc, wrong-group control | 500 | 0.004 | 16.40 | 0 |
| dev.T1 | acoustic | 500 | 0.168 | 6.73 | 34 |
| dev.T1 | acoustic, wrong-key control | 100 | 0.02 | 9.14 | 0 |
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

## Caveats to settle before any TEST run

- **params** has no wrong-group control. Its 20-group rerun (top-1 0.45,
  log2 loss 9.9) disagrees sharply with its 1000-item run (0.638, 2.47).
  Treat its headline as suspect until both are explained.
- **rule-prior** transfers well in one direction across captures and poorly in
  the other. Part of its dev.T1 gain may be capture-specific.
- Every method's wrong-group or wrong-key control collapses to chance or below.
  That is the expected sign that the methods read real codec evidence.
- Methods were scored on different subsets of dev.T1. Compare like-for-like
  before fusing.

## Next steps

1. Rerun all four methods on one common dev.T1 subset.
2. Add a params wrong-group control.
3. Run an adversarial verifier on each method, checking for label leakage and
   in-sample training.
4. Fuse the methods and freeze the result.
5. Score once on `test` and `syn-test`.
