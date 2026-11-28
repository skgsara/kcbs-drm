"""Measure a packet's one-bit syndrome against an intact wire at a matched receiver row.

Run with two historical, length-prefixed native MSC dumps. Each row is aligned by
a unique, unchanged packet, separate from the damaged packet being tested.
Both directions are reported. The audit emits counts and hashes, never changed MSC.
"""
import argparse
from collections import Counter
from functools import cache
from hashlib import sha256
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "examples/nov28/packet-bit-repair"))
from drm_row_alignment import PACKET_BYTES, parse_msc, valid_packets, witnessed_pairs
from repair import flipped, repair_row, single_bit_positions, syndrome
from salvage_msc_packets import PACKET_HEADERS


@cache
def positions():
    return single_bit_positions()


def distance(left, right):
    return sum((a ^ b).bit_count() for a, b in zip(left, right, strict=True))


def distances(value):
    if value <= 3:
        return str(value)
    for upper in (7, 15, 31, 63, 127):
        if value <= upper:
            return f"{(upper + 1) // 2}-{upper}"
    return "128+"


def direction(source, peer, pairs):
    counts = Counter(dict.fromkeys((
        "source_crc_failed_peer_valid", "single_bit_syndrome", "proposal_header_wrong",
        "packet_only_exact", "packet_only_wrong", "strict_du_gate_exact", "strict_du_gate_wrong",
        "same_wire_both_valid", "peer_unusable_source_crc_failed",
    ), 0))
    failure_distances = Counter()
    outcome_by_distance = {}
    strict_reasons = {}
    candidates = []

    for source_index, peer_index in pairs:
        row, other = source[source_index], peer[peer_index]
        source_ok, peer_ok = valid_packets(row), valid_packets(other)
        witnesses = [q for q in source_ok.keys() & peer_ok.keys() if source_ok[q] == peer_ok[q]]
        if not witnesses:
            raise ValueError("matched row without a native wire witness")
        strict_row, strict_reason, strict_change = repair_row(row, positions())
        for q, header in enumerate(PACKET_HEADERS):
            start = q * PACKET_BYTES
            wire = row[start:start + PACKET_BYTES]
            residual = syndrome(wire)
            reference = peer_ok.get(q)
            if not residual:
                counts["same_wire_both_valid"] += q in source_ok and reference == wire
                continue
            if reference is None:
                counts["peer_unusable_source_crc_failed"] += 1
                continue
            counts["source_crc_failed_peer_valid"] += 1
            before = distance(wire, reference)
            failure_distances[distances(before)] += 1
            bit = positions().get(residual)
            if bit is None:
                if before == 1:
                    raise ValueError("one-bit peer discrepancy had no matching syndrome")
                continue
            counts["single_bit_syndrome"] += 1
            proposal = flipped(wire, bit)
            if syndrome(proposal):
                raise ValueError("proposed wire has a nonzero syndrome")
            if proposal[0] != header:
                counts["proposal_header_wrong"] += 1
                continue
            exact = proposal == reference
            if (before == 1) != exact:
                raise ValueError("one-bit result disagrees with full-wire comparison")
            label = "exact" if exact else "wrong"
            counts["packet_only_" + label] += 1
            after = distance(proposal, reference)
            movement = "closer" if after < before else "further"
            outcome_by_distance.setdefault(label, Counter())[movement] += 1
            strict_reasons.setdefault(label, Counter())[strict_reason] += 1
            strict = strict_change is not None and strict_change["packet_ordinal"] == q
            if strict:
                if strict_row[start:start + PACKET_BYTES] != proposal:
                    raise ValueError("published row repair produced a different packet")
                counts["strict_du_gate_" + label] += 1
            peer_du_checks = None
            if len(peer_ok) == len(PACKET_HEADERS):
                peer_du = b"".join(peer_ok[index][1:-2] for index in range(len(PACKET_HEADERS)))
                peer_du_checks = syndrome(peer_du) == 0
            candidates.append(dict(source_row=source_index, peer_row=peer_index, ordinal=q,
                                   source_valid_ordinals=sorted(source_ok), peer_valid_ordinals=sorted(peer_ok),
                                   peer_complete_du_crc=peer_du_checks,
                                   unchanged_witness_ordinals=sorted(witnesses), original_distance=before,
                                   proposed_distance=after, changed_wire_bit_msb0=bit,
                                   published_row_gate=strict_reason, exact_peer_match=exact,
                                   source_wire_sha256=sha256(wire).hexdigest(),
                                   proposed_wire_sha256=sha256(proposal).hexdigest(),
                                   peer_wire_sha256=sha256(reference).hexdigest()))
    return dict(counts=dict(counts), distance_of_bad_wire_to_peer=dict(sorted(failure_distances.items())),
                distance_change=outcome_by_distance, published_row_rule_by_packet_result=strict_reasons,
                candidate_wires=candidates)


def compare(left, right):
    left_raw = left.read_bytes()
    right_raw = right.read_bytes()
    first, second = parse_msc(left_raw), parse_msc(right_raw)
    pairs, alignment = witnessed_pairs(first, second)
    # Keep the cohort summary small even if duplicated epochs cause many rejections.
    alignment.pop("rejections")
    return dict(left_sha256=sha256(left_raw).hexdigest(), right_sha256=sha256(right_raw).hexdigest(),
                alignment=alignment, left_as_source=direction(first, second, pairs),
                right_as_source=direction(second, first, [(j, i) for i, j in pairs]))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("left", type=Path, help="first original length-prefixed native MSC file")
    parser.add_argument("right", type=Path, help="independent paired native MSC file")
    args = parser.parse_args()
    print(json.dumps(compare(args.left, args.right), indent=2))
