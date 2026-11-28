"""Check on-air availability of the narrowband EVS transition tag in published receptions."""
from hashlib import sha256
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from project_evs_group import checked_units
from render_continuous import MODE_POSITIONS


def main():
    census = json.loads((HERE / "public-census.json").read_bytes())
    units = {}
    for name, expected in census["sources"].items():
        path = ROOT / name
        if sha256(path.read_bytes()).hexdigest() != expected["sha256"]:
            raise ValueError(f"source changed: {name}")
        for counter, phase, unit in checked_units(path):
            if units.setdefault((counter, phase), unit) != unit:
                raise ValueError(f"disagreeing copies at {counter}/{phase}")
    hits = [[counter, phase * 20 + slot]
            for (counter, phase), unit in sorted(units.items())
            for slot, mode in enumerate(MODE_POSITIONS) if unit[mode] == 0x13]
    if len(units) != census["unique_dus"] or hits != census["eligible_coordinates"]:
        raise ValueError("airborne mode counts differ from receipt")
    print(f"{len(units)} unique DUs, {20 * len(units)} slots, {len(hits)} narrowband mode 13 words")


if __name__ == "__main__":
    main()
