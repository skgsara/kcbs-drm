"""Score the existing INACTIVE/BWE mode prediction on every complete group."""
import argparse
from collections import Counter, defaultdict
from hashlib import sha256
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "scripts"))
from evs_gsc_fields import mode_predictions, observed_field
from project_evs_group import checked_units
from render_continuous import MODE_POSITIONS, PACKET_STARTS


def score(path):
    groups = defaultdict(dict)
    for counter, phase, unit in checked_units(path):
        groups[counter][phase] = unit
    selected = []
    modes = Counter()
    for counter, phases in sorted(groups.items()):
        if len(phases) != 3:
            continue
        for phase, unit in sorted(phases.items()):
            for ordinal, mode_offset in enumerate(MODE_POSITIONS):
                mode = unit[mode_offset]
                modes[mode] += 1
                for name, prediction in mode_predictions(mode):
                    if name == "inactive_nibble":
                        selected.append((counter, 20 * phase + ordinal, prediction))
    target_values = Counter()
    by_position = Counter()
    mismatches = []
    for counter, slot, prediction in selected:
        phase, ordinal = divmod(slot, 20)
        payload4 = groups[counter][phase][PACKET_STARTS[ordinal] + 4]
        observed = observed_field("inactive_nibble", payload4)
        target_values[observed] += 1
        by_position[slot % 4 + 1] += 1
        if prediction != observed:
            mismatches.append(dict(counter=counter, slot=slot, observed=observed, expected=prediction))
    coordinates = "".join(f"{counter},{slot}\n" for counter, slot, _ in selected)
    return dict(data_units_sha256=sha256(path.read_bytes()).hexdigest(),
                complete_group_slots=sum(modes.values()),
                mode_counts={f"{mode:02X}": count for mode, count in sorted(modes.items())},
                eligible=len(selected), distinct_counters=len({r[0] for r in selected}),
                selected_coordinates_sha256=sha256(coordinates.encode()).hexdigest(),
                eligible_by_position={p: by_position[p] for p in range(1, 5)},
                observed_nibbles={f"{v:04b}": n for v, n in sorted(target_values.items())},
                mismatches=mismatches)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data_units", type=Path)
    args = parser.parse_args()
    print(json.dumps(score(args.data_units), indent=2))
