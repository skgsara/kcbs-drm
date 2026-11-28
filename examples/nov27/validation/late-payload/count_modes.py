"""Count the modes required by three late-octet EVS controls in a received DU archive."""
import argparse
from collections import Counter
from pathlib import Path
import sys


sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "scripts"))
from project_evs_group import checked_units
from render_continuous import MODE_POSITIONS


def count_modes(archive):
    positions = [Counter() for _ in range(4)]
    phases_per_counter = Counter()
    for counter, _, unit in checked_units(archive):
        phases_per_counter[counter] += 1
        for slot, offset in enumerate(MODE_POSITIONS):
            positions[slot % 4][unit[offset]] += 1
    complete = sum(count == 3 for count in phases_per_counter.values())
    print(f"{phases_per_counter.total()} CRC-checked DUs, {complete} complete counters")
    print("position  received  NB-13  WB-GSC-AUDIO  SWB-BWE")
    for position, modes in enumerate(positions, start=1):
        wb_gsc = sum(n for mode, n in modes.items() if mode >> 3 == 8)
        swb_bwe = sum(n for mode, n in modes.items() if mode & 4 and mode >> 3 in (10, 12, 19))
        print(f"P{position} {modes.total():15} {modes[0x13]:6} {wb_gsc:13} {swb_bwe:8}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path, help="complete, CRC-checked DUs tagged with counter and phase")
    count_modes(parser.parse_args().archive)
