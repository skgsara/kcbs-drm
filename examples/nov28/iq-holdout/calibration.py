"""Score previously published 13:17 slot labels against a complete-group HQ observation JSON."""
import argparse
from collections import Counter
import csv
from hashlib import sha256
import json
from pathlib import Path


LABELS = Path(__file__).resolve().parents[2] / "nov27/validation/hq-class"


def score(path):
    raw = path.read_bytes()
    report = json.loads(raw)
    labels = {}
    for pos, name in [(1, "development-observations.csv"), (2, "p2-labels.csv")]:
        with (LABELS / name).open(newline="") as f:
            for row in csv.DictReader(f):
                if row["capture"] != "1317":
                    continue
                slot = int(row["group_slot" if pos == 1 else "slot_in_group"])
                mode = row["mode"]
                if int(row["position"]) != pos or slot % 4 + 1 != pos:
                    raise ValueError("inconsistent label coordinates")
                if pos == 1:
                    code = row["class_code"]
                    value = int(code[-1] if mode == "F9" else code, 2)
                else:
                    if int(row["verified_record_count"]) < 1:
                        raise ValueError("P2 label lacks a text witness")
                    value = int(row["observed"], 2)
                coord = (int(row["counter"]), slot)
                if coord in labels:
                    raise ValueError("duplicate comparison")
                labels[coord] = mode, value

    totals = {str(pos): {mode: Counter() for mode in ("F9", "FA", "FB")} for pos in range(1, 5)}
    scored = []
    for r in report["cases"]:
        mode, pos = r["mode"], r["position"]
        counts = totals[str(pos)][mode]
        counts["eligible"] += 1
        label = labels.get((r["counter"], r["slot"]))
        if label is None:
            counts["no_label"] += 1
            continue
        source_mode, value = label
        if source_mode != mode:
            raise ValueError("received and label modes differ")
        allowed = r["allowed_high_two_bits"]
        valid = any(pair >> 1 == value for pair in allowed) if mode == "F9" else value in allowed
        counts["match" if valid else "mismatch"] += 1
        scored.append(dict(counter=r["counter"], slot=r["slot"], position=pos, mode=mode,
                           target="bit_8" if mode == "F9" else "pair_8_9",
                           observed=value, allowed=allowed, matched=valid))
    return dict(predictions_sha256=sha256(raw).hexdigest(), complete_groups=report["complete_groups"],
                eligible=report["conditional_words"], by_position=totals, scored=scored)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("predictions", type=Path)
    print(json.dumps(score(parser.parse_args().predictions), indent=2))
