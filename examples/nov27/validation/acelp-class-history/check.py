"""Use a successor ACELP class to predict allowed values of the preceding two-bit class."""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys
import numpy as np

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "scripts"))
from project_evs_group import project_group
from render_continuous import MODE_POSITIONS, PACKET_STARTS
from tail_fill_audit import crc


def class_start(mode):
    """Return the first physical bit if the mode alone locates both bits in octet 6."""
    if mode is None:
        return None
    index = mode >> 3
    if index in (0, 10, 15, 19):  # NB or SWB GENERIC
        return 48
    if index in (5, 17):  # WB GENERIC
        return 49 if mode & 4 else 50
    if index == 2:  # NB TRANSITION, tag begins at bit 5
        length = 1 if mode & 4 else (3 if mode & 1 else 4)
        return 50 + length
    if index in (7, 12) and mode & 2:  # WB/SWB TRANSITION, one-bit tag
        return 53 if index == 7 and not mode & 4 else 52
    return None


def field(octet, start):
    return (octet >> (54 - start)) & 3


def predict(previous_mode, next_mode, next_octet):
    """The held-back previous payload octet is absent from the prediction inputs."""
    before, after = class_start(previous_mode), class_start(next_mode)
    if before is None or after is None or next_octet is None:
        return None
    successor = field(next_octet, after)
    excluded = {2: [0], 3: [2, 3]}.get(successor, [])
    return dict(word_bit_start=before, successor_class=successor, excluded=excluded)


def score(counter, observations):
    if len(observations) != 60:
        raise ValueError("expected the 60 chronological slots of one group")
    counts = Counter(dict.fromkeys(("eligible_pairs", "restrictive_pairs", "contradictions",
                                    "predict_prior_msb_zero", "wrong_msb"), 0))
    checks = []
    for slot in range(59):
        mode, held_back = observations[slot]
        answer = predict(mode, *observations[slot + 1])
        if answer is None or held_back is None:
            continue
        observed = field(held_back, answer["word_bit_start"])
        violation = observed in answer["excluded"]
        counts["eligible_pairs"] += 1
        counts["restrictive_pairs"] += bool(answer["excluded"])
        counts["contradictions"] += violation
        counts["predict_prior_msb_zero"] += answer["successor_class"] == 3
        counts["wrong_msb"] += answer["successor_class"] == 3 and bool(observed & 2)
        checks.append(dict(slot=slot, position=1 + slot % 4, **answer,
                           held_back_class=observed, contradicted=violation))
    return dict(counter=counter, counts=dict(counts), checks=checks)


def score_group(projection):
    observations = []
    for slot, row in enumerate(projection["slots"]):
        if row["counter"] != projection["counter"] or row["slot"] != slot:
            raise ValueError("projected slots out of order")
        tokens = row["octets"].split()
        observations.append((int(tokens[0], 16), int(tokens[6], 16))
                            if row["receipt"] == "received_du" else (None, None))
    return score(projection["counter"], observations)


def score_archive(path):
    groups = {}
    with np.load(path, allow_pickle=False) as archive:
        for count, phase, raw in zip(archive["counters"], archive["phases"], archive["du"], strict=True):
            count, phase = int(count), int(phase)
            unit = raw.tobytes()
            phases = groups.setdefault(count, {})
            if (len(unit) != 716 or phase not in (0, 1, 2) or phase in phases
                    or unit[1] >> 4 != phase or crc(unit[:-2]) != int.from_bytes(unit[-2:], "big")
                    or (phase == 0 and int.from_bytes(unit[664:668], "big") != count)):
                raise ValueError(f"invalid or duplicate data unit at {count}/{phase}")
            phases[phase] = [(unit[mode], unit[payload + 5])
                             for mode, payload in zip(MODE_POSITIONS, PACKET_STARTS, strict=True)]
    summary = Counter()
    by_position = {p: Counter() for p in range(1, 5)}
    pairs = Counter()
    groups_scored = 0
    for counter, phases in sorted(groups.items()):
        if len(phases) != 3:
            continue
        groups_scored += 1
        result = score(counter, phases[0] + phases[1] + phases[2])
        summary.update(result["counts"])
        for row in result["checks"]:
            pairs[f"{row['held_back_class']}{row['successor_class']}"] += 1
            p = by_position[row["position"]]
            p["eligible_pairs"] += 1
            p["restrictive_pairs"] += bool(row["excluded"])
            p["contradictions"] += row["contradicted"]
    return dict(complete_groups=groups_scored, counts=dict(summary), by_position=by_position,
                observed_class_pairs=dict(sorted(pairs.items())))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data_units", type=Path)
    parser.add_argument("--counter", type=int, help="show each pair for one counter; default counts all complete groups")
    args = parser.parse_args()
    result = (score_archive(args.data_units) if args.counter is None
              else score_group(project_group(args.data_units, args.counter)))
    print(json.dumps(result, indent=2))
