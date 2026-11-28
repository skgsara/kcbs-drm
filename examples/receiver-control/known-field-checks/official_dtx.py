"""Calibrate two published EVS field rules on nine official SWB DTX streams."""
import argparse
from collections import Counter, defaultdict
from hashlib import sha256
import json
from pathlib import Path
import struct
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from evs_core_history import core_history
from evs_transition_tags import transition_tags
from dtx_catalog import expected_names, validate_member

GOOD, BAD = 0x6B21, 0x6B20
SLOTS = {"stv32c": 2760, "stv32n1": 700, "stv32n2": 700}


def basename(name):
    return Path(name).name.split("_", 1)[0]


def condition(name):
    return "f06" if name.endswith(".f06.COD") else "b10" if name.endswith(".b10.COD") else "clean"


def read_frames(raw):
    """Yield one entry per G.192 physical frame. A BFI payload has no usable bits."""
    at = 0
    while at < len(raw):
        if at + 4 > len(raw):
            raise ValueError("truncated G.192 header")
        sync, n = struct.unpack_from("<HH", raw, at)
        at += 4
        if sync not in (GOOD, BAD) or n not in (0, 48, 264) or at + 2*n > len(raw):
            raise ValueError(f"unexpected G.192 sync, length or extent at byte {at-4}: {sync:#x}, {n}")
        payload = memoryview(raw)[at:at + 2*n]
        at += 2*n
        if sync == BAD:
            yield "bad", n, None
            continue
        symbols = struct.unpack(f"<{n}H", payload)
        if any(v not in (0x7F, 0x81) for v in symbols):
            raise ValueError("unexpected serial bit symbol in good G.192 frame")
        if n != 264:
            yield ("sid" if n else "no_data"), n, None
            continue
        octets = bytes(sum((bit == 0x81) << (7-j) for j, bit in enumerate(symbols[i:i+8]))
                       for i in range(0, n, 8))
        yield "speech", n, octets


def save(path, data):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(data, stream, separators=(",", ":"), sort_keys=True)
        stream.write("\n")


def prepare(root, out):
    features, labels, hashes = {}, {}, {}
    for name in expected_names():
        raw = (root / name).read_bytes()
        validate_member(name, raw)
        hashes[name] = sha256(raw).hexdigest()
        rows, answers = [], []
        for kind, n, word in read_frames(raw):
            rows.append([kind, n, word[0] if word else None, word[-1] if word else None])
            if condition(name) == "clean":
                answers.append([kind, n, word[0] if word else None, word[1] >> 6 if word else None])
        if len(rows) != SLOTS[basename(name)]:
            raise ValueError(f"wrong physical frame count for {name}: {len(rows)}")
        features[name] = rows
        if condition(name) == "clean":
            labels[name] = answers
    # The three files for one stimulus represent the same physical chronology.
    for name, rows in features.items():
        clean = features[clean_name(name)]
        if any(a[1] != b[1] for a, b in zip(rows, clean, strict=True)):
            raise ValueError(f"frame bit lengths differ at the same slot in {name} and clean sibling")
    out.mkdir(parents=True, exist_ok=False)
    save(out/"features.json", {"schema": "dtx-features-v1", "files": hashes, "rows": features})
    save(out/"labels.json", {"schema": "dtx-sibling-labels-v1", "files": {k: hashes[k] for k in labels},
                             "rows": labels})


def clean_name(name):
    return name.replace(".f06.COD", ".COD").replace(".b10.COD", ".COD")


def predictions(rows):
    result = []
    for base in range(0, len(rows), 60):
        group = []
        for s, (kind, n, mode, last) in enumerate(rows[base:base+60]):
            if kind == "speech":
                if n != 264 or not all(type(v) is int and 0 <= v < 256 for v in (mode, last)):
                    raise ValueError("invalid speech observation")
                octets = " ".join([f"{mode:02X}", *(["??"]*31), f"{last:02X}"])
                receipt = "received_du"  # Reuse rule API; this is a good vector word, with no RF involved.
            else:
                if kind not in ("bad", "sid", "no_data") or mode is not None or last is not None:
                    raise ValueError("invalid excluded observation")
                receipt, octets = "missing", " ".join(["--"]*33)
            group.append(dict(slot=s, counter=base//60, phase=s//20, cycle=s%20//4,
                              position=1+s%4, receipt=receipt, octets=octets))
        pairs = {r["slot"]: r["allowed_high_pairs"] for r in transition_tags(group)["slots"]}
        previous = {r["slot"]: r["predicted"] for r in core_history(group)["slots"]
                    if r["outcome"] == "tcx_conditional"}
        for s, (kind, n, mode, _) in enumerate(rows[base:base+60]):
            result.append([kind, n, mode, pairs.get(s), previous.get(s)])
    return result


def predict(path, destination):
    raw = path.read_bytes()
    data = json.loads(raw)
    if data["schema"] != "dtx-features-v1" or set(data["rows"]) != set(expected_names()):
        raise ValueError("unexpected input cohort")
    guesses = {name: predictions(rows) for name, rows in data["rows"].items()}
    save(destination, dict(schema="dtx-forecasts-v1", files=data["files"],
                           features_sha256=sha256(raw).hexdigest(), rows=guesses))


def add_slot(c, row, answer):
    status, n, mode, pairs, prior = row
    clean_status, clean_n, clean_mode, pair = answer
    if n != clean_n:
        raise ValueError("unmatched physical frame bit lengths")
    c["slots"] += 1
    c[f"status_{status}_{n}"] += 1
    has_label = (status == clean_status == "speech" and mode == clean_mode)
    if status == "speech" and not has_label:
        c["speech_without_matching_clean_mode"] += 1
    if pairs is not None:
        c["transition_applicable"] += 1
        if len(pairs) == 4:
            c["transition_unrestricted"] += 1
        else:
            c["transition_restrictive"] += 1
            if has_label:
                c["transition_scored"] += 1
                c["transition_membership_correct"] += pair in pairs
                c["rotated_domain_membership_correct"] += ((pair - 1) % 4) in pairs
                c["transition_empty_domain"] += not pairs
                for shift in (1, 0):
                    allowed_bits = {p >> shift & 1 for p in pairs}
                    if len(allowed_bits) == 1:
                        bit = pair >> shift & 1
                        c["transition_fixed_bits"] += 1
                        c["transition_fixed_bits_correct"] += bit in allowed_bits
                        c["transition_zero_baseline_bits_correct"] += bit == 0
                if len(pairs) == 1:
                    c["transition_singletons"] += 1
                    c["transition_singleton_correct"] += pairs[0] == pair
                    c["transition_zero_baseline_singleton_correct"] += pair == 0
            else:
                c["transition_unlabelled"] += 1
    if prior is not None:
        c["tcx_applicable"] += 1
        if has_label:
            bit = pair >> 1
            c["tcx_scored"] += 1
            c[f"tcx_predict_{prior}_observed_{bit}"] += 1
            c["tcx_correct"] += prior == bit
            c["tcx_constant_zero_correct"] += bit == 0
            c["tcx_constant_one_correct"] += bit == 1
        else:
            c["tcx_unlabelled"] += 1


def score(pred_file, label_file, out):
    raw = pred_file.read_bytes()
    pred = json.loads(raw)
    gold = json.loads(label_file.read_bytes())
    names = set(expected_names())
    clean = {name for name in names if condition(name) == "clean"}
    if (pred["schema"] != "dtx-forecasts-v1" or gold["schema"] != "dtx-sibling-labels-v1"
            or pred["rows"].keys() != names or gold["rows"].keys() != clean
            or any(pred["files"][name] != gold["files"][name] for name in clean)):
        raise ValueError("forecast and sibling label sources differ")
    per_file, by_position = {}, defaultdict(lambda: defaultdict(Counter))
    for name in sorted(names):
        rows, answers = pred["rows"][name], gold["rows"][clean_name(name)]
        if len(rows) != SLOTS[basename(name)] or len(answers) != len(rows):
            raise ValueError(f"wrong slot count for {name}")
        total = Counter()
        for i, (row, answer) in enumerate(zip(rows, answers, strict=True)):
            one = Counter()
            add_slot(one, row, answer)
            total.update(one)
            by_position[condition(name)][str(i % 4 + 1)].update(one)
        per_file[name] = total
    per_condition = {}
    for key, positions in by_position.items():
        total = Counter()
        for scores in positions.values():
            total.update(scores)
        per_condition[key] = {"all": total, "by_position": positions}
    report = dict(forecast_sha256=sha256(raw).hexdigest(), features_sha256=pred["features_sha256"],
                  members_sha256=pred["files"], by_condition=per_condition, by_member=per_file)
    with out.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, sort_keys=True, indent=2)
        stream.write("\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    for action, fn, names in (("prepare", prepare, ["members", "fresh_out"]),
                              ("predict", predict, ["features", "forecasts"]),
                              ("score", score, ["forecasts", "labels", "report"])):
        command = sub.add_parser(action)
        for name in names:
            command.add_argument(name, type=Path)
        command.set_defaults(run=fn, names=names)
    args = parser.parse_args()
    args.run(*(getattr(args, name) for name in args.names))


if __name__ == "__main__":
    main()
