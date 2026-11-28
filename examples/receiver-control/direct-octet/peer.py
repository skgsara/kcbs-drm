"""Evaluate the three-slot p5 rule on two archived, independently received packet pairs."""
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
DUAL = ROOT / "examples/nov28/group-boundary"
PAIR = ROOT / "examples/nov28/same-6140-1232"
MEMBER = ROOT / "examples/nov28/member-3205-20min"
sys.path[:0] = [str(ROOT / "scripts"), str(DUAL)]
from check_dual_rf import packets
from received_evs_packets import PACKET_BYTES, read_packet_snapshot
from render_continuous import MODE_POSITIONS, PACKET_STARTS

PINS = {
    DUAL / "dual-3205.npz": "7824c1146312aef97628da57d97e947036ce3b5312691c5376bbcff7e223293f",
    DUAL / "dual-6140.npz": "05a4cc876e3f20c89d01e80eaa3fd3e4fb027f3d5ff920db34e1a9c6d008a90c",
    PAIR / "yokohama-packets.npz": "ee0eb383de5fcf07121583752894e6226dba58dd5340bd37de983827fa7c39fd",
    PAIR / "edogawa-packets.npz": "8eb521c769f27344fb0b5b813de2d298e1b53ef03588a41540602daf775ff9be",
}


def load(path):
    if sha256(path.read_bytes()).hexdigest() != PINS[path]:
        raise ValueError(f"published packet digest changed for {path.name}")
    if path.parent == DUAL:
        prior = json.loads((MEMBER / "cross-frequency.json").read_bytes())
        ids = set(prior["historical_exposure"]["member_historical_counter_ids"])
        units = (MEMBER / "member-dus.npz" if path.name == "dual-3205.npz" else
                 ROOT / prior["sources"]["edogawa_6140_du_archive"])
        wire, _ = packets(path, units, ids, None, None)
        return {coord: body for coord, (body, _) in wire.items()}
    ticks, units, flags = read_packet_snapshot(path)
    result = {}
    for tick, unit, present in zip(ticks, units, flags, strict=True):
        for q, body in enumerate(unit.reshape(4, PACKET_BYTES)):
            if present[q]:
                result[int(tick), q] = body.tobytes()
    return result


def byte_at(table, counter, slot, addresses, displacement=0):
    phase, within = divmod(slot, 20)
    q, index = divmod(int(addresses[within]) + displacement, PACKET_BYTES)
    body = table.get((counter * 3 + phase, q))
    return None if body is None else body[index]


def forecast(table):
    counters = sorted({tick // 3 for tick, _ in table})
    decisions = []
    groups = 0
    for c in counters:
        if not all((3 * c + phase, q) in table for phase in range(3) for q in range(4)):
            continue
        groups += 1
        for slot in range(1, 59, 3):
            modes = [byte_at(table, c, i, MODE_POSITIONS) for i in (slot - 1, slot, slot + 1)]
            if len(set(modes)) != 1:
                decisions.append((c, slot, "modes_differ", None))
                continue
            left = byte_at(table, c, slot - 1, PACKET_STARTS, 5)
            right = byte_at(table, c, slot + 1, PACKET_STARTS, 5)
            if left == right:
                decisions.append((c, slot, "consensus", left))
            else:
                decisions.append((c, slot, "neighbors_differ", None))
    return groups, decisions


COUNT_NAMES = ("selected_centers", "modes_differ", "neighbors_differ", "consensus",
               "peer_p5_present", "peer_p5_missing", "consensus_peer_missing", "scored", "exact",
               "wrong", "zero_baseline_exact_on_scored", "nonzero_predictions_scored", "nonzero_exact")


def score(decisions, peer):
    rows = [Counter(dict.fromkeys(COUNT_NAMES, 0)) for _ in range(4)]
    for c, slot, reason, predicted in decisions:
        row = rows[slot % 4]
        row["selected_centers"] += 1
        row[reason] += 1
        observed = byte_at(peer, c, slot, PACKET_STARTS, 5)
        row["peer_p5_missing" if observed is None else "peer_p5_present"] += 1
        if predicted is None:
            continue
        if observed is None:
            row["consensus_peer_missing"] += 1
            continue
        row["scored"] += 1
        row["exact" if observed == predicted else "wrong"] += 1
        row["zero_baseline_exact_on_scored"] += observed == 0
        row["nonzero_predictions_scored"] += predicted != 0
        row["nonzero_exact"] += observed == predicted != 0
    return {str(i): row for i, row in enumerate(rows, 1)}, {k: sum(r[k] for r in rows) for k in COUNT_NAMES}


def case(source_path, peer_path):
    source = load(source_path)
    groups, decisions = forecast(source)
    sealed = sha256(json.dumps(decisions, separators=(",", ":")).encode("ascii")).hexdigest()
    positions, counts = score(decisions, load(peer_path))
    return dict(source=str(source_path.relative_to(ROOT)), source_sha256=PINS[source_path],
                peer=str(peer_path.relative_to(ROOT)), peer_sha256=PINS[peer_path],
                source_assigned_counters=len({t // 3 for t, _ in source}), source_complete_groups=groups,
                source_centers_with_naturally_missing_p5=0, decisions_sha256=sealed,
                counts=counts, by_position=positions)


if __name__ == "__main__":
    result = dict(schema="historical-independent-peer-p5-v1",
                  target="Zero-based payload octet 5, excluding the mode. Center slots 1,4,...,58.",
                  selection="All source groups with three complete CRC-validated DUs in each named archive. "
                            "The dual-frequency wire archives were previously restricted to 119 mutually assigned "
                            "counters. The 12:32 source selection uses its own archive without peer selection.",
                  evidence="The predictor can read the three modes and the two neighbor payload bytes. All center "
                           "payloads are withheld from forecasting. The peer supplies the score when its target "
                           "packet arrived, regardless of its other packets or mode. Each center was physically "
                           "received on the source. These are retrospective byte-withholding controls.",
                  decision_digest="SHA-256 of ASCII compact JSON arrays [counter,slot,reason,prediction-or-null] "
                                  "in group/slot order, without a final newline.",
                  member_3205_to_edogawa_6140=case(DUAL / "dual-3205.npz", DUAL / "dual-6140.npz"),
                  yokohama_to_edogawa_1232=case(PAIR / "yokohama-packets.npz", PAIR / "edogawa-packets.npz"))
    print(json.dumps(result, indent=2))
