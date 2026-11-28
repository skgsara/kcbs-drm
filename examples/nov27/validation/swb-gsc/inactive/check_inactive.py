"""Freeze and score the empirical 1100 nibble rule on already CRC-verified transport."""
import argparse
import binascii
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path

import numpy as np


def save(path, value):
    raw = (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode("ascii")
    with path.open("xb") as output:
        output.write(raw)
    return sha256(raw).hexdigest()


def archive(path):
    with np.load(path, allow_pickle=False) as data:
        counters, phases, units = data["counters"], data["phases"], data["du"]
    if (counters.ndim != 1 or phases.shape != counters.shape or units.shape != (len(counters), 716)
            or units.dtype != np.uint8 or counters.dtype.kind not in "iu" or phases.dtype.kind not in "iu"):
        raise ValueError("Invalid transport array dimensions or types")
    groups = {}
    for counter, phase, row in zip(counters, phases, units, strict=True):
        counter, phase = int(counter), int(phase)
        if (not 0 <= counter < 2**32 or phase not in range(3) or row[1] >> 4 != phase
                or phase == 0 and int.from_bytes(row[664:668], "big") != counter):
            raise ValueError("Invalid data-unit coordinates")
        if (binascii.crc_hqx(row[:-2].tobytes(), 0xffff) ^ 0xffff) != int.from_bytes(row[-2:], "big"):
            raise ValueError("Invalid data-unit CRC")
        phases_at_counter = groups.setdefault(counter, {})
        if phase in phases_at_counter:
            raise ValueError("Duplicate counter/phase")
        phases_at_counter[phase] = row
    return {c: groups[c] for c in sorted(groups) if len(groups[c]) == 3}


def seal(args):
    groups = archive(args.data)
    rows = []
    for counter, phases in groups.items():
        for phase in range(3):
            for cycle in range(5):
                for pos, base in enumerate((2, 39, 72, 105)):
                    offset = base + (cycle if pos == 0 else 131 * cycle)
                    mode = int(phases[phase][offset])
                    if mode >> 3 == 14:
                        rows.append([counter, 20 * phase + 4 * cycle + pos, mode, 12])
    data = {"archive_sha256": sha256(args.data.read_bytes()).hexdigest(),
            "complete_counters": list(groups), "prediction_columns": ["counter", "slot", "mode", "predicted"],
            "predictions": rows}
    print(save(args.out, data), len(groups), len(rows))


def summarize(rows, n):
    observed = Counter(r[-1] for r in rows)
    return {"slots": n, "eligible": len(rows), "abstained": n - len(rows), "correct": observed[12],
            "wrong": len(rows) - observed[12], "observed_hex_histogram": {f"{v:X}": observed[v] for v in sorted(observed)}}


def score(args):
    raw = args.sealed.read_bytes()
    if sha256(raw).hexdigest() != args.sha256:
        raise ValueError("Prediction file differs from the externally frozen digest")
    data = json.loads(raw)
    if data["archive_sha256"] != sha256(args.data.read_bytes()).hexdigest():
        raise ValueError("Scoring archive differs from the prediction archive")
    groups = archive(args.data)
    if list(groups) != data["complete_counters"]:
        raise ValueError("Complete counters differ")
    primary = next(iter(groups), None)
    result_rows = []
    for counter, slot, mode, predicted in data["predictions"]:
        phase, i = divmod(slot, 20)
        cycle, pos = divmod(i, 4)
        start = 131 * cycle + (7, 40, 73, 106)[pos]
        value = int(groups[counter][phase][start + 4]) >> 4
        result_rows.append((counter, slot, mode, predicted, value))
    def view(rows, ng):
        return {"total": summarize(rows, 60 * ng),
                "by_position": {p: summarize([r for r in rows if r[1] % 4 == p - 1], 15 * ng) for p in range(1, 5)}}
    primary_rows = [r for r in result_rows if r[0] == primary]
    failures = [r for r in result_rows if r[-1] != r[-2]]
    by_value = {}
    for r in failures:
        by_value.setdefault(f"{r[-1]:X}", r)
    group_positions = Counter((r[0], r[1] % 4 + 1) for r in result_rows)
    exact = Counter((r[0], r[1] % 4 + 1) for r in result_rows if r[-1] == r[-2])
    result = {"decision_sha256": args.sha256, "archive_sha256": data["archive_sha256"], "complete_groups": len(groups),
              "all": view(result_rows, len(groups)), "first_complete": primary, "primary": view(primary_rows, int(primary is not None)),
              "group_positions_with_15_eligible": sum(n == 15 for n in group_positions.values()),
              "group_positions_with_15_correct": sum(n == 15 for n in exact.values()), "possible_group_positions": 4 * len(groups),
              "distinct_counters_with_errors": len({r[0] for r in failures}), "first_failure_by_observed_nibble": by_value,
              "failure_columns": ["counter", "slot", "mode_octet_decimal", "predicted_decimal", "observed_decimal"]}
    if args.failures:
        result["all_failure_coordinates_sha256"] = save(args.failures, failures)
    print(save(args.out, result), result["all"]["total"])


def main():
    p = argparse.ArgumentParser(description=__doc__)
    commands = p.add_subparsers(dest="action", required=True)
    for name in ("seal", "score"):
        action = commands.add_parser(name)
        action.add_argument("data", type=Path)
        action.add_argument("out", type=Path)
        if name == "score":
            action.add_argument("sealed", type=Path)
            action.add_argument("sha256")
            action.add_argument("--failures", type=Path)
    args = p.parse_args()
    (seal if args.action == "seal" else score)(args)


if __name__ == "__main__":
    main()
