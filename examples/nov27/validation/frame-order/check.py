"""Check 96 fixed in-group layouts using received EVS mode and payload octet 5.

A layout lists the original on-wire slot indices in the proposed order. The
normal layout is cycle-major, ascending cycles 0..14, positions 1,2,3,4.
Optional boundary checks join the last and first proposed slots only where
both complete group counters are numerically consecutive. No gap is bridged.
"""
import argparse
from functools import lru_cache
from hashlib import sha256
import importlib.util
from itertools import permutations
import json
from pathlib import Path
import sys

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
sys.path.insert(0, str(ROOT / "scripts"))
from evs_core_history import previous_core
from project_evs_group import checked_units
from render_continuous import MODE_POSITIONS, PACKET_STARTS

spec = importlib.util.spec_from_file_location("acelp_class_history", HERE.parent / "acelp-class-history/check.py")
speech = importlib.util.module_from_spec(spec)
spec.loader.exec_module(speech)

CHRONOLOGICAL = "cycle-asc-1234"
METRICS = ("hq_eligible", "hq_predicted_switch", "hq_contradictions", "acelp_eligible",
           "acelp_restrictive", "acelp_previous_high_bit_predicted_zero", "acelp_contradictions")


def layouts():
    for major in ("cycle", "role"):
        for direction, cycles in (("asc", range(15)), ("desc", range(14, -1, -1))):
            for roles in permutations(range(4)):
                if major == "cycle":
                    slots = [4*c+r for c in cycles for r in roles]
                else:
                    slots = [4*c+r for r in roles for c in cycles]
                name = f"{major}-{direction}-" + "".join(str(r+1) for r in roles)
                yield name, slots


def received_groups(path):
    phases = {}
    for counter, phase, du in checked_units(path):
        phases.setdefault(counter, {})[phase] = [
            (du[m], du[p+5]) for m, p in zip(MODE_POSITIONS, PACKET_STARTS, strict=True)
        ]
    groups = {c: v[0]+v[1]+v[2] for c,v in sorted(phases.items()) if len(v) == 3}
    return groups, len(phases) - len(groups)


@lru_cache(maxsize=65536)
def score_pair(earlier, later):
    before_mode, earlier_octet = earlier
    after_mode, later_octet = later
    before_core = previous_core(before_mode)
    hq = before_core is not None and after_mode >> 3 >= 29 and not (after_mode & 4)
    switched = hq and before_core == "ACELP"
    hq_error = hq and bool(after_mode & 2) != switched

    prediction = speech.predict(before_mode, after_mode, later_octet)
    eligible = prediction is not None
    restricted = eligible and bool(prediction["excluded"])
    high_zero = eligible and prediction["successor_class"] == 3
    acelp_error = restricted and speech.field(earlier_octet, prediction["word_bit_start"]) in prediction["excluded"]
    return hq, switched, hq_error, eligible, restricted, high_zero, acelp_error


def as_counts(counts):
    return dict(zip(METRICS, map(int, counts), strict=True))


def add_pairs(pairs):
    counts = [0] * len(METRICS)
    for earlier, later in pairs:
        for index, hit in enumerate(score_pair(earlier, later)):
            counts[index] += hit
    return np.array(counts, dtype=np.int64)


def evaluate(groups, boundaries=False):
    orders = dict(layouts())
    rows = list(groups.values())
    counters = list(groups)
    if counters != sorted(counters) or any(len(row) != 60 for row in rows):
        raise ValueError("expected sorted complete 60-word groups")
    neighbors = [(c, c+1) for c in counters if c+1 in groups]
    edges = {edge for order in orders.values() for edge in zip(order, order[1:])}
    within = {(i,j): add_pairs((r[i], r[j]) for r in rows) for i,j in edges}
    across = {}
    if boundaries:
        endpoints = {(order[-1], order[0]) for order in orders.values()}
        across = {(i,j): add_pairs((groups[a][i], groups[b][j]) for a,b in neighbors) for i,j in endpoints}

    results = {}
    for name, order in orders.items():
        totals = sum((within[edge] for edge in zip(order, order[1:])), np.zeros(len(METRICS), dtype=np.int64))
        result = {"within": as_counts(totals)}
        if boundaries:
            result["boundary_only"] = as_counts(across[order[-1],order[0]])
        results[name] = result

    primary = None
    if rows:
        primary = {"counter": counters[0], "within": as_counts(add_pairs(zip(rows[0], rows[0][1:])))}
    first_boundary = None
    if boundaries and neighbors:
        a,b = neighbors[0]
        first_boundary = {"from_counter": a, "from_slot": 59, "to_counter": b, "to_slot": 0,
                          "boundary_only": as_counts(score_pair(groups[a][59], groups[b][0]))}
    return {"complete_groups": len(rows), "within_edges_per_layout": len(rows)*59,
            "boundary_checks_requested": boundaries, "boundary_edges_per_layout": len(neighbors) if boundaries else 0,
            "layout_count": len(orders), "chronological_layout": CHRONOLOGICAL, "primary_chronological": primary,
            "first_chronological_boundary": first_boundary, "layouts": results}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data_units", type=Path, help="received data_units.npz")
    parser.add_argument("--boundaries", action="store_true", help="also score consecutive complete counters")
    parser.add_argument("--out", type=Path, help="write compact JSON to a file; default is stdout")
    args = parser.parse_args()
    groups, incomplete = received_groups(args.data_units)
    report = evaluate(groups, args.boundaries)
    report.update(data_units_sha256=sha256(args.data_units.read_bytes()).hexdigest(),
                  incomplete_counters_excluded=incomplete)
    output = json.dumps(report, indent=2) + "\n"
    if args.out:
        args.out.write_text(output, encoding="utf-8")
    else:
        sys.stdout.write(output)


if __name__ == "__main__":
    main()
