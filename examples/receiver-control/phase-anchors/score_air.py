"""Score single-receiver phase placements and project the prospectively selected groups."""
import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
NOV = HERE.parents[1] / "nov28"
sys.path.insert(0, str(NOV / "packet-bit-repair"))
from score_field import prior_ids
from evs_evidence import bit_evidence, field_sections
from native_groups import native_groups
from project_evs_group import project_group
from received_evs_packets import read_packet_snapshot
from phase_anchors import is_anchor, read_assignments


def inventory(path):
    ticks, _, flags = read_packet_snapshot(path)
    accepted = {(int(t), q) for t, row in zip(ticks, flags, strict=True) for q, good in enumerate(row) if good}
    full = {int(t) for t, row in zip(ticks, flags, strict=True) if row.all()}
    groups = {t // 3 for t in full if t % 3 == 0 and t + 1 in full and t + 2 in full}
    ids = {t // 3 for t, _ in accepted}
    return accepted, full, groups, ids


def selected_projection(path, counter, *, evidence_version=1):
    if counter is None:
        return None
    projection = project_group(path, counter, packets=True)
    projection.update(field_sections(projection["slots"]))
    positions = {str(p): Counter(dict(complete=0, partial=0, absent=0)) for p in range(1, 5)}
    for slot in projection["slots"]:
        n = sum(octet != "--" for octet in slot["octets"].split())
        positions[str(slot["position"])]["complete" if n == 33 else "absent" if n == 0 else "partial"] += 1
    return dict(physical_slots_by_position=positions, projection=projection,
                bit_evidence=bit_evidence(projection, version=evidence_version))


def seal(msc, directory):
    rows, _, extra = read_assignments(msc)
    paths = [directory / arm / "packets.npz" for arm in ("stock", "extended")]
    before, after = (inventory(p) for p in paths)
    for old, new in zip(before, after, strict=True):
        if not old <= new:
            raise ValueError("the field overlay lost a previously received coordinate")
    added_packets = after[0] - before[0]
    partial = None
    anchors = [i for i, row in enumerate(rows) if is_anchor(row)]
    placements = []
    for row, (c, p) in sorted(extra.items()):
        received = [q for q, ok in enumerate(rows[row]["packet_ok"]) if ok]
        added = [q for q in received if (3 * c + p, q) in added_packets]
        left = max(i for i in anchors if i < row)
        right = min(i for i in anchors if i > row)
        placements.append(dict(native_row=row, counter=c, phase=p, received_ordinals=received,
                               gained_ordinals=added, endpoint_rows=[left, right],
                               endpoint_counters=[rows[left]["counter"], rows[right]["counter"]]))
        if partial is None and c not in after[2] and added:
            partial = dict(native_row=row, counter=c, phase=p)
    raw = msc.read_bytes()
    stats, native, _, _ = native_groups(raw)
    primary = native[0] if native else None
    if primary and primary["counter"] not in before[2]:
        raise ValueError("native primary missing from baseline packet groups")
    arm_counts = []
    for path, (packets, full, groups, ids) in zip(paths, (before, after), strict=True):
        totals = Counter()
        for c in sorted(ids):
            proj = project_group(path, c, packets=True)
            totals.update(dict(complete_wire_slots=proj["physically_complete_slots"],
                               directly_observed_bits=proj["confirmed_direct_bits"], full_clear_words=proj["full_clear_words"]))
        arm_counts.append(dict(packet_coordinates=len(packets), complete_dus=len(full), complete_groups=len(groups),
                               assigned_counters=sorted(ids), **totals))
    return dict(native_msc_sha256=sha256(raw).hexdigest(), native=stats, pristine_native_groups=len(native),
                archive_sha256={p.parent.name: sha256(p.read_bytes()).hexdigest() for p in paths},
                stock=arm_counts[0], extended=arm_counts[1], placements=placements,
                new_packet_coordinates=[list(divmod(t, 3)) + [q] for t, q in sorted(added_packets)],
                pristine_primary=primary, incomplete_control=partial)


def score(sealed, directory, expected):
    data = sealed.read_bytes()
    if sha256(data).hexdigest() != expected:
        raise ValueError("placement seal differs from the specified digest")
    ledger = json.loads(data)
    base_history, later = prior_ids()
    previous = json.loads((NOV / "packet-bit-repair/field/group-evaluation.json").read_bytes())
    recent = json.loads((HERE.parent / "on-air/coverage.json").read_bytes())
    history = base_history | later | set(previous["combined_exposure"]["assigned_counters"]) | set(recent["all_assigned_counters"])
    hist_hash = sha256(",".join(map(str, sorted(history))).encode("ascii")).hexdigest()
    if hist_hash != "c9881e036bd57ab12cb8af4a5177a02bc30b348dd61d85539c6963d6a36032c1":
        raise ValueError("published pre-field inventory differs")
    result = dict(seal_sha256=expected, prior_inventory_size=len(history), prior_inventory_sha256=hist_hash)
    for arm in ("stock", "extended"):
        path = directory / arm / "packets.npz"
        if sha256(path.read_bytes()).hexdigest() != ledger["archive_sha256"][arm]:
            raise ValueError(f"{arm} packet snapshot differs from the placement seal")
        projected = {}
        for key in ("pristine_primary", "incomplete_control"):
            selected = ledger[key]
            projected[key] = selected_projection(path, selected["counter"] if selected else None)
        result[arm] = dict(overlap=sorted(history.intersection(ledger[arm]["assigned_counters"])), fields=projected)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest="action", required=True)
    placement = subs.add_parser("seal")
    placement.add_argument("msc", type=Path)
    placement.add_argument("receiver_output", type=Path)
    scoring = subs.add_parser("score")
    scoring.add_argument("sealed", type=Path)
    scoring.add_argument("receiver_output", type=Path)
    scoring.add_argument("expected_sha256")
    args = parser.parse_args()
    result = (seal(args.msc, args.receiver_output) if args.action == "seal" else
              score(args.sealed, args.receiver_output, args.expected_sha256))
    print(json.dumps(result, indent=2))
