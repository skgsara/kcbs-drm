"""Test the received P4 octet at payload offset 30 against a frozen codec-context table."""
import argparse
from collections import Counter, defaultdict
from hashlib import sha256
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "scripts"))
from project_evs_group import checked_units
from render_continuous import MODE_POSITIONS, PACKET_STARTS


def complete_groups(paths):
    phases = defaultdict(dict)
    for path in paths:
        for counter, phase, unit in checked_units(path):
            previous = phases[counter].setdefault(phase, unit)
            if previous != unit:
                raise ValueError(f"Conflicting data units at {counter}/{phase}")
    return {count: phases[count] for count in sorted(phases) if len(phases[count]) == 3}


def slots(groups):
    for count, phases in groups.items():
        for phase in range(3):
            for index, (mode, start) in enumerate(zip(MODE_POSITIONS, PACKET_STARTS, strict=True)):
                unit = phases[phase]
                # The signature excludes the target and all nominally masked octets.
                key = bytes([unit[mode], unit[start+28], unit[start+29], unit[start+31]]).hex()
                yield count, phase * 20 + index, key, unit, start


def most_common(table):
    # Deterministic tie break toward the lower received octet.
    return {k: min(v, key=lambda b: (-v[b], b)) for k, v in table.items()}


def signature(key, context):
    return key if context == "full" else key[:2] + key[-2:]


def train(paths, context):
    groups = complete_groups(paths)
    contexts, modes = defaultdict(Counter), defaultdict(Counter)
    for _, slot, key, unit, start in slots(groups):
        if slot % 4 == 3:
            observed = unit[start+30]
            contexts[signature(key, context)][observed] += 1
            modes[key[:2]][observed] += 1
    return dict(training_counters=list(groups), context_kind=context,
                context=most_common(contexts), mode=most_common(modes))


def predict(model, groups):
    common = set(model["training_counters"]).intersection(groups)
    if common:
        raise ValueError(f"Training and test have {len(common)} counters in common")
    rows = []
    for count, slot, key, _, _ in slots(groups):
        lookup = signature(key, model["context_kind"])
        if lookup in model["context"]:
            rows.append(dict(counter=count, slot=slot, mode=key[:2], context=key,
                             guess=model["context"][lookup], mode_baseline=model["mode"][key[:2]]))
    return dict(test_counters=list(groups), context_kind=model["context_kind"], predictions=rows)


def score(prediction, groups):
    if list(groups) != prediction["test_counters"]:
        raise ValueError("Scoring groups differ from the sealed prediction population")
    observations = {(c, s): (k, unit[start+30]) for c, s, k, unit, start in slots(groups)}
    strata = defaultdict(list)
    for row in prediction["predictions"]:
        c, s = row["counter"], row["slot"]
        key, value = observations[c, s]
        if key != row["context"] or row["mode"] != key[:2]:
            raise ValueError("Scoring context differs from the sealed prediction")
        strata[s % 4 + 1, row["mode"]].append((row, value))
    scored = []
    for (position, _), pairs in strata.items():
        for i, (row, value) in enumerate(pairs):
            # A singleton has no different partner for the shifted control.
            shifted = pairs[(i + len(pairs)//2) % len(pairs)][1] if len(pairs) >= 2 else None
            scored.append(dict(**row, position=position, received=value, correct=row["guess"] == value,
                               mode_correct=row["mode_baseline"] == value,
                               shifted_correct=None if shifted is None else row["guess"] == shifted))
    scored.sort(key=lambda r: (r["counter"], r["slot"]))
    first = next(iter(groups), None)

    def totals(rows, eligible):
        comparable = [r for r in rows if r["shifted_correct"] is not None]
        return dict(eligible=eligible, attempted=len(rows), abstained=eligible-len(rows),
                    correct=sum(r["correct"] for r in rows), mode_correct=sum(r["mode_correct"] for r in rows),
                    shift_comparable=len(comparable), correct_on_shift_comparable=sum(r["correct"] for r in comparable),
                    shifted_correct=sum(r["shifted_correct"] for r in comparable),
                    distinct_attempted_counters=len({r["counter"] for r in rows}))

    return dict(complete_groups=len(groups), primary_counter=first,
                primary_p4=totals([r for r in scored if r["counter"] == first and r["position"] == 4], 15 if groups else 0),
                by_position={p: totals([r for r in scored if r["position"] == p], len(groups)*15) for p in range(1, 5)},
                scope="Targets are received octets. Each guess is statistical; all clear alternatives remain possible.",
                slots=scored)


def save(output, obj):
    with output.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(obj, stream, sort_keys=True, separators=(",", ":"))
        stream.write("\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    training = commands.add_parser("train")
    training.add_argument("output", type=Path)
    training.add_argument("archives", type=Path, nargs="+")
    training.add_argument("--context", choices=("full", "last"), default="full",
                          help="full uses payload 28, 29, 31; last uses only 31. Both include mode.")
    run = commands.add_parser("predict")
    run.add_argument("model", type=Path)
    run.add_argument("archive", type=Path)
    run.add_argument("output", type=Path)
    check = commands.add_parser("score")
    check.add_argument("prediction", type=Path)
    check.add_argument("prediction_sha256")
    check.add_argument("archive", type=Path)
    check.add_argument("output", type=Path)
    args = parser.parse_args()
    if args.action == "train":
        result = train(args.archives, args.context)
    elif args.action == "predict":
        result = predict(json.loads(args.model.read_bytes()), complete_groups([args.archive]))
    else:
        data = args.prediction.read_bytes()
        if sha256(data).hexdigest() != args.prediction_sha256:
            parser.error("prediction digest differs from the sealed digest")
        result = score(json.loads(data), complete_groups([args.archive]))
    save(args.output, result)
    print(sha256(args.output.read_bytes()).hexdigest(), args.output)


if __name__ == "__main__":
    main()
