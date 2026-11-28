"""Score SWB transition tags from the seven published November 25–26 receiver dumps.

Run predict first, then pass the SHA-256 it prints to score. Only score opens the
contributor's existing labels. Input receiver dumps begin after RF demodulation.
"""
import argparse
from collections import Counter, defaultdict
from hashlib import sha256
import json
from pathlib import Path
import sys

import numpy as np


def write(path, obj):
    raw = (json.dumps(obj, indent=2, sort_keys=True) + "\n").encode()
    with path.open("xb") as handle:
        handle.write(raw)
    print(sha256(raw).hexdigest())


def predictions(units, origins, sources):
    from archived import MODE_POSITIONS, PACKET_STARTS
    from evs_transition_tags import allowed_pairs

    cases = []
    for (counter, phase), unit in sorted(units.items()):
        for cycle in range(5):
            mode = int(unit[MODE_POSITIONS[4 * cycle]])
            if 0x60 <= mode <= 0x67:
                p31 = int(unit[PACKET_STARTS[4 * cycle] + 31])
                pairs = allowed_pairs(mode, p31)
                cases.append(dict(counter=counter, phase=phase, cycle=cycle, position=1,
                                  mode=f"{mode:02X}", p31=f"{p31:02X}", allowed=pairs))
    return dict(source_sha256={name: s["source_sha256"] for name, s in sources.items()},
                accepted_unique_dus=len(units), received_p1=5 * len(units), cases=cases)


def reviewed_columns(units, origins):
    from archived import CONTRIB, INPUTS
    from review_supplied_records import review

    labels = {}; witnesses = {}; digests = {}
    for tag in sorted(set(INPUTS.values())):
        path = CONTRIB / "keys" / f"keys_{tag}.npz"
        digests[tag] = sha256(path.read_bytes()).hexdigest()
        ticks = sorted(coord for coord, names in origins.items() if any(INPUTS[n] == tag for n in names))
        counters, phases = zip(*ticks, strict=True)
        with np.load(path, allow_pickle=False) as f:
            ids, supplied, flags = (f[k] for k in ("counters", "ks", "crc_supported"))
        chosen, records = review(ids, supplied, flags, np.array(counters), np.array(phases),
                                 np.array([units[t] for t in ticks], dtype=np.uint8))
        if np.any(chosen & ~flags):
            raise ValueError("unexpected expansion of contributor support")
        labels[tag] = {int(c): (key, flag, accepted)
                       for c, key, flag, accepted in zip(ids, supplied, flags, chosen, strict=True)}
        header_body = defaultdict(list)
        for r in records:
            first = r["counter"] * 3 + r["phase"]
            end = 2 + r["body_length"]
            def octet(i):
                tick, column = divmod(i, 16)
                coord = divmod(first + tick, 3)
                return int(units[coord][698 + column]) ^ int(labels[tag][coord[0]][0][column])
            crc_hex = f"{octet(end):02X}{octet(end+1):02X}"
            for i in range(0, end, 16):  # column zero in the actual header/body of this verified record
                counter = (first + i // 16) // 3
                header_body[counter].append(dict(start_counter=r["counter"], start_phase=r["phase"],
                    header=r["header_hex"], crc=crc_hex, record_offset=i))
        witnesses[tag] = header_body
    return labels, witnesses, digests


def counts(rows):
    n = Counter(labelled_transitions=len(rows))
    size = Counter()
    examples = {}
    disagreements = []
    for r, observed, witnesses in rows:
        pairs = r["allowed"]
        size[len(pairs)] += 1
        if not pairs:
            n["contradictions"] += 1
            continue
        if len(pairs) == 4:
            continue
        n["restrictive_words"] += 1
        n["pair_membership_matches"] += observed in pairs
        if observed not in pairs:
            disagreements.append(dict(r, observed_pair=observed, records=witnesses))
        n["pair_alternatives_excluded"] += 4 - len(pairs)
        n["exact_pair_predictions"] += len(pairs) == 1
        n["exact_pair_matches"] += len(pairs) == 1 and observed in pairs
        bits = []
        for bit, shift in ((8, 1), (9, 0)):
            values = {pair >> shift & 1 for pair in pairs}
            if len(values) == 1:
                value = values.pop()
                n[f"b{bit}_predictions"] += 1
                n[f"b{bit}_matches"] += value == (observed >> shift & 1)
                n[f"b{bit}_predicted_{value}"] += 1
                bits.append(f"b{bit}={value}")
        n["pair_only_restrictions"] += not bits
        n["pair_only_matches"] += not bits and observed in pairs
        key = ",".join(bits) or "pair_only"
        if key not in examples and witnesses:
            examples[key] = dict(r, observed_pair=observed, record=witnesses[0])
    return dict(counts=n, allowed_pair_count=size, examples=examples, disagreements=disagreements)


def scores(frozen, units, origins):
    from archived import INPUTS, PACKET_STARTS, support

    labels, witnesses, digests = reviewed_columns(units, origins)
    full, header_body = [], []
    for r in frozen["cases"]:
        coord = r["counter"], r["phase"]
        names = origins[coord]
        supplied, _ = support(r["counter"], names, labels)
        if "reviewed_full_p1" not in supplied:
            continue
        p0 = int(units[coord][PACKET_STARTS[4 * r["cycle"]]]) ^ supplied["reviewed_full_p1"]
        records = []
        for tag in sorted({INPUTS[n] for n in names}):
            label = labels[tag].get(r["counter"])
            if label is not None and label[2][:11].all():
                records.extend(witnesses[tag].get(r["counter"], []))
        entry = (r, p0 >> 6, records)
        full.append(entry)
        if records:
            header_body.append(entry)
    return dict(label_source_sha256=digests, reviewed_full_p1=counts(full),
                header_or_body_column=counts(header_body))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[3])
    subs = parser.add_subparsers(dest="action", required=True)
    pred = subs.add_parser("predict")
    pred.add_argument("output", type=Path)
    assess = subs.add_parser("score")
    assess.add_argument("predictions", type=Path)
    assess.add_argument("sha256")
    assess.add_argument("output", type=Path)
    args = parser.parse_args()
    sys.path.insert(0, str(args.repo / "examples/nov27/validation/hq-class"))
    sys.path.insert(0, str(args.repo / "scripts"))
    from archived import transport

    frozen = None
    if args.action == "score":
        raw = args.predictions.read_bytes()
        if sha256(raw).hexdigest() != args.sha256:
            raise ValueError("predictions differ from frozen digest")
        frozen = json.loads(raw)
    units, origins, sources, _ = transport()
    projected = predictions(units, origins, sources)
    if args.action == "predict":
        write(args.output, projected)
    else:
        if projected != frozen:
            raise ValueError("transport or predicted fields differ from frozen projection")
        write(args.output, dict(predictions_sha256=args.sha256, **scores(frozen, units, origins)))
