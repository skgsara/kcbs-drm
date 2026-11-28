"""Recheck public DEV aggregate receipts and the arithmetic of one fixed toy control."""
from decimal import Decimal
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
REVISION = "f79d70f85d0caf2e5c5f380c9c69d3781e048121"
BENCHMARK = "examples/nov28/blind-mask-benchmark"


def blob(path):
    result = subprocess.run(
        ["git", "--no-replace-objects", "cat-file", "blob", f"{REVISION}:{path}"],
        cwd=ROOT, env={**os.environ, "GIT_NO_LAZY_FETCH": "1", "GIT_ALLOW_PROTOCOL": ""},
        capture_output=True,
    )
    if result.returncode:
        raise ValueError(f"Could not read {REVISION}:{path} from the local Git objects")
    return result.stdout


def receipt(name):
    return json.loads(blob(f"{BENCHMARK}/{name}"))


def acoustic_row(block):
    bit_calls = Decimal(str(block["bits_per_group_995"])) * block["groups"]
    if bit_calls != bit_calls.to_integral_value():
        raise ValueError("Displayed rate does not determine an integer number of bit calls")
    return {
        "groups": block["groups"], "byte_items": block["items"], "byte_top1": block["top1"],
        "bits_called_empirical_995": int(bit_calls),
    }


def toy_counts():
    # The missing byte gets a uniform distribution. A tie contributes fractional credit.
    groups, supplied = 200, 199
    empirical_byte_precision = (supplied + 1 / 256) / groups
    empirical_bit_precision = (8 * supplied + 8 * 0.5) / (8 * groups)
    if min(empirical_byte_precision, empirical_bit_precision) < 0.995:
        raise ValueError("Taking every toy prediction falls below the empirical cutoff")
    return {
        "groups": groups, "supplied_bytes": supplied, "missing_bytes": groups - supplied,
        "empirical": {"bytes": groups, "bits": 8 * groups,
                      "byte_precision": round(empirical_byte_precision, 5),
                      "bit_precision": empirical_bit_precision, "bits_per_group": 8},
        "fixed_confidence_0.995": {"bytes": supplied, "bits": 8 * supplied,
                                  "bits_per_group": 8 * supplied / groups},
    }


def audit():
    registry = receipt("split.json")
    registered = {registry[k]["path"]: registry[k]["sha256"]
                  for k in ("builder", "evaluator", "protocol", "baselines")}
    freezes = {}
    for method in ("acoustic", "learned-disc", "params", "rule-prior"):
        entry = receipt(f"method-panel/{method}.freeze.json")
        freezes[method] = entry
        script = entry["script"]
        if isinstance(script, str):
            registered[script] = entry["script_sha256"]
        else:
            registered[script["path"]] = script["sha256"]
    hashes = {path: sha256(blob(path)).hexdigest() for path in registered}
    if len(hashes) != 8 or hashes != registered:
        raise ValueError("A source file differs from its registered SHA-256")

    runs = freezes["acoustic"]["evaluation_runs"]
    shared = runs["dev.T1"]
    results = {name: acoustic_row(shared[name]) for name in ("method", "mode_prior", "derange_control")}
    if len({(r["groups"], r["byte_items"]) for r in results.values()}) != 1:
        raise ValueError("The three shared-subset denominators differ")
    full = receipt("baselines-dev.json")["runs"]["dev.T1"]
    prior = full["mode_prior"]
    return {
        "revision": REVISION, "verified_sha256": hashes,
        "same_dev_T1_subset": results,
        "separate_wrong_key_subset": acoustic_row(runs["dev.T1 wrong-key decoded control"]["method"]),
        "full_dev_T1_mode_prior": {
            "groups": full["groups"], "byte_items": full["items"], "byte_top1": prior["top1"],
            "bits_called_empirical_995": prior["bits_at_precision"]["0.995"]["called"],
        },
        "toy_control": toy_counts(),
    }


if __name__ == "__main__":
    try:
        actual = audit()
        expected = json.loads((HERE / "expected.json").read_text(encoding="utf-8"))
        if actual != expected:
            raise ValueError("Recomputed results differ from expected.json")
        print(json.dumps(actual, indent=2, sort_keys=True))
    except (OSError, ValueError, KeyError) as exc:
        sys.exit(str(exc))
