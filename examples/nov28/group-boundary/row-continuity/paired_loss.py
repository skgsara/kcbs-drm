"""Check which received group contains each phase after deliberately omitting three native callbacks."""
from hashlib import sha256
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[4]
PAIR = ROOT / "examples/nov28/same-6140-1232"
sys.path[:0] = [str(ROOT / "scripts"), str(PAIR)]
from drm_row_alignment import parse_msc, valid_packets
from locate_evs_slots import unit_locations
from native_groups import native_groups

PRIMARY = 43945659


def load_reception(site):
    raw = (PAIR / f"{site}-msc.bin").read_bytes()
    receipt = json.loads((PAIR / f"{site}-native.json").read_bytes())
    if sha256(raw).hexdigest() != receipt["msc_sha256"]:
        raise ValueError(f"MSC differs from the published {site} receipt")
    _, groups, _, units = native_groups(raw)
    start, = (g["phase0_row"] for g in groups if g["counter"] == PRIMARY)
    return receipt["msc_sha256"], parse_msc(raw), start, units[PRIMARY]


def following_counter(row):
    packets = valid_packets(row)
    if 0 not in packets or 3 not in packets or packets[0][2] >> 4 != 0:
        raise ValueError("control lacks an intact phase-zero counter")
    return int.from_bytes(packets[3][128:132], "big")


def trial(rows, peer_units):
    # The unmodified parser sees exactly the original native headers, CRCs and row ordering that remain.
    raw = b"".join(len(row).to_bytes(4, "little") + row for row in rows[:3])
    checks, occurrences, _, units = native_groups(raw)
    if len(occurrences) != 1 or occurrences[0]["counter"] != PRIMARY:
        raise ValueError("the three-row parser did not return the original primary counter")
    following = following_counter(rows[3])
    equal_slots = []
    for phase, (candidate, reference) in enumerate(zip(units[PRIMARY], peer_units, strict=True)):
        observed = dict(unit_locations(PRIMARY, phase, candidate))
        peer = dict(unit_locations(PRIMARY, phase, reference))
        equal_slots.append(sum(octets == peer[coordinate] for coordinate, octets in observed.items()))
    return dict(phase_zero_counter=PRIMARY, following_counter=following,
                next_counter_is_successor=following == (PRIMARY + 1) % (1 << 32),
                wire_packets_passing_crc_and_header=checks["physical_packets_crc_and_header"],
                data_units_passing_crc=checks["native_complete_dus"],
                slots_matching_peer_on_22_direct_octets_by_phase=equal_slots,
                slots_matching_peer=sum(equal_slots))


def evaluate():
    source_hash, source, start, _ = load_reception("yokohama")
    peer_hash, peer, peer_start, peer_units = load_reception("edogawa")
    if following_counter(peer[peer_start + 3]) != PRIMARY + 1:
        raise ValueError("independent receiver lacks the immediate successor counter")
    original = source[start:start + 7]
    if following_counter(original[6]) != PRIMARY + 2:
        raise ValueError("expected both following group counters in the original source")
    cases = dict(original=trial(original, peer_units))
    for first in (1, 2, 3):
        remaining = original[:first] + original[first + 3:]
        cases[f"omit_after_phase_{first - 1}"] = dict(
            removed_native_rows=list(range(start + first, start + first + 3)), **trial(remaining, peer_units))
    return dict(yokohama_msc_sha256=source_hash, edogawa_msc_sha256=peer_hash,
                yokohama_phase0_row=start, edogawa_phase0_row=peer_start,
                edogawa_following_counter=following_counter(peer[peer_start + 3]), cases=cases)


if __name__ == "__main__":
    print(json.dumps(evaluate(), indent=2))
