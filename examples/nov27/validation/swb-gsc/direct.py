"""Predict a directly transmitted SWB GSC AUDIO noisy-speech bit from the mode octet."""
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


def predict(mode):
    if mode >> 3 != 13:
        return None
    return 0 if mode & 4 else 1


def score(archive):
    groups = {}
    for counter, phase, unit in checked_units(archive):
        groups.setdefault(counter, {})[phase] = unit
    predictions = []
    complete = sorted(c for c, phases in groups.items() if len(phases) == 3)
    for counter in complete:
        for phase in range(3):
            unit = groups[counter][phase]
            for i, mode_index in enumerate(MODE_POSITIONS):
                mode = unit[mode_index]
                predicted = predict(mode)
                if predicted is not None:
                    slot = phase * 20 + i
                    predictions.append(dict(counter=counter, slot=slot, position=1+slot%4,
                                            mode=f"{mode:02X}", predicted=predicted))

    # Materialize and hash all decisions before opening any held-back b40.
    decision_hash = sha256(json.dumps(predictions, separators=(",", ":")).encode()).hexdigest()
    lanes = {c: [Counter() for _ in range(4)] for c in complete}
    counts = Counter()
    disagreements = []
    for row in predictions:
        phase, index = divmod(row["slot"], 20)
        unit = groups[row["counter"]][phase]
        observed = unit[PACKET_STARTS[index] + 4] >> 7
        expected = row["predicted"]
        key = f"predicted_{expected}_observed_{observed}"
        lanes[row["counter"]][row["position"] - 1][key] += 1
        counts[key] += 1
        if observed != expected:
            disagreements.append(dict(**row, observed=observed))
    return {"data_units_sha256": sha256(archive.read_bytes()).hexdigest(), "complete_groups": len(complete),
            "first_complete": next(iter(complete), None), "complete_slots": 60*len(complete),
            "eligible": len(predictions), "decision_sha256": decision_hash, "counts": dict(counts),
            "disagreements": disagreements, "by_counter_positions_1_to_4": lanes}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data_units", type=Path)
    options = parser.parse_args()
    print(json.dumps(score(options.data_units), indent=2))
