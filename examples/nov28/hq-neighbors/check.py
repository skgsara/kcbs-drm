"""Measure SWB HQ neighbor constraints in complete groups of CRC-checked data units."""
import argparse
from collections import Counter, defaultdict
from hashlib import sha256
import json
from pathlib import Path
import sys

SCRIPTS = Path(__file__).resolve().parents[3] / "scripts"
sys.path.insert(0, str(SCRIPTS))
from evs_hq_neighbors import check_successor, eligible
from project_evs_group import checked_units
from render_continuous import MODE_POSITIONS


def selection(modes):
    result = []
    for count, groups in sorted(modes.items()):
        if len(groups) != 3:
            continue
        words = sum((groups[phase] for phase in range(3)), [])
        for central in range(1, len(words) - 1):
            if eligible(words[central - 1], words[central], words[central + 1] >> 1):
                result.append((count, central))
    return result


def counts(cases):
    totals = Counter(eligible=0, transient_excluded=0, inconclusive=0)
    for row in cases:
        totals["eligible"] += 1
        totals[row["outcome"]] += 1
    return dict(totals)


def measure(path, provenance=None, history=None):
    modes = defaultdict(dict)
    for counter, phase, unit in checked_units(path):
        modes[counter][phase] = [unit[i] for i in MODE_POSITIONS]
    complete = sorted(c for c, phases in modes.items() if len(phases) == 3)
    selected = selection(modes)
    coordinate_bytes = "".join(f"{c},{s}\n" for c, s in selected).encode()
    rows = []
    for counter, slot in selected:
        phase, ordinal = divmod(slot + 1, 20)
        held_back = modes[counter][phase][ordinal] & 1
        rows.append(dict(counter=counter, slot=slot, position=slot % 4 + 1, **check_successor(held_back)))
    result = dict(archive_sha256=sha256(path.read_bytes()).hexdigest(),
                  data_units=sum(map(len, modes.values())), complete_groups=len(complete),
                  selection_sha256=sha256(coordinate_bytes).hexdigest(), all_positions=counts(rows),
                  by_position={str(p): counts(r for r in rows if r["position"] == p) for p in range(1, 5)},
                  cases=rows)
    if provenance is not None and history is not None:
        physical = json.loads(provenance.read_bytes())
        assigned = {int(k.partition(",")[0]) for k in physical}
        if not set(modes).issubset(assigned):
            raise ValueError("DU archive contains coordinates absent from packet provenance")
        starts = {int(k.partition(",")[0]): min(v[1] for v in values)
                  for k, values in physical.items() if k.endswith(",0,0")}
        historical = json.loads(history.read_bytes())["counter_ids"]
        overlap = sorted(assigned.intersection(historical))
        primary = min(complete, key=starts.__getitem__) if complete and not overlap else None
        result.update(all_assigned_counters=sorted(assigned), previously_seen=overlap, primary=primary,
                      primary_summary=counts(r for r in rows if r["counter"] == primary),
                      first_restriction=min((r for r in rows if r["outcome"] == "transient_excluded"),
                                            key=lambda r: (starts[r["counter"]], r["slot"]), default=None))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data_units", type=Path)
    parser.add_argument("--provenance", type=Path)
    parser.add_argument("--history", type=Path)
    args = parser.parse_args()
    if (args.provenance is None) != (args.history is None):
        parser.error("supply both --provenance and --history for a prospective test")
    print(json.dumps(measure(args.data_units, args.provenance, args.history), indent=2))
