"""Score three directly transmitted SWB GSC fields on CRC-checked complete groups."""
import argparse
from collections import Counter, defaultdict
from hashlib import sha256
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from evs_gsc_fields import FIELD_DEFINITIONS, has_noisy_pitch, mode_predictions, observed_field
from project_evs_group import checked_units
from render_continuous import MODE_POSITIONS, PACKET_STARTS


FIELDS = ("audio_noisy", "inactive_nibble", "noisy_pitch_fill")
# Values these three fixed rules can predict before a capture is scored.
POSSIBLE_PREDICTIONS = {"audio_noisy": (0, 1), "inactive_nibble": (12,), "noisy_pitch_fill": (0,)}


def seal(rows):
    """Hash numerically sorted decision rows as compact ASCII JSON without a trailing LF."""
    rows.sort()
    encoded = json.dumps(rows, separators=(",", ":")).encode("ascii")
    return {"decisions": len(rows), "sha256": sha256(encoded).hexdigest()}


def totals(checks):
    correct = sum(expected == observed for _, _, expected, observed in checks)
    return {"eligible": len(checks), "correct": correct, "disagreements": len(checks) - correct}


def summarize(name, checks, primary):
    groups = defaultdict(list)
    for row in checks:
        counter, slot = row[:2]
        groups[counter, slot % 4 + 1].append(row)
    tested = sorted({r[2] for r in checks})
    primary_cases = [
        {"slot": s, "phase": s // 20, "cycle": (s % 20) // 4, "position": s % 4 + 1,
         "expected": exp, "observed": obs}
        for c, s, exp, obs in checks if c == primary
    ]
    primary_checks = [row for row in checks if row[0] == primary]
    correct_fifteens = defaultdict(list)
    for (c, p), rows in sorted(groups.items()):
        if len(rows) == 15 and all(e == o for _, _, e, o in rows):
            correct_fifteens[c].append(p)

    def positions(rows):
        return {p: totals([r for r in rows if r[1] % 4 + 1 == p]) for p in range(1, 5)}

    return {**totals(checks), **FIELD_DEFINITIONS[name], "by_position": positions(checks),
            "expected_values": dict(sorted(Counter(r[2] for r in checks).items())),
            "untested_possible_predictions": sorted(set(POSSIBLE_PREDICTIONS[name]) - set(tested)),
            "observed_values": dict(sorted(Counter(r[3] for r in checks).items())),
            "counters_with_15_of_15_correct": dict(correct_fifteens),
            "primary": {**totals(primary_checks), "by_position": positions(primary_checks),
                        "cases": primary_cases},
            "discrepancies": [{"counter": c, "slot": s, "position": s % 4 + 1,
                               "expected": e, "observed": o}
                              for c, s, e, o in checks if e != o]}


def evaluate(path):
    phases = defaultdict(dict)
    for counter, phase, unit in checked_units(path):
        phases[counter][phase] = unit
    complete = sorted(c for c, rows in phases.items() if len(rows) == 3)
    primary = complete[0] if complete else None

    # Stage one reads mode octets only. CRC and coordinate verification precedes selection.
    by_mode = []
    for c in complete:
        for phase in range(3):
            unit = phases[c][phase]
            for i, offset in enumerate(MODE_POSITIONS):
                mode = unit[offset]
                for name, expected in mode_predictions(mode):
                    by_mode.append((c, phase * 20 + i, mode, name, expected))
    first = seal(by_mode)

    checks = {name: [] for name in FIELDS}
    by_pitch = []
    for c, slot, mode, name, expected in by_mode:
        phase, i = divmod(slot, 20)
        octet = phases[c][phase][PACKET_STARTS[i] + 4]
        checks[name].append((c, slot, expected, observed_field(name, octet)))
        if name == "audio_noisy" and has_noisy_pitch(mode, octet):
            by_pitch.append((c, slot, mode, octet >> 3, "noisy_pitch_fill", 0))
    second = seal(by_pitch)

    # The p26 scorer must run after every mode+p4 decision has entered the hash.
    for c, slot, mode, p4_high_five, name, expected in by_pitch:
        phase, i = divmod(slot, 20)
        octet = phases[c][phase][PACKET_STARTS[i] + 26]
        checks[name].append((c, slot, expected, observed_field(name, octet)))

    credited = {(c, s) for rows in checks.values() for c, s, _, _ in rows}
    confirmed = {(c, s) for rows in checks.values() for c, s, e, o in rows if e == o}
    return {"format": "evs-gsc-direct-fields-v1", "data_units_sha256": sha256(path.read_bytes()).hexdigest(),
            "received_dus": sum(map(len, phases.values())), "complete_groups": len(complete),
            "incomplete_counters_excluded": len(phases) - len(complete), "primary_counter": primary,
            "complete_group_slots": 60 * len(complete),
            "unique_word_coordinates_with_a_prediction": len(credited),
            "unique_word_coordinates_with_a_correct_prediction": len(confirmed),
            "primary_unique_word_coordinates_with_a_prediction": sum(c == primary for c, _ in credited),
            "primary_unique_word_coordinates_with_a_correct_prediction": sum(c == primary for c, _ in confirmed),
            "mode_decisions_before_p4": first, "mode_and_p4_decisions_before_p26": second,
            "fields": {name: summarize(name, rows, primary) for name, rows in checks.items()}}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("data_units", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    args.out.write_text(json.dumps(evaluate(args.data_units), indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
