"""Compare the sealed scheduled reception with an independent receiver at the same transport coordinates."""
import argparse
from collections import Counter
from dataclasses import dataclass
import gzip
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import sys

from score import HERE, HISTORY_SHA256  # The frozen scheduled score and its repository imports.
from check_evs_origin import PROJECTED_OCTETS
from locate_evs_slots import unit_locations
from project_evs_group import project_group
from received_evs_packets import PACKET_BYTES, read_packet_snapshot


@dataclass
class Transport:
    archive: bytes
    packets: dict
    dus: dict
    groups: dict
    signatures: dict
    partial_groups: set


def read_transport(raw):
    ticks, units, flags = read_packet_snapshot(BytesIO(raw))
    packets, dus, signatures = {}, {}, {}
    partial = set()
    for tick, unit, present in zip(ticks, units, flags, strict=True):
        tick = int(tick)
        counter, phase = divmod(tick, 3)
        for ordinal, body in enumerate(unit.reshape(4, PACKET_BYTES)):
            if present[ordinal]:
                packets[4 * tick + ordinal] = body.tobytes()
        if present.all():
            dus[tick] = unit.tobytes()
        elif present.any():
            partial.add(counter)
        for (_, _, cycle, position), signature in unit_locations(counter, phase, unit, present):
            signatures[20 * tick + 4 * cycle + position - 1] = signature
    groups = {tick // 3: (dus[tick], dus[tick + 1], dus[tick + 2]) for tick in dus
              if tick % 3 == 0 and tick + 1 in dus and tick + 2 in dus}
    return Transport(raw, packets, dus, groups, signatures, partial)


def inclusive_ranges(keys):
    ranges = []
    for index in sorted(keys):
        if ranges and index == ranges[-1][-1] + 1:
            ranges[-1][1] = index
        else:
            ranges.append([index, index])
    return ranges


def overlap(scheduled, peer, *, locations=False):
    common = scheduled.keys() & peer.keys()
    conflicts = [key for key in common if scheduled[key] != peer[key]]
    scheduled_only = scheduled.keys() - peer.keys()
    peer_only = peer.keys() - scheduled.keys()
    result = dict(scheduled=len(scheduled), peer=len(peer), shared=len(common), equal=len(common) - len(conflicts),
                  conflicting=len(conflicts), scheduled_only=len(scheduled_only), peer_only=len(peer_only))
    if locations:
        result.update(conflicting_ranges=inclusive_ranges(conflicts), scheduled_only_ranges=inclusive_ranges(scheduled_only),
                      peer_only_ranges=inclusive_ranges(peer_only))
    return result


def signature_positions(scheduled, peer):
    return {position: overlap({k: v for k, v in scheduled.items() if k % 4 == position - 1},
                              {k: v for k, v in peer.items() if k % 4 == position - 1})
            for position in range(1, 5)}


def check_score(score, scheduled):
    registry = gzip.decompress((HERE / "history.json.gz").read_bytes())
    if sha256(registry).hexdigest() != HISTORY_SHA256 or score["prior_inventory_sha256"] != HISTORY_SHA256:
        raise ValueError("scheduled score and frozen registry differ")
    assigned = score["assigned_counters"]  # The original scorer also includes subsequently quarantined coordinates.
    if (not isinstance(assigned, list) or any(type(c) is not int or not 0 <= c <= 0xffffffff for c in assigned)
            or assigned != sorted(set(assigned))):
        raise ValueError("invalid assigned counters in scheduled score")
    if not {packet // 12 for packet in scheduled.packets}.issubset(assigned):
        raise ValueError("scheduled score omits a counter with received packets")
    if score["prior_overlap"] != sorted(set(assigned).intersection(json.loads(registry)["counter_ids"])):
        raise ValueError("scheduled score differs from frozen inventory intersection")
    for name, actual in (("complete_groups", len(scheduled.groups)),
                         ("groups_with_partial_packet_rows", len(scheduled.partial_groups))):
        if type(score[name]) is not int or score[name] != actual:
            raise ValueError(f"scheduled score differs from its archive for {name}")


def sealed_selection(score, label, scheduled):
    eligible = scheduled.groups if label == "primary" else scheduled.partial_groups
    recorded = score[label]
    if not eligible or score["prior_overlap"]:
        if recorded is not None:
            raise ValueError(f"unexpected {label} despite the frozen gate")
        status = "suppressed_by_frozen_overlap" if eligible else "no_eligible_group"
        return None, status
    if not isinstance(recorded, dict) or type(recorded.get("counter")) is not int or recorded["counter"] not in eligible:
        raise ValueError(f"missing or ineligible {label} in the sealed score")
    counter = recorded["counter"]
    source_group = project_group(BytesIO(scheduled.archive), counter, packets=True)
    if any(recorded.get(key) != value for key, value in source_group.items()):
        raise ValueError(f"sealed {label} projection differs from its scheduled packet archive")
    return source_group, "reported"


def direct_positions(source_group, peer_group):
    by_position = {}
    for position in range(1, 5):
        counts = Counter(slots=15, comparable_direct_bits=0, different_direct_bits=0,
                         scheduled_only_direct_bits=0, peer_only_direct_bits=0, neither_direct_bits=0,
                         complete_signatures_both=0, equal_signatures=0, conflicting_signatures=0,
                         scheduled_signature_only=0, peer_signature_only=0, neither_signature_complete=0)
        source_slots = source_group["slots"][position - 1::4]
        peer_slots = peer_group["slots"][position - 1::4]
        for left, right in zip(source_slots, peer_slots, strict=True):
            source_tokens, peer_tokens = left["octets"].split(), right["octets"].split()
            source_direct = [source_tokens[i] for i in PROJECTED_OCTETS]
            peer_direct = [peer_tokens[i] for i in PROJECTED_OCTETS]
            for source_byte, peer_byte in zip(source_direct, peer_direct, strict=True):
                if "--" not in (source_byte, peer_byte):
                    counts["comparable_direct_bits"] += 8
                    counts["different_direct_bits"] += (int(source_byte, 16) ^ int(peer_byte, 16)).bit_count()
                elif source_byte == peer_byte:
                    counts["neither_direct_bits"] += 8
                elif source_byte == "--":
                    counts["peer_only_direct_bits"] += 8
                else:
                    counts["scheduled_only_direct_bits"] += 8
            if "--" not in source_direct and "--" not in peer_direct:
                counts["complete_signatures_both"] += 1
                counts["equal_signatures" if source_direct == peer_direct else "conflicting_signatures"] += 1
            elif "--" not in source_direct:
                counts["scheduled_signature_only"] += 1
            elif "--" not in peer_direct:
                counts["peer_signature_only"] += 1
            else:
                counts["neither_signature_complete"] += 1
        by_position[position] = dict(counts)

    return by_position


def counter_overlap(source_table, peer_table, counter, per_group):
    expected = range(counter * per_group, (counter + 1) * per_group)
    source = {key: source_table[key] for key in expected if key in source_table}
    peer = {key: peer_table[key] for key in expected if key in peer_table}
    result = overlap(source, peer, locations=True)
    result["missing_on_both_ranges"] = inclusive_ranges(set(expected) - source.keys() - peer.keys())
    return result


def selected_result(selection, scheduled, peer):
    source_group, status = selection
    if source_group is None:
        return dict(counter=None, status=status, comparison=None)
    counter = source_group["counter"]
    peer_group = project_group(BytesIO(peer.archive), counter, packets=True)
    packets = counter_overlap(scheduled.packets, peer.packets, counter, 12)
    dus = counter_overlap(scheduled.dus, peer.dus, counter, 3)
    status = "no_peer_receipt"
    if counter in peer.groups:
        status = "peer_complete"
    elif packets["peer"]:
        status = "peer_partial"
    return dict(counter=counter, status=status,
                comparison=dict(packets=packets, complete_dus=dus, direct_by_position=direct_positions(source_group, peer_group),
                                verified_complete_clear_words=0))


def compare(score_path, scheduled_path, peer_path, expected_score_sha256=None):
    score_raw = score_path.read_bytes()
    score_hash = sha256(score_raw).hexdigest()
    if expected_score_sha256 is not None and expected_score_sha256 != score_hash:
        raise ValueError("score JSON differs from the supplied seal")
    score = json.loads(score_raw)
    source_raw = scheduled_path.read_bytes()
    source_hash = sha256(source_raw).hexdigest()
    if score["packet_snapshot_sha256"] != source_hash:
        raise ValueError("scheduled packet archive differs from the sealed score")
    scheduled = read_transport(source_raw)
    check_score(score, scheduled)
    primary = sealed_selection(score, "primary", scheduled)
    first_partial = sealed_selection(score, "first_partial", scheduled)
    peer = read_transport(peer_path.read_bytes())
    return dict(
        score_sha256=score_hash, scheduled_packets_sha256=source_hash, peer_packets_sha256=sha256(peer.archive).hexdigest(),
        coordinate_ranges="Inclusive. DU = 3*counter + phase. Packet = 4*DU + ordinal. Group = counter.",
        scope="Each side covers its own recording. A one-sided coordinate can be outside the other recording. "
              "Archive receipt flags identify accepted 179-byte bodies; complete 716-byte DUs also pass their wire CRC. "
              "Signatures contain the mode and 21 directly transmitted payload octets; "
              "the other 88 clear bits per received slot remain unresolved.",
        all_window=dict(packets=overlap(scheduled.packets, peer.packets, locations=True),
                        complete_dus=overlap(scheduled.dus, peer.dus, locations=True),
                        complete_groups=overlap(scheduled.groups, peer.groups, locations=True),
                        complete_signatures_by_position=signature_positions(scheduled.signatures, peer.signatures)),
        primary=selected_result(primary, scheduled, peer),
        first_partial=selected_result(first_partial, scheduled, peer),
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("score", type=Path, help="frozen scheduled score JSON")
    parser.add_argument("scheduled_packets", type=Path)
    parser.add_argument("peer_packets", type=Path)
    parser.add_argument("--score-sha256", help="also check the independently recorded score seal")
    parser.add_argument("--out", type=Path, help="write to a new JSON file (default stdout)")
    args = parser.parse_args()
    try:
        result = compare(args.score, args.scheduled_packets, args.peer_packets, args.score_sha256)
        output = json.dumps(result, indent=2) + "\n"
        if args.out is None:
            sys.stdout.write(output)
        else:
            with args.out.open("x") as stream:
                stream.write(output)
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(2, f"{parser.prog}: {error}\n")
