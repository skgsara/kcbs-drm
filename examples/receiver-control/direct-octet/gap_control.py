"""Test the p5 neighbor rule on natural packet gaps of two historical receiver snapshots."""
import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import sys

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2] / "scripts"))
from project_evs_group import checked_units
from received_evs_packets import PACKET_BYTES, read_packet_snapshot
from render_continuous import MODE_POSITIONS, PACKET_STARTS

CENTERS = range(1, 59, 3)
METRICS = (
    "counters", "centers", "source_target_present", "source_target_missing", "missing_with_peer_target",
    "missing_with_both_neighbor_p5", "missing_with_all_five_source_fields",
    "all_five_source_fields", "all_five_with_matching_modes", "consensus_calls",
    "natural_gap_calls", "natural_gap_with_peer", "natural_gap_correct",
    "visible_center_calls", "visible_center_correct", "visible_calls_with_peer", "visible_peer_correct",
)


def address(slot, mode=False):
    phase, local = divmod(slot, 20)
    offset = MODE_POSITIONS[local] if mode else PACKET_STARTS[local] + 5
    return phase, offset


def packet(slot, mode=False):
    phase, offset = address(slot, mode)
    return phase, offset // PACKET_BYTES


def geometry(slots, distance=1):
    sharing = Counter(dict.fromkeys(("both", "left_only", "right_only", "neither"), 0))
    different_mode = []
    all_inputs_separate = []
    for slot in slots:
        center = packet(slot)
        neighbors = (slot - distance, slot + distance)
        sides = tuple(packet(neighbor) == center for neighbor in neighbors)
        modes = [packet(s, mode=True) for s in (*neighbors, slot)]
        if not any(sides) and center not in modes:
            all_inputs_separate.append(slot)
        label = {(True, True): "both", (True, False): "left_only", (False, True): "right_only",
                 (False, False): "neither"}[sides]
        sharing[label] += 1
        if packet(slot, mode=True) != center:
            different_mode.append(slot)
    return dict(centers=len(slots), same_packet_as_neighbor_p5=dict(sharing),
                same_packet_as_center_mode=len(slots) - len(different_mode),
                center_mode_in_different_packet_at=different_mode,
                all_five_inputs_outside_target_packet_at=all_inputs_separate)


def snapshot(path, complete_path=None):
    ticks, units, flags = read_packet_snapshot(path)
    result = {int(tick): (unit, ok) for tick, unit, ok in zip(ticks, units, flags, strict=True) if ok.any()}
    if complete_path:
        for counter, phase, unit in checked_units(complete_path):
            tick = counter * 3 + phase
            if tick in result:
                previous, ok = result[tick]
                present = np.repeat(ok, PACKET_BYTES)
                if not np.array_equal(np.frombuffer(unit, dtype=np.uint8)[present], previous[present]):
                    raise ValueError(f"Conflicting complete/partial inputs at {tick}")
            result[tick] = (unit, (True, True, True, True))
    return result


def received(rows, counter, slot, mode=False):
    phase, offset = address(slot, mode)
    record = rows.get(3 * counter + phase)
    if record is None or not record[1][offset // PACKET_BYTES]:
        return None
    return int(record[0][offset])


def count(counter, source, peer, slots, distance, complete_gaps):
    totals = Counter(dict.fromkeys(METRICS, 0))
    totals["counters"] = 1
    for slot in slots:
        left, right = slot - distance, slot + distance
        modes = [received(source, counter, s, mode=True) for s in (left, slot, right)]
        before, after = (received(source, counter, s) for s in (left, right))
        donors = before is not None and after is not None
        available = donors and None not in modes
        matched_modes = available and modes[0] == modes[1] == modes[2]
        call = matched_modes and before == after
        # Read the center only after deciding. A missing packet is never read.
        actual = received(source, counter, slot)
        witness = received(peer, counter, slot)
        missing = actual is None
        if missing and available and complete_gaps is not None:
            complete_gaps.append(dict(counter=counter, slot=slot, modes_equal=matched_modes,
                                      donor_octets_equal=before == after, peer_target_present=witness is not None))
        totals["centers"] += 1
        totals["source_target_present"] += not missing
        totals["source_target_missing"] += missing
        totals["missing_with_peer_target"] += missing and witness is not None
        totals["missing_with_both_neighbor_p5"] += missing and donors
        totals["missing_with_all_five_source_fields"] += missing and available
        totals["all_five_source_fields"] += available
        totals["all_five_with_matching_modes"] += matched_modes
        totals["consensus_calls"] += call
        totals["natural_gap_calls"] += call and missing
        totals["natural_gap_with_peer"] += call and missing and witness is not None
        totals["natural_gap_correct"] += call and missing and witness is not None and before == witness
        totals["visible_center_calls"] += call and not missing
        totals["visible_center_correct"] += call and not missing and before == actual
        totals["visible_calls_with_peer"] += call and not missing and witness is not None
        totals["visible_peer_correct"] += call and not missing and witness is not None and before == witness
    return totals


def direction(source, peer, slots, distance, *, list_complete_gaps=False):
    source_ids = {tick // 3 for tick in source}
    peer_ids = {tick // 3 for tick in peer}
    totals = Counter(dict.fromkeys(METRICS, 0))
    shared = totals.copy()
    complete_gaps = [] if list_complete_gaps else None
    for counter in sorted(source_ids):
        row = count(counter, source, peer, slots, distance, complete_gaps)
        totals.update(row)
        if counter in peer_ids:
            shared.update(row)
    result = dict(all_source_assigned_counters=dict(totals), shared_assigned_counters=dict(shared))
    if list_complete_gaps:
        result["missing_target_with_five_source_inputs"] = complete_gaps
    return result


def fingerprint(path):
    return sha256(path.read_bytes()).hexdigest()


def compare(left, right, left_complete=None, right_complete=None):
    first = snapshot(left, left_complete)
    second = snapshot(right, right_complete)
    result = dict(left_snapshot_sha256=fingerprint(left), right_snapshot_sha256=fingerprint(right),
                  left_complete_dus_sha256=fingerprint(left_complete) if left_complete else None,
                  right_complete_dus_sha256=fingerprint(right_complete) if right_complete else None)
    for name, slots, distance in arms():
        details = name == "same_role_geometry_eligible_only"
        result[name] = dict(left_to_right=direction(first, second, slots, distance, list_complete_gaps=details),
                            right_to_left=direction(second, first, slots, distance, list_complete_gaps=details))
    return result


def arms():
    inner = [s for s in CENTERS if 4 <= s < 56]
    eligible = geometry(inner, 4)["all_five_inputs_outside_target_packet_at"]
    return (("immediate_neighbors", CENTERS, 1), ("same_role_neighbors", inner, 4),
            ("same_role_geometry_eligible_only", eligible, 4))


def geometry_table():
    result = {name: geometry(slots, distance) for name, slots, distance in arms()}
    result["same_role_required_packets"] = {
        str(slot): {
            "target": packet(slot),
            "modes": [packet(s, mode=True) for s in (slot - 4, slot, slot + 4)],
            "donors": [packet(s) for s in (slot - 4, slot + 4)],
        } for slot in result["same_role_neighbors"]["all_five_inputs_outside_target_packet_at"]
    }
    result["all_interior_immediate_neighbors"] = geometry(range(1, 59))
    result["immediate_including_adjacent_counter_edges"] = geometry(range(60))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("left", type=Path)
    parser.add_argument("right", type=Path)
    parser.add_argument("--left-complete", type=Path, help="optional matching complete DU archive for a partial-only snapshot")
    parser.add_argument("--right-complete", type=Path)
    args = parser.parse_args()
    print(json.dumps(dict(geometry=geometry_table(),
                          comparison=compare(args.left, args.right, args.left_complete, args.right_complete)), indent=2))
