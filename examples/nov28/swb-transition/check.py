"""Evaluate the stock SWB transition-tag constraint on CRC-checked broadcast DUs."""
import argparse
from collections import Counter, defaultdict
from hashlib import sha256
import json
from pathlib import Path
import sys

SCRIPTS = Path(__file__).resolve().parents[3] / "scripts"
sys.path.insert(0, str(SCRIPTS))
from evs_transition_tags import field
from project_evs_group import checked_units
from render_continuous import MODE_POSITIONS, PACKET_STARTS


def counts(rows):
    c = Counter(eligible=0, restricted=0, unrestricted=0, contradiction=0, fixed_bits=0,
                fixed_b8=0, fixed_b9=0, pair_only=0)
    for r in rows:
        c["eligible"] += 1
        c[r["outcome"]] += 1
        c["fixed_bits"] += len(r["fixed_word_bits"])
        c["fixed_b8"] += "8" in r["fixed_word_bits"]
        c["fixed_b9"] += "9" in r["fixed_word_bits"]
        c["pair_only"] += r["outcome"] == "restricted" and not r["fixed_word_bits"]
    return dict(c)


def run(data_units, provenance, prior):
    phases = defaultdict(set)
    cases = []
    for counter, phase, du in checked_units(data_units):
        phases[counter].add(phase)
        for i, (m, p) in enumerate(zip(MODE_POSITIONS, PACKET_STARTS, strict=True)):
            r = field(du[m], du[p + 31])
            if r is not None:
                cases.append(dict(counter=counter, slot=phase * 20 + i, position=i % 4 + 1, **r))
    physical = json.loads(provenance.read_bytes())
    assigned = sorted({int(key.partition(",")[0]) for key in physical})
    starts = {int(key.partition(",")[0]): min(row[1] for row in rows)
              for key, rows in physical.items() if key.endswith(",0,0")}
    if set(phases).difference(assigned):
        raise ValueError("DU archive and physical packet provenance disagree")
    complete = sorted((k for k, p in phases.items() if len(p) == 3), key=starts.__getitem__)
    ids = json.loads(prior.read_bytes())["counter_ids"]
    overlap = sorted(set(ids).intersection(assigned))
    primary = complete[0] if complete and not overlap else None
    full = set(complete)
    full_cases = [r for r in cases if r["counter"] in full]
    primary_cases = [r for r in full_cases if r["counter"] == primary]
    first = next((r for r in sorted(full_cases, key=lambda r: (starts[r["counter"]], r["slot"]))
                  if r["outcome"] == "restricted"), None)
    return dict(archive_sha256=sha256(data_units.read_bytes()).hexdigest(),
                historical_inventory_sha256=sha256(prior.read_bytes()).hexdigest(),
                all_assigned_counters=assigned, overlap=overlap, complete_in_time_order=complete,
                du_count=sum(map(len, phases.values())), complete_slots=60*len(complete), primary=primary,
                primary_summary=counts(primary_cases), first_restriction=first, complete_summary=counts(full_cases),
                complete_by_position={str(p): counts(r for r in full_cases if r["position"] == p)
                                      for p in range(1, 5)},
                complete_group_cases=full_cases, partial_group_cases=[r for r in cases if r["counter"] not in full])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("data_units", "provenance", "historical_inventory"):
        parser.add_argument(name, type=Path)
    args = parser.parse_args()
    print(json.dumps(run(args.data_units, args.provenance, args.historical_inventory), indent=2))
