"""Score directly carried EVS octets in two CRC-failing hard decisions against a separate RF receiver."""
import argparse
from collections import Counter
from hashlib import sha256
from itertools import groupby
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from drm_row_alignment import parse_msc, valid_packets, witnessed_pairs
from render_continuous import MODE_POSITIONS, PACKET_STARTS
from salvage_msc_packets import PACKET_HEADERS
from tail_fill_audit import crc

PAIR = ROOT / "examples/nov28/same-6140-1232"
BRANCH = ROOT / "examples/nov28/clear-evs-controls/transport-mlc4"
METHODS = ("one_iteration", "four_iterations", "equal_octet", "equal_run_8", "equal_run_8_mode",
           "equal_run_8_payload", "different_one_iteration", "different_four_iterations")
FIELDS = [[] for _ in range(4)]
for slot, (mode, payload) in enumerate(zip(MODE_POSITIONS, PACKET_STARTS, strict=True)):
    for field, addr in [("mode", mode), *(("payload", payload + p) for p in range(32) if p % 3 != 0)]:
        q, within = divmod(int(addr), 179)
        FIELDS[q].append((within + 1, field))  # index in 182-byte wire, after header
for entries in FIELDS:
    entries.sort()
if len({(q, idx) for q, fields in enumerate(FIELDS) for idx, _ in fields}) != 440:
    raise ValueError("the 20-slot directly readable geometry must have 440 distinct addresses")


def read(path):
    raw = path.read_bytes()
    return parse_msc(raw), sha256(raw).hexdigest()


def wire_at(row, q):
    return row[q * 182:(q + 1) * 182]


def crc_pass(wire):
    return crc(wire[:-2]) == int.from_bytes(wire[-2:], "big")


def forecasts(first, fourth):
    pairs, _ = witnessed_pairs(first, fourth)
    predicted = []
    for i, j in pairs:
        for q, fields in enumerate(FIELDS):
            w1, w4 = wire_at(first[i], q), wire_at(fourth[j], q)
            if crc_pass(w1) or crc_pass(w4):
                continue
            # CRCs qualify a packet; only the 22 direct application octets per EVS word
            # participate in agreements. Runs continue across uninspected masked bytes.
            cells = [(idx, kind, w1[idx], w4[idx]) for idx, kind in fields]
            decisions = []
            for equal, group in groupby(cells, key=lambda cell: cell[2] == cell[3]):
                run = list(group)
                for idx, kind, v1, v4 in run:
                    decisions.append((idx, kind, v1, v4, len(run) if equal else 0))
            headers_ok = w1[0] == w4[0] == PACKET_HEADERS[q]
            predicted.append((i, j, q, headers_ok, decisions))
    return pairs, predicted


def empty_counts():
    return {k: 0 for k in ("octets", "exact_octets", "correct_bits", "packets_with_predictions",
                            "packets_all_predicted_octets_exact")}


def evaluate(items, peer_matches, peer_good):
    summary = Counter(dict.fromkeys(("both_crc_failed", "both_canonical_headers", "with_peer_row",
                                     "peer_target_crc_good", "peer_target_missing", "direct_octets_total",
                                     "direct_octets_with_peer", "direct_octets_missing_peer", "run8_octets_total",
                                     "run8_octets_missing_peer"), 0))
    methods = {k: empty_counts() for k in METHODS}
    bit_totals = Counter(dict.fromkeys(("issued_equal_bits", "correct_equal_bits"), 0))
    cases = []
    for i, j, q, headers_ok, decisions in items:
        k = peer_matches.get(i)
        label = None if k is None else peer_good[k].get(q)
        summary["both_crc_failed"] += 1
        summary["both_canonical_headers"] += headers_ok
        summary["with_peer_row"] += k is not None
        summary["direct_octets_total"] += len(decisions)
        summary["run8_octets_total"] += sum(run >= 8 for _, _, _, _, run in decisions)
        if label is None:
            summary["peer_target_missing"] += 1
            summary["direct_octets_missing_peer"] += len(decisions)
            summary["run8_octets_missing_peer"] += sum(run >= 8 for _, _, _, _, run in decisions)
            continue
        summary["peer_target_crc_good"] += 1
        summary["direct_octets_with_peer"] += len(decisions)
        local = {name: [] for name in methods}
        for idx, kind, v1, v4, run in decisions:
            y = label[idx]
            common = 255 ^ (v1 ^ v4)
            bit_totals["issued_equal_bits"] += common.bit_count()
            bit_totals["correct_equal_bits"] += (common & (255 ^ (v1 ^ y))).bit_count()
            local["one_iteration"].append((v1, y))
            local["four_iterations"].append((v4, y))
            if run:
                local["equal_octet"].append((v1, y))
                if run >= 8:
                    local["equal_run_8"].append((v1, y))
                    local["equal_run_8_" + kind].append((v1, y))
            else:
                local["different_one_iteration"].append((v1, y))
                local["different_four_iterations"].append((v4, y))
        for name, values in local.items():
            totals = methods[name]
            exact = sum(v == y for v, y in values)
            totals["octets"] += len(values)
            totals["exact_octets"] += exact
            totals["correct_bits"] += sum(8 - (v ^ y).bit_count() for v, y in values)
            if values:
                totals["packets_with_predictions"] += 1
                totals["packets_all_predicted_octets_exact"] += exact == len(values)
        primary = local["equal_run_8"]
        cases.append(dict(first_row=i, fourth_row=j, peer_row=k, ordinal=q, both_headers_canonical=headers_ok,
                          scored_direct_octets=len(decisions), run_8_octets=len(primary),
                          run_8_exact=sum(v == y for v, y in primary)))
    return dict(availability=summary, equal_bits=bit_totals, estimates=methods, labelled_packets=cases)


def run(one_path, four_path, peer_path):
    a, ha = read(one_path)
    b, hb = read(four_path)
    pairs, issued = forecasts(a, b)
    ledger_hash = sha256(json.dumps(issued, separators=(",", ":")).encode("ascii")).hexdigest()
    other, hp = read(peer_path)
    peer_pairs, _ = witnessed_pairs(a, other)
    peer_map = dict(peer_pairs)
    good = [valid_packets(row) for row in other]
    splits = {"all": issued, "calibration_rows_0_71": [r for r in issued if r[0] < 72],
              "guard_rows_72_83": [r for r in issued if 72 <= r[0] < 84],
              "evaluation_rows_84_end": [r for r in issued if r[0] >= 84]}
    groups = {name: evaluate(rows, peer_map, good) for name, rows in splits.items()}
    return dict(schema="two-failing-branches-direct-EVS-v1",
                inputs={k: dict(filename=p.name, sha256=h) for k, p, h in
                        (("one_iteration", one_path, ha), ("four_iterations", four_path, hb), ("peer", peer_path, hp))},
                source_native_row_counts=[len(a), len(b)], peer_native_rows=len(other),
                witnessed_branch_row_pairs=len(pairs), witnessed_first_to_peer_row_pairs=len(peer_pairs),
                source_ledger_sha256=ledger_hash,
                scope="Retrospective 12:32 row split. Both target CRCs must fail; a distinct, unique "
                      "CRC-valid wire supplies each row correspondence. The peer's target must pass CRC and header. "
                      "Only mode and p1,p2,p4,p5,...,p31 are scored. The two branches share their original IQ.",
                primary="Emit equal octets in a run of at least eight equal directly readable EVS octets, in "
                        "ascending wire address within one packet, skipping other bytes. Modes and payload use "
                        "the same rule. No reference bytes participate in constructing runs.",
                groups=groups)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--one", type=Path, default=PAIR / "edogawa-msc.bin")
    parser.add_argument("--four", type=Path, default=BRANCH / "edogawa-mlc4-msc.bin")
    parser.add_argument("--peer", type=Path, default=PAIR / "yokohama-msc.bin")
    args = parser.parse_args()
    print(json.dumps(run(args.one, args.four, args.peer), indent=2))
