"""Forecast the directly carried p5 byte at disjoint EVS slots using held-out centers."""
import argparse
from collections import Counter, defaultdict
from hashlib import sha256
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
NOV = HERE.parents[1] / "nov28"
sys.path.insert(0, str(NOV / "same-6140-1232"))
from native_groups import native_groups
from project_evs_group import checked_units
from render_continuous import MODE_POSITIONS, PACKET_STARTS

MEMBER = NOV / "member-3205-20min/member-dus.npz"
MEMBER_SHA = "5be01db5e77f42b5b6ddd05fec8d0dee146f48356cdc7d89dd98edc8a04bae5f"
OFFSET = 5
CENTERS = range(1, 59, 3)


def octet(triple, slot, addresses, offset=0):
    phase, local = divmod(slot, 20)
    return triple[phase][addresses[local] + offset]


def features(groups):
    # Only non-center slots contribute payload bytes. Triples may cross a DU boundary.
    return [(c, s, octet(t, s - 1, MODE_POSITIONS), octet(t, s, MODE_POSITIONS),
             octet(t, s + 1, MODE_POSITIONS), octet(t, s - 1, PACKET_STARTS, OFFSET),
             octet(t, s + 1, PACKET_STARTS, OFFSET))
            for c, t in groups.items() for s in CENTERS]


def decisions(rows, model):
    return [(c, s, m, left, model["by_mode"].get(str(m), model["fallback"]))
            for c, s, lm, m, rm, left, right in rows if lm == m == rm and left == right]


def labelled(predictions, groups):
    return [[c, s, m, pred, base, octet(groups[c], s, PACKET_STARTS, OFFSET)]
            for c, s, m, pred, base in predictions]


def complete_dus(path):
    units = {(c, p): unit for c, p, unit in checked_units(path)}
    return {c: [units[c, phase] for phase in range(3)]
            for c, p in sorted(units) if p == 0 and (c, 1) in units and (c, 2) in units}


def most_common(counter):
    return min(counter, key=lambda value: (-counter[value], value))


def train():
    if sha256(MEMBER.read_bytes()).hexdigest() != MEMBER_SHA:
        raise ValueError("development archive differs from the published source")
    groups = complete_dus(MEMBER)
    rows = features(groups)
    predicted = decisions(rows, dict(by_mode={}, fallback=0))
    global_counts = Counter()
    modes = defaultdict(Counter)
    for _, _, mode, _, _, target in labelled(predicted, groups):
        global_counts[target] += 1
        modes[mode][target] += 1
    return dict(source_sha256=MEMBER_SHA, groups=len(groups), eligible=len(predicted),
                training_counter_ids=sorted(groups), offset=OFFSET, fallback=most_common(global_counts),
                by_mode={str(mode): most_common(counts) for mode, counts in sorted(modes.items())})


def forecast(msc, model):
    raw = msc.read_bytes()
    native, originals, _, groups = native_groups(raw)
    rows = features(groups)
    candidates = decisions(rows, model)
    # Transport and feature digests are receipts. The predictor above does not receive either.
    return dict(native_sha256=sha256(raw).hexdigest(), transport=native, counters=list(groups),
                primary=originals[0] if originals else None, physical_slots=60 * len(groups),
                reserved_centers=len(rows), same_mode_centers=sum(lm == m == rm for _, _, lm, m, rm, _, _ in rows),
                context_sha256=sha256(json.dumps(rows, separators=(",", ":")).encode("ascii")).hexdigest(),
                prediction_columns=["counter", "zero_based_slot", "mode", "neighbor_byte", "mode_baseline_byte"],
                predictions=candidates)


def summarize(scores, opportunities):
    exact = sum(p == y for _, _, _, p, _, y in scores)
    mode_exact = sum(b == y for _, _, _, _, b, y in scores)
    common = sum(p == b == y for _, _, _, p, b, y in scores)
    return dict(reserved_centers=opportunities, predictions=len(scores), abstentions=opportunities - len(scores),
                exact=exact, wrong=len(scores) - exact, mode_baseline_exact=mode_exact,
                both_exact=common, only_consensus_exact=exact - common, only_mode_baseline_exact=mode_exact - common,
                consensus_exact_bits=sum(8 - (p ^ y).bit_count() for _, _, _, p, _, y in scores),
                bits_compared=8 * len(scores), counters_with_predictions=len({row[0] for row in scores}))


def breakdown(scores, ids):
    keep = [r for r in scores if r[0] in ids]
    return dict(all=summarize(keep, 20 * len(ids)), by_position={
        str(p + 1): summarize([r for r in keep if r[1] % 4 == p], 5 * len(ids)) for p in range(4)})


def score(msc, model, path, seal):
    raw = path.read_bytes()
    if sha256(raw).hexdigest() != seal:
        raise ValueError("different forecast seal")
    frozen = json.loads(raw)
    if json.loads(json.dumps(forecast(msc, model))) != frozen:
        raise ValueError("forecast differs from the frozen receiver and input")
    _, _, _, groups = native_groups(msc.read_bytes())
    measured = labelled(frozen["predictions"], groups)
    ids = set(frozen["counters"])
    return dict(forecast_sha256=seal, model_fit_overlap=sorted(ids.intersection(model["training_counter_ids"])),
                primary=breakdown(measured, {frozen["primary"]["counter"]} if frozen["primary"] else set()),
                all_groups=breakdown(measured, ids),
                groups_with_all_issued_predictions_exact=sum(
                    all(row[3] == row[5] for row in measured if row[0] == c) for c in {r[0] for r in measured}),
                results_columns=frozen["prediction_columns"] + ["received_target"], results=measured)


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    sub = cli.add_subparsers(dest="action", required=True)
    sub.add_parser("train")
    for command in ("forecast", "score"):
        parser = sub.add_parser(command)
        parser.add_argument("msc", type=Path)
        if command == "score":
            parser.add_argument("forecasts", type=Path)
            parser.add_argument("seal")
    args = cli.parse_args()
    if args.action == "train":
        result = train()
    else:
        model = json.loads((HERE / "model.json").read_bytes())
        if args.action == "forecast":
            result = forecast(args.msc, model)
        else:
            result = score(args.msc, model, args.forecasts, args.seal)
    print(json.dumps(result, indent=2))
