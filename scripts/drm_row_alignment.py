"""Align native MSC rows using unique, identical physical packets from two receivers."""

from collections import Counter
from pathlib import Path
import struct

from salvage_msc_packets import PACKET_HEADERS, crc


PACKET_BYTES = 182
ROW_BYTES = PACKET_BYTES * len(PACKET_HEADERS)


def parse_msc(raw: bytes) -> list[bytes]:
    """Read little-endian length-prefixed records, preserving native row indices."""
    rows = []
    offset = 0
    while offset < len(raw):
        if len(raw) - offset < 4:
            raise ValueError(f"truncated MSC length at row {len(rows)}")
        size, = struct.unpack_from("<I", raw, offset)
        offset += 4
        if not 0 < size <= 1024 * 1024:
            raise ValueError(f"invalid MSC length {size} at row {len(rows)}")
        end = offset + size
        if end > len(raw):
            raise ValueError(f"truncated MSC payload at row {len(rows)}")
        rows.append(raw[offset:end])
        offset = end
    return rows


def read_msc(path) -> list[bytes]:
    return parse_msc(Path(path).read_bytes())


def valid_packets(row: bytes) -> dict[int, bytes]:
    """Return full wire bytes by ordinal for packets with the expected header and CRC."""
    valid = {}
    if len(row) != ROW_BYTES:
        return valid
    for ordinal, header in enumerate(PACKET_HEADERS):
        start = ordinal * PACKET_BYTES
        wire = row[start:start + PACKET_BYTES]
        if wire[0] == header and crc(wire[:-2]) == int.from_bytes(wire[-2:], "big"):
            valid[ordinal] = wire
    return valid


def _index(rows):
    by_row = []
    by_wire = {}
    unsupported = 0
    for index, row in enumerate(rows):
        packets = valid_packets(row)
        by_row.append(packets)
        unsupported += len(row) != ROW_BYTES
        for key in packets.items():
            # Retain repeats as ambiguous even if they occur more than twice.
            by_wire[key] = None if key in by_wire else index
    stats = dict(native_rows=len(by_row), unsupported_rows=unsupported,
                 valid_packets=sum(map(len, by_row)))
    return by_row, by_wire, stats


def _crossings(pairs):
    """Mark both participants of every inversion among one-to-one pairs sorted by left."""
    crossed = set()
    maximum = -1
    for pair in pairs:
        right = pair[1]
        if right < maximum:
            crossed.add(pair)
        maximum = max(right, maximum)
    minimum = float("inf")
    for pair in reversed(pairs):
        right = pair[1]
        if right > minimum:
            crossed.add(pair)
        minimum = min(right, minimum)
    return crossed


def witnessed_pairs(left_rows, right_rows):
    """Return sorted native row index pairs and JSON-serializable selection counts.

    A witness occurs just once in each dump at the same ordinal. A proposed
    row must have only one partner in either direction and agree on every other
    jointly received ordinal. Among those candidates, both sides of any order
    inversion are rejected. Gaps and unsupported row sizes never supply pairs.
    This establishes row correspondence only; it assigns no absolute counters.
    """
    left, left_wires, left_stats = _index(left_rows)
    right, right_wires, right_stats = _index(right_rows)
    common = left_wires.keys() & right_wires.keys()
    candidates = Counter()
    nonunique = 0
    for key in common:
        i, j = left_wires[key], right_wires[key]
        if i is None or j is None:
            nonunique += 1
        else:
            candidates[i, j] += 1

    left_degree = Counter(i for i, _ in candidates)
    right_degree = Counter(j for _, j in candidates)
    eligible = []
    rejected = {}
    for i, j in sorted(candidates):
        reasons = []
        if left_degree[i] != 1 or right_degree[j] != 1:
            reasons.append("ambiguous_partner")
        joint = left[i].keys() & right[j].keys()
        if any(left[i][q] != right[j][q] for q in joint):
            reasons.append("conflicting_packet")
        if reasons:
            rejected[i, j] = reasons
        else:
            eligible.append((i, j))

    crossed = _crossings(eligible)
    for pair in crossed:
        rejected[pair] = ["crossed_order"]
    pairs = [pair for pair in eligible if pair not in crossed]
    reason_counts = Counter(reason for reasons in rejected.values() for reason in reasons)
    stats = dict(left=left_stats, right=right_stats, shared_distinct_wires=len(common),
                 nonunique_shared_wires=nonunique, candidate_pairs=len(candidates),
                 accepted_pairs=len(pairs), accepted_witnesses=sum(candidates[pair] for pair in pairs),
                 rejected_pairs=len(rejected), rejection_reasons=dict(sorted(reason_counts.items())),
                 rejections=[dict(left=i, right=j, reasons=rejected[i, j]) for i, j in sorted(rejected)])
    return pairs, stats
