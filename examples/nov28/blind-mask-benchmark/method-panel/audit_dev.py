"""Check the published DEV aggregate receipts using only the Python standard library."""
from decimal import Decimal
import hashlib
import json
from pathlib import Path


PANEL = Path(__file__).resolve().parent
ROOT = PANEL.parents[3]


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def check_hash(relative_path, expected):
    digest = hashlib.sha256((ROOT / relative_path).read_bytes()).hexdigest()
    if digest != expected:
        raise ValueError(f"{relative_path}: SHA-256 differs from the frozen record")
    return digest


def acoustic_row(block):
    # A bit count on n groups advances in steps of 1/n bits per group.
    # The selected receipts report enough decimal places to identify that count.
    groups = block["groups"]
    bit_calls = Decimal(str(block["bits_per_group_995"])) * groups
    if bit_calls != bit_calls.to_integral_value():
        raise ValueError("The displayed rate does not yield an integer bit count")
    return {
        "groups": groups,
        "byte_items": block["items"],
        "tie_aware_byte_top1": block["top1"],
        "bits_called_at_empirical_995": int(bit_calls),
        "bytes_called_at_empirical_995": None,
    }


def audit():
    benchmark = PANEL.parent
    registry = load(benchmark / "split.json")
    hashes = {}
    for key in ("builder", "evaluator", "protocol", "baselines"):
        entry = registry[key]
        hashes[entry["path"]] = check_hash(entry["path"], entry["sha256"])
    for method in ("acoustic", "learned-disc", "params", "rule-prior"):
        freeze = load(PANEL / f"{method}.freeze.json")
        entry = freeze["script"]
        if isinstance(entry, str):
            path, digest = entry, freeze["script_sha256"]
        else:
            path, digest = entry["path"], entry["sha256"]
        hashes[path] = check_hash(path, digest)

    runs = load(PANEL / "acoustic.freeze.json")["evaluation_runs"]
    acoustic = runs["dev.T1"]
    acoustic_comparison = {name: acoustic_row(acoustic[name])
                           for name in ("method", "mode_prior", "derange_control")}
    if len({(row["groups"], row["byte_items"]) for row in acoustic_comparison.values()}) != 1:
        raise ValueError("The three summaries for the same DEV run disagree on denominators")
    wrong_key = acoustic_row(runs["dev.T1 wrong-key decoded control"]["method"])
    full = load(benchmark / "baselines-dev.json")["runs"]["dev.T1"]
    prior = full["mode_prior"]
    return {
        "sha256_verified": hashes,
        "full_dev_T1_mode_prior": {
            "groups": full["groups"], "byte_items": full["items"],
            "tie_aware_byte_top1": prior["top1"],
            "bits_called_at_empirical_995": prior["bits_at_precision"]["0.995"]["called"],
        },
        "dev_T1_acoustic_subset": acoustic_comparison,
        "separate_wrong_key_subset": wrong_key,
    }


if __name__ == "__main__":
    print(json.dumps(audit(), indent=2, sort_keys=True))
