"""Exercise two-branch inference against predetermined physical errors and an original sender row."""
import json
from pathlib import Path
import struct
import sys
from tempfile import TemporaryDirectory

from solve import PACKET_BYTES, ROOT, digest, flip, propose, score, sealed

sys.path.insert(0, str(ROOT / "examples/nov28/packet-bit-repair"))
from controls import checks, corrupt, sender_row


def framed(row):
    return struct.pack("<I", len(row)) + row


def run():
    original = sender_row()
    target = 1
    wire = original[target * PACKET_BYTES:(target + 1) * PACKET_BYTES]
    # In physical MSB-first order these four positions are one CRC polynomial apart.
    shared_collision = [300, 304, 311, 316]
    cases = [
        ("complementary", [100], [200], False, "exact"),
        ("shared_undetectable_error", [100, *shared_collision], [200, *shared_collision], False, "different"),
        ("shared_single_error", [100, 300], [200, 300], False, "inconsistent"),
        ("dependent_disagreements", [300], [304, 311, 316], False, "multiple_solutions"),
        ("disagreement_limit", [100], list(range(201, 213)), False, "more_than_limit"),
        ("unavailable_sibling", [100], [200], True, "missing_original_sibling"),
        ("common_failed_packet", [100], [100], False, "identical_crc_failed"),
        ("bad_header", [0, 100], [200], False, "wrong_header"),
    ]
    details = []
    with TemporaryDirectory() as directory:
        tmp = Path(directory)
        peer = tmp / "sender.msc"
        peer.write_bytes(framed(original))
        decisions = tmp / "proposals.json"
        for name, left_bits, right_bits, missing_sibling, expected in cases:
            left = corrupt(original, target, left_bits)
            right = corrupt(original, target, right_bits)
            if missing_sibling:
                left = corrupt(left, 2, [120])
                right = corrupt(right, 2, [120])
            raw_a, raw_b = framed(left), framed(right)
            proposed = propose(raw_a, raw_b)
            saved = (json.dumps(proposed, indent=2) + "\n").encode()
            decisions.write_bytes(saved)
            seal = digest(saved)
            scored = score(raw_a, raw_b, decisions, seal, peer)
            observations = dict(name=name, primary_target_flips=left_bits, alternate_target_flips=right_bits,
                                shared_sibling_error=missing_sibling, proposals=proposed["proposed_packets"])
            if expected in ("exact", "different"):
                if scored["outcomes"][expected] != 1 or proposed["proposed_packets"] != 1:
                    raise ValueError(f"{name}: sender comparison failed")
                proposal = proposed["proposals"][0]
                corrected = corrupt(left, target, proposal["primary_flips_msb0"])
                corrected_wire = corrected[target * PACKET_BYTES:(target + 1) * PACKET_BYTES]
                expected_wire = flip(wire, shared_collision) if expected == "different" else wire
                if corrected_wire != expected_wire or checks(corrected) != checks(original):
                    raise ValueError(f"{name}: reconstructed bytes or checks differ")
                observations.update(proposed_checks=checks(corrected), sender_comparison=expected,
                                    proposed_wire_sha256=digest(corrected_wire),
                                    remaining_wrong_wire_bits=sum((a ^ b).bit_count()
                                                                  for a, b in zip(wire, corrected_wire)))
            else:
                if proposed["proposed_packets"] or proposed["counts"].get(expected) != 1:
                    raise ValueError(f"{name}: expected abstention {expected}")
                observations["abstention"] = expected
            details.append(observations)
        try:
            sealed(raw_a, raw_b, decisions, "0" * 64)
        except ValueError as error:
            if str(error) != "wrong decision seal":
                raise
        else:
            raise ValueError("altered seal accepted")
    return dict(synthetic_original_row_sha256=digest(original), synthetic_target_ordinal=target,
                synthetic_original_wire_sha256=digest(wire), invalid_decision_seal_rejected=True,
                cases=details)


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
