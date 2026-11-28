"""Compare two receivers' direct EVS octets at the same counter, phase and word location."""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "scripts"))
from check_evs_origin import PROJECTED_OCTETS
from received_evs_packets import PACKET_BYTES, read_packet_snapshot
from render_continuous import MODE_POSITIONS, PACKET_STARTS


def received_phases(path):
    ticks, units, flags = read_packet_snapshot(path)
    return {int(t): (unit, present) for t, unit, present in zip(ticks, units, flags, strict=True)
            if present.any()}


def direct_octets(row):
    if row is None:
        return {}
    unit, present = row
    values = {}
    for slot, (mode, payload) in enumerate(zip(MODE_POSITIONS, PACKET_STARTS, strict=True)):
        for word_octet in PROJECTED_OCTETS:
            offset = mode if word_octet == 0 else payload + word_octet - 1
            if present[offset // PACKET_BYTES]:
                values[slot, word_octet] = unit[offset]
    return values


def compare(first, second):
    left, right = received_phases(first), received_phases(second)
    totals = Counter(first_direct_octets=0, second_direct_octets=0, union_direct_octets=0,
                     shared_direct_octets=0, matching_direct_octets=0, differing_direct_octets=0,
                     shared_packet_bodies=0, differing_packet_bodies=0, matches_in_partial_phases=0)
    by_counter = {}
    partial = []
    for tick in sorted(left.keys() | right.keys()):
        a, b = direct_octets(left.get(tick)), direct_octets(right.get(tick))
        totals.update(first_direct_octets=len(a), second_direct_octets=len(b),
                      union_direct_octets=len(a.keys() | b.keys()))
        if tick not in left or tick not in right:
            continue
        counter, phase = divmod(tick, 3)
        left_unit, left_flags = left[tick]
        right_unit, right_flags = right[tick]
        for q in np.flatnonzero(left_flags & right_flags):
            start = q * PACKET_BYTES
            end = start + PACKET_BYTES
            totals["shared_packet_bodies"] += 1
            if not np.array_equal(left_unit[start:end], right_unit[start:end]):
                totals["differing_packet_bodies"] += 1

        shared = a.keys() & b.keys()
        matches = [key for key in shared if a[key] == b[key]]
        totals.update(shared_direct_octets=len(shared), matching_direct_octets=len(matches),
                      differing_direct_octets=len(shared) - len(matches))
        if shared:
            positions = by_counter.setdefault(counter, [0, 0, 0, 0])
            for slot, _ in matches:
                positions[slot % 4] += 1
            if not (left_flags.all() and right_flags.all()):
                totals["matches_in_partial_phases"] += len(matches)
                partial.append(dict(counter=counter, phase=phase, shared=len(shared), matched=len(matches)))
    return dict(totals=dict(totals), matches_by_counter_and_position=by_counter, shared_partial_phases=partial)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("first", type=Path, help="first receiver's packets.npz from --save-packets")
    parser.add_argument("second", type=Path, help="second receiver's packets.npz from --save-packets")
    args = parser.parse_args()
    try:
        result = compare(args.first, args.second)
    except (OSError, ValueError) as error:
        parser.exit(2, f"{parser.prog}: {error}\n")
    print(json.dumps(result, indent=2))
    totals = result["totals"]
    return int(bool(totals["differing_direct_octets"] or totals["differing_packet_bodies"]))


if __name__ == "__main__":
    raise SystemExit(main())
