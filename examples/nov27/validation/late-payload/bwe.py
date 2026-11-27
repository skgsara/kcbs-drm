"""Locate and check the stock bandwidth-extension class in ordinary SWB EVS.

The prediction inputs are the mode and three guaranteed direct payload octets.
An optional, separately supported early octet can identify the transition tag.
The function never receives payload octet 24 or 27.
"""
import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "scripts"))
from project_evs_group import checked_units
from render_continuous import MODE_POSITIONS, PACKET_STARTS


PADDING = {"1": 0, "0101": 1, "0100": 3, "011": 6, "001": 2, "0001": 6, "0000": 0}


def predict(mode, p5, p28, p31, early_octet=None):
    """Describe feasible class locations and the bits the receiver can check directly."""
    family = mode >> 3
    if not mode & 4 or family not in (10, 12, 19):
        return None
    if family == 12:
        head = f"{mode & 3:02b}"
        if early_octet is not None:
            head += f"{early_octet:08b}"
        choices = [(tag, pad, 51 + len(tag)) for tag, pad in PADDING.items()
                   if tag.startswith(head) or head.startswith(tag)]
    else:
        choices = [("", 0, 48)]

    branches = []
    for tag, pad, fec in choices:
        if p31 & ((1 << pad) - 1):
            continue
        # All candidate FEC high bits are in p5, including the 4-bit tag case.
        voiced_or_onset = (p5 >> (55 - fec)) & 1
        # Physical word bits start at the mode MSB. Payload octet 28
        # supplies b232..239. Only read class bits that actually fall in it.
        start = 233 - pad
        available = [(i, (p28 >> (239 - (start+i))) & 1)
                     for i in range(2) if start+i >= 232]
        observed = [value for value in range(4)
                    if all(((value >> (1-i)) & 1) == b for i, b in available)]
        possible = [value for value in observed if not (voiced_or_onset and value == 1)]
        branches.append({"tag": tag, "start": start, "direct_class_bits": len(available),
                         "fec_high": voiced_or_onset, "observed_class_options": observed,
                         "standard_class_options": possible})

    supported = [row for row in branches if row["standard_class_options"]]
    if not supported:
        outcome = "direct_contradiction"
    elif all(r["fec_high"] and r["direct_class_bits"] == 2 for r in supported):
        outcome = "direct_class_checked"
    elif all(r["fec_high"] and r["start"] < 232 for r in supported):
        outcome = "class_crosses_unknown_payload"
    else:
        outcome = "unresolved_or_inapplicable"
    return {"outcome": outcome, "branches": branches}


def score(path):
    phases = {}
    for counter, phase, unit in checked_units(path):
        phases.setdefault(counter, {})[phase] = unit
    groups = sorted(counter for counter, data in phases.items() if len(data) == 3)
    outcomes = []
    for counter in groups:
        counts = Counter()
        witnesses = []
        for phase in range(3):
            unit = phases[counter][phase]
            for i, (m, p) in enumerate(zip(MODE_POSITIONS, PACKET_STARTS, strict=True)):
                mode = unit[m]
                row = predict(mode, unit[p+5], unit[p+28], unit[p+31])
                if row is None:
                    continue
                counts["eligible"] += 1
                generic = mode >> 3 != 12
                counts["generic" if generic else "transition"] += 1
                counts[row["outcome"]] += 1
                witnesses.append({"slot": 20 * phase + i, "position": 1 + i % 4,
                                  "mode": f"{mode:02X}", **row})
        outcomes.append({"counter": counter, "counts": dict(counts), "witnesses": witnesses})
    total = Counter()
    for row in outcomes:
        total.update(row["counts"])
    return {"data_units_sha256": sha256(path.read_bytes()).hexdigest(),
            "complete_groups": len(groups), "slots": len(groups)*60,
            "first_complete": next(iter(groups), None), "total": dict(total),
            "groups": outcomes}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data_units", type=Path)
    args = parser.parse_args()
    print(json.dumps(score(args.data_units), indent=2))
