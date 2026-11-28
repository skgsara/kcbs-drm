"""Propose a DRM packet when two failed hard decodes disagree on at most 12 bits."""
import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))
from drm_row_alignment import PACKET_BYTES, PACKET_HEADERS, parse_msc, valid_packets, witnessed_pairs
from salvage_msc_packets import crc

LIMIT = 12


def digest(data):
    return sha256(data).hexdigest()


def syndrome(wire):
    return crc(wire[:-2]) ^ int.from_bytes(wire[-2:], "big")


def flip(data, indices):
    altered = bytearray(data)
    for index in indices:
        altered[index // 8] ^= 128 >> (index % 8)
    return bytes(altered)


def solve(columns, residual):
    """Represent the 16-bit residual as a combination of columns, retaining witnesses."""
    pivots = {}
    for i, column in enumerate(columns):
        subset = 1 << i
        while column:
            leading = column.bit_length() - 1
            if leading not in pivots:
                pivots[leading] = (column, subset)
                break
            vector, mask = pivots[leading]
            column ^= vector
            subset ^= mask
    solution = 0
    while residual:
        leading = residual.bit_length() - 1
        if leading not in pivots:
            return None, len(pivots)
        column, subset = pivots[leading]
        residual ^= column
        solution ^= subset
    return solution, len(pivots)


def physical_columns():
    zero = bytes(PACKET_BYTES)
    original = syndrome(zero)
    return [syndrome(flip(zero, [i])) ^ original for i in range(PACKET_BYTES * 8)]


def one_packet(x, y, ordinal, effects):
    if x[0] != PACKET_HEADERS[ordinal] or y[0] != PACKET_HEADERS[ordinal]:
        return "wrong_header", None
    disagreements = [8 * i + j for i, (a, b) in enumerate(zip(x, y, strict=True)) if a != b
                     for j in range(8) if (a ^ b) & (128 >> j)]
    if not disagreements:
        return "identical_crc_failed", None
    if len(disagreements) > LIMIT:
        return "more_than_limit", None
    solution, rank = solve([effects[i] for i in disagreements], syndrome(x))
    if solution is None:
        return "inconsistent", None
    if rank < len(disagreements):
        return "multiple_solutions", None
    flips = [bit for j, bit in enumerate(disagreements) if solution & (1 << j)]
    wire = flip(x, flips)
    if syndrome(wire):
        raise ValueError("GF(2) solver returned a nonzero packet syndrome")
    return "unique_packet", (wire, dict(differing_bits=len(disagreements), rank=rank,
                                         disagreements_msb0=disagreements, primary_flips_msb0=flips))


def propose(raw_a, raw_b):
    left, right = parse_msc(raw_a), parse_msc(raw_b)
    pairs, selection = witnessed_pairs(left, right)
    effects = physical_columns()
    counts = Counter()
    proposals = []
    for i, j in pairs:
        good_a, good_b = valid_packets(left[i]), valid_packets(right[j])
        for q in range(4):
            if q in good_a or q in good_b:
                continue
            counts["both_rejected"] += 1
            region = slice(q * PACKET_BYTES, (q + 1) * PACKET_BYTES)
            x, y = left[i][region], right[j][region]
            reason, candidate = one_packet(x, y, q, effects)
            counts[reason] += 1
            if candidate is None:
                continue
            wire, solution = candidate
            others = {k: good_a[k] if k in good_a else good_b[k] for k in good_a.keys() | good_b.keys()}
            if len(others) != 3:
                counts["missing_original_sibling"] += 1
                continue
            siblings = {str(k): "primary" if k in good_a else "alternate" for k in sorted(others)}
            others[q] = wire
            du = b"".join(others[k][1:-2] for k in range(4))
            if syndrome(du):
                counts["du_crc_reject"] += 1
                continue
            proposals.append(dict(primary_row=i, alternate_row=j, ordinal=q, **solution,
                                  original_primary_sha256=digest(x), original_alternate_sha256=digest(y),
                                  proposed_wire_sha256=digest(wire), sibling_sources=siblings,
                                  proposed_du_sha256=digest(du), transmitted_du_crc=du[-2:].hex(),
                                  primary_payload_octets_changed=sum(a != b for a, b in zip(x[1:-2], wire[1:-2]))))
    return dict(format="two-branch-physical-packet-proposals-v1", primary_msc_sha256=digest(raw_a),
                alternate_msc_sha256=digest(raw_b), max_disagreements=LIMIT, native_rows=[len(left), len(right)],
                aligned_rows=len(pairs), rejected_alignment_rows=selection["rejected_pairs"],
                counts=dict(sorted(counts.items())), proposed_packets=len(proposals), proposals=proposals,
                scope="Proposals assume every bit where both hard decodes agree is correct. Packet and DU CRCs "
                      "share a polynomial. Only a separate observation can test common errors.")


def sealed(raw_a, raw_b, saved_path, seal):
    raw = saved_path.read_bytes()
    if digest(raw) != seal.lower():
        raise ValueError("wrong decision seal")
    forecast = json.loads(raw)
    if forecast != propose(raw_a, raw_b):
        raise ValueError("sealed decisions differ from original inputs and fixed solver")
    return forecast


def score(raw_a, raw_b, saved_path, seal, peer, origin="unspecified"):
    forecast = sealed(raw_a, raw_b, saved_path, seal)
    observed = peer.read_bytes()
    if origin == "independent-station" and digest(observed) in (digest(raw_a), digest(raw_b)):
        raise ValueError("an identical source file cannot serve as an independent station")
    peer_rows = parse_msc(observed)
    rows = parse_msc(raw_a)
    mapping = dict(witnessed_pairs(rows, peer_rows)[0])
    results = []
    for p in forecast["proposals"]:
        i, q = p["primary_row"], p["ordinal"]
        j = mapping.get(i)
        wire = valid_packets(peer_rows[j]).get(q) if j is not None else None
        if wire is None:
            outcome = "unavailable"
        else:
            outcome = "exact" if digest(wire) == p["proposed_wire_sha256"] else "different"
        results.append(dict(primary_row=i, peer_row=j, ordinal=q, outcome=outcome,
                            peer_wire_sha256=digest(wire) if wire is not None else None))
    return dict(format="two-branch-physical-packet-score-v1", decision_sha256=seal.lower(),
                peer_msc_sha256=digest(observed), declared_witness_origin=origin, proposals=len(results),
                outcomes={s: sum(r["outcome"] == s for r in results) for s in ("exact", "different", "unavailable")},
                comparisons=results)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="stage", required=True)
    generate = commands.add_parser("propose", help="emit sealable proposals without a reference")
    check = commands.add_parser("score", help="compare externally sealed decisions with CRC-accepted witness packets")
    for sub in (generate, check):
        sub.add_argument("primary", type=Path)
        sub.add_argument("alternate", type=Path)
    check.add_argument("decisions", type=Path)
    check.add_argument("--seal", required=True)
    check.add_argument("--peer", type=Path, required=True)
    check.add_argument("--witness-origin", choices=("independent-station", "same-iq", "unspecified"),
                       default="unspecified", help="declared acquisition relationship; hashes alone cannot establish it")
    args = parser.parse_args()
    a, b = args.primary.read_bytes(), args.alternate.read_bytes()
    if args.stage == "propose":
        result = propose(a, b)
    else:
        result = score(a, b, args.decisions, args.seal, args.peer, args.witness_origin)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
