"""Locate unassigned q3 records on the four hash-pinned development MSC files."""
import argparse
from collections import Counter, defaultdict
from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from check import CASE, Q3_START, SLICES, digest
from project_evs_group import checked_units
from received_evs_packets import read_packet_snapshot
from salvage_msc_packets import records, salvage
from tail_fill_audit import crc


def station(paths, dest, published_units):
    with redirect_stdout(StringIO()):
        salvage(paths, dest, transport_only=True, save_packets=True)
    ticks, units, flags = read_packet_snapshot(dest / "packets.npz")
    table = {(int(tick), q): bytes(unit[q * 179:(q + 1) * 179])
             for tick, unit, accepted in zip(ticks, units, flags, strict=True)
             for q in range(4) if accepted[q]}
    expected = {3 * c + phase: du for c, phase, du in checked_units(published_units)}
    complete = {int(t): bytes(u) for t, u, ok in zip(ticks, units, flags, strict=True) if ok.all()}
    if complete != expected:
        raise ValueError("the single-station baseline differs from the published complete-DU archive")
    assigned = set()
    for entries in json.loads((dest / "provenance.json").read_bytes()).values():
        assigned.update((path, row) for path, row in entries)
    return table, assigned


def indexes(table):
    fragments, markers = defaultdict(set), defaultdict(set)
    for (tick, q), body in table.items():
        phase = tick % 3
        if q == 3 and phase in (1, 2):
            a, b = SLICES[phase]
            fragments[body[a - Q3_START:b - Q3_START]].add(tick)
        elif q != 3:
            markers[q, body].add(tick)
    return fragments, markers


def locate(path, own, assigned, reference):
    index, markers = indexes(reference)
    counts = Counter()
    receipts = []
    additions = defaultdict(lambda: defaultdict(set))
    for i, row in enumerate(records(path)):
        counts["native_rows"] += 1
        if row is None or not row["packet_ok"][3]:
            continue
        counts["in_scope_valid_q3"] += 1
        if (str(path), i) in assigned:
            counts["already_assigned_rows"] += 1
            continue
        counts["unassigned_q3_rows"] += 1
        good = {q: row["payload"][q] for q, valid in enumerate(row["packet_ok"]) if valid}
        windows = [good[3][a - Q3_START:b - Q3_START] for a, b in SLICES[1:]]
        hits = set().union(*(index.get(window, ()) for window in windows))
        if not hits:
            counts["no_fragment_match"] += 1
            continue
        if len(hits) > 1:
            counts["ambiguous_fragment"] += 1
            continue
        tick = hits.pop()
        counts["unique_fragment_rows"] += 1
        corroborated = []
        conflicting = []
        for q, body in good.items():
            if q == 3:
                continue
            destinations = markers.get((q, body), set())
            if destinations == {tick}:
                corroborated.append(q)
            elif len(destinations) == 1:
                conflicting.append(q)
        if conflicting:
            counts["different_independent_coordinate"] += 1
            continue
        if not corroborated:
            counts["no_unique_second_packet"] += 1
            continue
        if 0 in good and good[0][1] >> 4 != tick % 3:
            counts["contradictory_phase"] += 1
            continue
        if any(table[tick, q] != body for q, body in good.items()
               for table in (own, reference) if (tick, q) in table):
            counts["contradictory_existing_packet"] += 1
            continue
        counts["independently_witnessed_rows"] += 1
        for q, body in good.items():
            additions[tick][q].add(body)
        counter, phase = divmod(tick, 3)
        receipts.append(dict(native_row=i, counter=counter, phase=phase, received_ordinals=sorted(good),
                             unique_other_packet_ordinals=corroborated,
                             ordinals_absent_from_source_baseline=[q for q in good if (tick, q) not in own]))
    labels = ("native_rows", "in_scope_valid_q3", "already_assigned_rows", "unassigned_q3_rows", "no_fragment_match",
              "ambiguous_fragment", "unique_fragment_rows", "different_independent_coordinate",
              "no_unique_second_packet", "contradictory_phase", "contradictory_existing_packet",
              "independently_witnessed_rows")
    return additions, dict(counts={key: counts[key] for key in labels}, rows=receipts)


def incorporate(baseline, proposed):
    """Resolve proposals together; do not let contradictory additions evict prior coverage."""
    result = baseline.copy()
    rejections = []
    for tick, choices in sorted(proposed.items()):
        row = {q: {baseline[tick, q]} for q in range(4) if (tick, q) in baseline}
        for q, bodies in choices.items():
            row.setdefault(q, set()).update(bodies)
        reason = None
        if any(len(bodies) != 1 for bodies in row.values()):
            reason = "conflicting_bodies"
        else:
            single = {q: next(iter(bodies)) for q, bodies in row.items()}
            if len(single) == 4:
                du = b"".join(single[q] for q in range(4))
                if crc(du[:-2]) != int.from_bytes(du[-2:], "big"):
                    reason = "assembled_du_crc"
        if reason is None:
            result.update({(tick, q): body for q, body in single.items()})
        else:
            c, p = divmod(tick, 3)
            rejections.append(dict(counter=c, phase=p, reason=reason))
    return result, rejections


def sites_union(tables):
    proposed = defaultdict(lambda: defaultdict(set))
    for table in tables:
        for (tick, q), body in table.items():
            proposed[tick][q].add(body)
    return incorporate({}, proposed)


def inventory(table):
    ticks = {t for t, _ in table}
    full_dus, complete_slots, direct_slots = set(), set(), set()
    for tick in ticks:
        qs = {q for q in range(4) if (tick, q) in table}
        if len(qs) == 4:
            full_dus.add(tick)
        for slot in range(20):
            cycle, role = divmod(slot, 4)
            payload = 7 + 131 * cycle + 33 * role
            mode = 2 + cycle if role == 0 else payload - 1
            wire = [mode, *range(payload, payload + 32)]
            direct = [mode, *(payload + i for i in range(32) if i % 3 != 0)]
            if all(addr // 179 in qs for addr in wire):
                complete_slots.add((tick, slot))
            if all(addr // 179 in qs for addr in direct):
                direct_slots.add((tick, slot))
    groups = {tick // 3 for tick in full_dus if tick % 3 == 0 and tick + 1 in full_dus and tick + 2 in full_dus}
    return dict(packet_coordinates=set(table), q3_coordinates={t for t, q in table if q == 3},
                complete_dus=full_dus, complete_three_du_groups=groups,
                complete_33_wire_octet_slots=complete_slots, all_22_direct_octets_slots=direct_slots)


def coverage(original, amended):
    before = inventory(original)
    after = inventory(amended)
    return {k: dict(before=len(v), after=len(after[k]), gained=len(after[k] - v), lost=len(v - after[k]))
            for k, v in before.items()}


def run(member_paths, edogawa):
    prior = json.loads((CASE.parent / "member-3205-20min/cross-frequency.json").read_bytes())
    expected = prior["sources"]["raw_msc_sha256"]
    actual = {f"member_3205_mlc1_window{i}": digest(p) for i, p in enumerate(member_paths)}
    actual["edogawa_6140"] = digest(edogawa)
    if any(value != expected[name] for name, value in actual.items()):
        raise ValueError("input native MSC SHA-256 differs from the published capture receipt")
    published_member = CASE.parent / "member-3205-20min/member-dus.npz"
    published_peer = CASE.parents[2] / prior["sources"]["edogawa_6140_du_archive"]
    with TemporaryDirectory() as tmp:
        member, am = station(member_paths, Path(tmp) / "member", published_member)
        peer, ap = station([edogawa], Path(tmp) / "peer", published_peer)
    candidate_m, report_m = locate(member_paths[0], member, am, peer)
    candidate_p, report_p = locate(edogawa, peer, ap, member)
    after_m, rejected_m = incorporate(member, candidate_m)
    after_p, rejected_p = incorporate(peer, candidate_p)
    prior_union, rejected_before = sites_union((member, peer))
    after_union, rejected_after = sites_union((after_m, after_p))
    return dict(format="unassigned-native-trailer-location-v1", selection_sha256=digest(Path(__file__).with_name("unassigned.md")),
                native_msc_sha256=actual,
                complete_du_archive_sha256={"member_3205": digest(published_member), "edogawa_6140": digest(published_peer)},
                member_3205=dict(location=report_m, quarantined_proposals=rejected_m, coverage=coverage(member, after_m)),
                edogawa_6140=dict(location=report_p, quarantined_proposals=rejected_p, coverage=coverage(peer, after_p)),
                union=dict(rejected_baseline_ticks=rejected_before, rejected_after_ticks=rejected_after,
                           coverage=coverage(prior_union, after_union)),
                scope="Previously unassigned original rows from two overlapping radio recordings. All proposed packets "
                      "passed their physical CRC. Slot counts concern received transport octets. A receiver that uses "
                      "the other station's labelled packets for alignment depends on that station. Each accepted "
                      "coordinate also has a separate unique whole-packet witness.")


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("member_windows", nargs=3, type=Path, help="3205 MLC1 native MSC windows in order 0,1,2")
    cli.add_argument("edogawa", type=Path, help="6140 native MSC dump")
    args = cli.parse_args()
    print(json.dumps(run([p.resolve() for p in args.member_windows], args.edogawa.resolve()), indent=2))
