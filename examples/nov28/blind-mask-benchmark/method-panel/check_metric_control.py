"""Check the evaluator's empirical and fixed 99.5% cutoffs on invented labels only."""
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory

import numpy as np

EVALUATOR = Path(__file__).resolve().parents[4] / "scripts/eval_mask_predictions.py"
CUTOFF = 0.995
GROUPS = 200
PROVIDED = 199


def run_toy(directory):
    group_ids = np.array([f"toy-{i}" for i in range(GROUPS)])
    truth = np.full((GROUPS, 44), -1, dtype=np.int16)
    truth[:, 0] = 0  # One target byte in each group.
    truth_path = directory / "truth.npz"
    np.savez(truth_path, target=truth >= 0, truth=truth, group_id=group_ids,
             capture=np.full(GROUPS, "toy-capture"), split="toy", task="control")

    probabilities = np.zeros((PROVIDED, 256))
    probabilities[:, 0] = 1
    predictions_path = directory / "predictions.npz"
    np.savez(predictions_path, group=group_ids[:PROVIDED], role=np.zeros(PROVIDED, dtype=int),
             j=np.zeros(PROVIDED, dtype=int), probs=probabilities)

    # A deliberately specified threshold gives the frozen and empirical summaries distinct results.
    thresholds_path = directory / "toy-thresholds.json"
    thresholds = {"at_precision": {str(CUTOFF): {"threshold": CUTOFF}}}
    thresholds_path.write_text(json.dumps({"metrics": {"method": {"bytes": thresholds, "bits": thresholds}}}))
    report_path = directory / "report.json"
    completed = subprocess.run(
        [sys.executable, "-B", str(EVALUATOR), "--truth", str(truth_path), "--predictions", str(predictions_path),
         "--no-baselines", "--frozen-thresholds", str(thresholds_path), "--out", str(report_path)],
        capture_output=True, text=True, check=True,
    )
    return json.loads(report_path.read_text()), json.loads(completed.stdout)["summary"]["method"]


def main():
    with TemporaryDirectory() as tmp:
        report, summary = run_toy(Path(tmp))

    predictions = report["predictions"]
    assert (predictions["provided"], predictions["missing"]) == (199, 1)
    metrics = report["metrics"]["method"]
    empirical_bytes = metrics["bytes"]["at_precision"][str(CUTOFF)]
    empirical_bits = metrics["bits"]["at_precision"][str(CUTOFF)]
    nominal_bytes = next(row for row in metrics["bytes"]["coverage"] if row["threshold"] == CUTOFF)
    nominal_bits = metrics["bits"]["at_nominal_confidence"][str(CUTOFF)]
    frozen_bytes = metrics["bytes"]["frozen"][str(CUTOFF)]
    frozen_bits = metrics["bits"]["frozen"][str(CUTOFF)]

    assert (empirical_bytes["called"], empirical_bytes["precision"], empirical_bytes["threshold"]) == (200, 0.99502, 1/256)
    assert (empirical_bits["called"], empirical_bits["precision"], empirical_bits["threshold"]) == (1600, 0.9975, 0.5)
    assert (nominal_bytes["called"], nominal_bytes["accuracy"]) == (199, 1.0)
    assert (nominal_bits["called"], nominal_bits["precision"]) == (1592, 1.0)
    assert frozen_bytes["called"] == 199 and frozen_bits["called"] == 1592
    assert summary["bits_per_group_995"] == empirical_bits["bits_per_group"] == 8.0
    assert frozen_bits["bits_per_group"] == 7.96

    print("The toy has 199 certain correct byte predictions and 1 omitted byte across 200 groups.")
    print(f"At 99.5% empirical precision, {empirical_bytes['called']}/200 bytes, {empirical_bits['called']}/1600 bits called.")
    print(f"At 99.5% nominal confidence, {nominal_bytes['called']}/200 bytes, {nominal_bits['called']}/1600 bits called.")
    print(f"At the frozen cutoff of 0.995, {frozen_bytes['called']}/200 bytes, {frozen_bits['called']}/1600 bits called.")
    print(f"The CLI prints bits_per_group_995={summary['bits_per_group_995']:.2f}. The frozen JSON reports {frozen_bits['bits_per_group']:.2f}.")


if __name__ == "__main__":
    main()
