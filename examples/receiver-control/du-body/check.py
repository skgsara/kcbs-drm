"""Check unchanged data-unit bodies when one of four physical packet CRCs fails."""
import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from drm_row_alignment import parse_msc, valid_packets, witnessed_pairs
from salvage_msc_packets import PACKET_HEADERS, crc


def tagged(data):
    return data + crc(data).to_bytes(2, "big")


def passes(wire):
    return crc(wire[:-2]) == int.from_bytes(wire[-2:], "big")


def body(row):
    return b"".join(row[start+1:start+180] for start in range(0, 728, 182))


def assess(row):
    if len(row) != 728:
        return "other_length", None
    wires = [row[i:i+182] for i in range(0, 728, 182)]
    failed = [q for q, wire in enumerate(wires) if not passes(wire)]
    if len(failed) != 1:
        return "not_one_failed_crc", None
    q = failed[0]
    if any(w[0] != PACKET_HEADERS[i] for i, w in enumerate(wires) if i != q):
        return "noncanonical_surviving_header", None
    if not passes(body(row)):
        return "unedited_unit_crc_failed", None
    wire = wires[q]
    header_diff = wire[0] ^ PACKET_HEADERS[q]
    canonical_crc_diff = crc(bytes([PACKET_HEADERS[q]]) + wire[1:180]) ^ int.from_bytes(wire[-2:], "big")
    if not header_diff:
        kind = "fcs_only_compatible"
    elif not canonical_crc_diff:
        kind = "header_only_compatible"
    else:
        kind = "both_header_and_fcs_differ"
    return kind, dict(ordinal=q, header_differing_bits=header_diff.bit_count(),
                      fcs_differing_bits_with_canonical_header=canonical_crc_diff.bit_count())


def station(rows, other, pairs):
    outcomes, peer_scores, cases = Counter(), Counter(), []
    for i, row in enumerate(rows):
        outcome, candidate = assess(row)
        outcomes[outcome] += 1
        if candidate is None:
            continue
        j = pairs.get(i)
        received = {} if j is None else valid_packets(other[j])
        q = candidate["ordinal"]
        if q not in received:
            check = "no_peer_packet"
        elif received[q][1:180] != row[182*q+1:182*q+180]:
            check = "peer_packet_body_differs"
        else:
            check = "peer_packet_body_exact"
        peer_scores[check] += 1
        peer_unit = len(received) == 4 and passes(body(other[j]))
        cases.append(dict(native_row=i, peer_row=j, outcome=outcome, **candidate, peer_packet=check,
                          peer_whole_body_exact=body(row) == body(other[j]) if peer_unit else None,
                          unchanged_unit_sha256=sha256(body(row)).hexdigest()))
    return dict(native_rows=len(rows), three_canonical_good_and_one_crc_failed=len(cases)+outcomes["unedited_unit_crc_failed"],
                unchanged_du_crc_passed=len(cases), outcomes=dict(sorted(outcomes.items())),
                peer_packet_comparisons=dict(peer_scores), candidates=cases)


def compare(left, right):
    raw = [p.read_bytes() for p in (left, right)]
    a, b = [parse_msc(data) for data in raw]
    pairs, _ = witnessed_pairs(a, b)
    return dict(left=left.name, right=right.name, original_sha256=[sha256(data).hexdigest() for data in raw],
                witnessed_row_pairs=len(pairs), left_results=station(a, b, dict(pairs)),
                right_results=station(b, a, {j:i for i,j in pairs}))


def controls():
    source = tagged(bytes((i*37+5) % 256 for i in range(714)))
    clean = b"".join(tagged(bytes([h]) + source[179*q:179*(q+1)]) for q,h in enumerate(PACKET_HEADERS))
    accepted, rejected = Counter(), Counter()
    for i in range(728):
        for bit in range(8):
            test = bytearray(clean)
            test[i] ^= 1 << bit
            result, candidate = assess(test)
            off = i % 182
            if off == 0 or off >= 180:
                want = "header_only_compatible" if off == 0 else "fcs_only_compatible"
                if result != want or candidate["ordinal"] != i//182 or body(test) != source:
                    raise ValueError(f"incorrect envelope classification at byte {i}, bit {bit}")
                accepted[result] += 1
            else:
                if (result, candidate) != ("unedited_unit_crc_failed", None):
                    raise ValueError(f"accepted corrupted data byte {i}, bit {bit}")
                rejected[result] += 1
    # An undetected single-packet body error can coexist with a damaged wire FCS.
    test = bytearray(clean)
    for bit in (48,52,59,64):
        test[bit//8] ^= 128 >> (bit%8)
    test[181] ^= 1
    outcome, candidate = assess(test)
    if outcome != "fcs_only_compatible" or candidate is None or body(test) == source:
        raise ValueError("expected checksum-compatible wrong body")
    return dict(correct_unchanged_bodies=dict(accepted), rejected_logical_bit_errors=dict(rejected),
                crc_compatible_body_and_damaged_wire_fcs=dict(outcome=outcome, matches_sender=False))


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("msc", nargs="*", type=Path, help="optional pair of original native receiver dumps")
    args = cli.parse_args()
    if args.msc and len(args.msc) != 2:
        cli.error("supply two original MSC files or neither")
    if args.msc:
        result = compare(*args.msc)
    else:
        a = ROOT / "examples/nov28/same-6140-1232"
        b = ROOT / "examples/nov28/packet-bit-repair/peer-2126"
        result = dict(synthetic=controls(), field_1232=compare(a/"edogawa-msc.bin",a/"yokohama-msc.bin"),
                      field_2126=compare(b/"primary.msc.bin",b/"witness.msc.bin"))
    print(json.dumps(result, indent=2))
