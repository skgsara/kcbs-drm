"""Screen a public EVS group projection for a necessary condition of the TCX20 zero-pair branch."""
import argparse
import json
from pathlib import Path
import sys


# Full-word coordinates, MSB first. The last four bits of octet 20 are outside the filler.
TEST_OCTETS = ((17, 8), (18, 8), (20, 4))
OUTCOMES = ("incompatible", "compatible_only", "inconclusive", "abstain")


def read_octet(token):
    if token in ("??", "--"):
        return None
    if len(token) != 2 or any(c not in "0123456789abcdefABCDEF" for c in token):
        raise ValueError(f"invalid projected octet: {token!r}")
    return int(token, 16)


def screen_slot(row):
    coords = {k: row[k] for k in ("counter", "slot", "phase", "cycle", "position")}
    result = dict(coords, outcome="abstain", observed_test_bits=0, one_bits=[])
    if row.get("receipt") == "missing_du":
        return dict(result, reason="missing_du")
    if row.get("receipt") != "received_du":
        raise ValueError(f"invalid receipt in slot {row['slot']}")
    octets = row.get("octets")
    if not isinstance(octets, str) or len(tokens := octets.split()) != 33:
        raise ValueError(f"expected 33 word octets in slot {row['slot']}")
    mode = read_octet(tokens[0])
    if mode is None:
        return dict(result, reason="missing_mode")
    if mode >> 3 < 29 or not mode & 0x04:
        return dict(result, reason="not_ordinary_tcx20")

    for offset, width in TEST_OCTETS:
        octet = read_octet(tokens[offset])
        if octet is not None:
            result["observed_test_bits"] += width
            result["one_bits"].extend(8*offset + bit for bit in range(width)
                                      if octet & (0x80 >> bit))
    if result["one_bits"]:
        return dict(result, outcome="incompatible", reason="one_in_required_zero_bits")
    if result["observed_test_bits"] == 20:
        return dict(result, outcome="compatible_only", reason="all_20_bits_zero")
    return dict(result, outcome="inconclusive", reason="missing_test_bits")


def screen(projection):
    """Return the outcome per slot and counts for each of the four frame positions."""
    if not isinstance(projection, dict) or projection.get("format") != "kcbs-evs-projection-v1":
        raise ValueError("expected kcbs-evs-projection-v1 JSON from project_evs_group.py")
    counter = projection.get("counter")
    if type(counter) is not int or not 0 <= counter <= 0xffffffff:
        raise ValueError("expected an unsigned 32-bit group counter")
    slots = projection.get("slots")
    if not isinstance(slots, list) or len(slots) != 60:
        raise ValueError("expected all 60 group slots, including any missing DUs")
    counts = dict.fromkeys(OUTCOMES, 0)
    by_position = {str(pos): counts.copy() for pos in range(1, 5)}
    results = []
    for slot, row in enumerate(slots):
        phase, index = divmod(slot, 20)
        cycle, role = divmod(index, 4)
        expected = dict(counter=counter, slot=slot, phase=phase, cycle=cycle, position=role+1)
        if not isinstance(row, dict) or any(type(row.get(k)) is not int or row[k] != v
                                             for k, v in expected.items()):
            raise ValueError(f"invalid projected coordinates for slot {slot}")
        result = screen_slot(row)
        counts[result["outcome"]] += 1
        by_position[str(role+1)][result["outcome"]] += 1
        results.append(result)
    return dict(counter=counter, scope="A TCX20 branch certified by bit 128 would require zeros at "
                "word bits [136,152) and [160,164). Compatibility leaves the branch unverified.",
                counts=counts, by_position=by_position, slots=results)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("projection", help="project_evs_group.py JSON file, or - for stdin")
    args = parser.parse_args()
    try:
        source = sys.stdin.read() if args.projection == "-" else Path(args.projection).read_text(encoding="utf-8")
        print(json.dumps(screen(json.loads(source)), indent=2))
    except (OSError, ValueError) as error:
        parser.exit(2, f"{parser.prog}: {error}\n")
