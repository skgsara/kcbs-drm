"""Collect conditional SWB HQ class restrictions using only received mode octets."""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "scripts"))
from project_evs_group import checked_units
from render_continuous import MODE_POSITIONS


def restriction(mode):
    """Return the allowed high two bits of payload octet 0, or None for an unrestricted field."""
    if mode == 0xF9:
        return (0, 1)
    if mode in (0xFA, 0xFB):
        return (0, 1, 2)
    return None


def observe(path, counter=None):
    modes = {}
    for count, phase, unit in checked_units(path):
        if counter is None or count == counter:
            modes.setdefault(count, {})[phase] = [unit[k] for k in MODE_POSITIONS]
    complete = sorted(k for k, v in modes.items() if len(v) == 3)
    counts = {p: Counter() for p in range(1, 5)}
    rows = []
    for count in complete:
        for phase in range(3):
            for index, mode in enumerate(modes[count][phase]):
                allowed = restriction(mode)
                if allowed is not None:
                    position = 1 + index % 4
                    counts[position][f"{mode:02X}"] += 1
                    rows.append(dict(counter=count, slot=phase*20 + index, position=position,
                                     mode=f"{mode:02X}", allowed_high_two_bits=allowed))
    return dict(complete_groups=len(complete), first_complete_counter=min(complete, default=None),
                other_incomplete_counters=len(modes) - len(complete), slots=len(complete)*60,
                conditional_words=len(rows), by_position=counts, cases=rows)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data_units", type=Path)
    parser.add_argument("--counter", type=int)
    args = parser.parse_args()
    print(json.dumps(observe(args.data_units, args.counter), indent=2))
