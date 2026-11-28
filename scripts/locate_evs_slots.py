"""Locate supplied EVS words using the mode and 21 directly transmitted payload octets."""
import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import sys
from zipfile import BadZipFile

from check_evs_origin import PROJECTED_OCTETS
from compare_evs_group import read_words
from project_evs_group import checked_units
from received_evs_packets import PACKET_BYTES, read_packet_snapshot
from render_continuous import MODE_POSITIONS, PACKET_STARTS


DIRECT_OFFSETS = [
    (mode, *(start + j - 1 for j in PROJECTED_OCTETS[1:]))
    for mode, start in zip(MODE_POSITIONS, PACKET_STARTS, strict=True)
]


def unit_locations(counter, phase, unit, present=None):
    for i, offsets in enumerate(DIRECT_OFFSETS):
        if present is not None and not all(present[j // PACKET_BYTES] for j in offsets):
            continue
        cycle, role = divmod(i, 4)
        yield (counter, phase, cycle, role + 1), bytes(unit[j] for j in offsets)


def received_locations(path):
    for counter, phase, unit in checked_units(path):
        yield from unit_locations(counter, phase, unit)


def build_index(data_units_path, extra_packets=None):
    locations = defaultdict(list)
    units = {(c, p): unit for c, p, unit in checked_units(data_units_path)}
    for (counter, phase), unit in units.items():
        for coordinate, direct in unit_locations(counter, phase, unit):
            locations[direct].append(coordinate)
    if extra_packets is not None:
        ticks, rows, flags = read_packet_snapshot(extra_packets)
        for tick, row, present in zip(ticks, rows, flags, strict=True):
            counter, phase = divmod(int(tick), 3)
            original = units.get((counter, phase))
            if original is not None:
                for q, ok in enumerate(present):
                    start = q * PACKET_BYTES
                    end = start + PACKET_BYTES
                    if ok and original[start:end] != row[start:end].tobytes():
                        raise ValueError(f"packet conflicts with DU at {counter}/{phase}/{q}")
                continue
            for coordinate, direct in unit_locations(counter, phase, row, present):
                locations[direct].append(coordinate)
    return locations


def outcome(candidates):
    if not candidates:
        return "unmatched"
    return "unique" if len(candidates) == 1 else "ambiguous"


def export_locations(index, export_path):
    for i, word in enumerate(read_words(export_path)):
        direct = bytes(word[j] for j in PROJECTED_OCTETS) if word else None
        candidates = index.get(direct, [])
        yield dict(input_slot=i, outcome=outcome(candidates) if word else "erasure", candidates=candidates)


def check_against_receiver(index, peer_path):
    indexed = {coord for coords in index.values() for coord in coords}
    counts = {"present": Counter(), "absent": Counter()}
    for truth, direct in received_locations(peer_path):
        candidates = index.get(direct, [])
        result = outcome(candidates)
        if result == "unique":
            result = "unique_correct" if candidates[0] == truth else "unique_wrong"
        elif result == "ambiguous":
            result = "ambiguous_includes_true" if truth in candidates else "ambiguous_excludes_true"
        counts["present" if truth in indexed else "absent"][result] += 1
    return dict(indexed_slots=len(indexed), distinct_projections=len(index), by_true_coordinate=counts)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data_units", type=Path, help="CRC-checked complete data_units.npz to search")
    parser.add_argument("--extra-packets", type=Path, help="also index fully observed projections from packets.npz")
    query = parser.add_mutually_exclusive_group(required=True)
    query.add_argument("--export", type=Path, help="G.192 or EVS storage words, optionally gzipped")
    query.add_argument("--peer-dus", type=Path, help="score lookup against another receiver's known coordinates")
    args = parser.parse_args()
    try:
        index = build_index(args.data_units, args.extra_packets)
        if args.export:
            counts = Counter()
            for row in export_locations(index, args.export):
                print(json.dumps(row))
                counts[row["outcome"]] += 1
            print(json.dumps({"complete": True, "input_slots": sum(counts.values()), "counts": counts}))
        else:
            print(json.dumps(check_against_receiver(index, args.peer_dus), indent=2))
    except (OSError, ValueError, BadZipFile) as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
