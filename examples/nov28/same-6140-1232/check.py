"""Replay the two-receiver direct-field scores and compare the selected primary's 60 EVS projections."""
import argparse
from collections import Counter
import csv
import gzip
from hashlib import sha256
from io import StringIO
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "dual-iq-1228"))
import score_fields as scorer
from check_evs_origin import PROJECTED_OCTETS
from evs_evidence import bit_evidence, field_sections
from locate_evs_slots import unit_locations
from project_evs_group import project_group
from received_evs_packets import PACKET_BYTES
from render_continuous import MODE_POSITIONS, PACKET_STARTS

INDEPENDENT = "independent_yokohama"
FALLBACK = "secondary_edogawa_only"
CSV_HEADER = ("counter", "slot", "position", "mode", "field", "predicted", "target_source", "observed",
              "outcome", "mode_du_offset", "target_du_offset")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def checked_bytes(path, expected_hash):
    data = path.read_bytes()
    require(sha256(data).hexdigest() == expected_hash, f"{path.name} differs from its published SHA-256")
    return data


def station_transport(snapshot, receipt, site):
    """The archive supplies 179-byte bodies. native_groups.py checks native headers and packet CRCs."""
    packets = {}
    units = {}
    for tick, (unit, present) in snapshot.items():
        counter, phase = divmod(tick, 3)
        for ordinal, packet in enumerate(unit.reshape(4, PACKET_BYTES)):
            if present[ordinal]:
                packets[counter, phase, ordinal] = packet.tobytes()
        if present.all():
            units[counter, phase] = unit.tobytes()  # snapshot() already checked its transmitted DU CRC.

    require(len(packets) == receipt["coord_packets"], f"{site}: assigned packet count differs")
    require(len(units) == receipt["coord_dus"], f"{site}: complete DU count differs")
    counters = {counter for counter, _, _ in packets}
    require(sorted(counters) == receipt["assigned_counters"], f"{site}: assigned counters differ")
    complete_groups = {counter for counter in counters if all((counter, phase) in units for phase in range(3))}
    require(sorted(complete_groups) == receipt["archived_complete_groups"], f"{site}: complete archive groups differ")

    native_groups = set()
    previous_row = -1
    for group in receipt["direct_complete_groups"]:
        counter = group["counter"]
        start = group["phase0_row"]
        require(previous_row < start and start + 2 < receipt["msc_rows"], f"{site}: invalid native group row order")
        previous_row = start
        require(counter in complete_groups, f"{site}: native group {counter} lacks a complete archived DU")
        hashes = [sha256(units[counter, phase]).hexdigest() for phase in range(3)]
        require(hashes == group["du_sha256"], f"{site}: native/archived DU differs at counter {counter}")
        native_groups.add(counter)
    return packets, units, counters, native_groups


def coordinate_overlap(left, right):
    shared = left.keys() & right.keys()
    conflicts = sorted(key for key in shared if left[key] != right[key])
    return dict(left_only=len(left) - len(shared), right_only=len(right) - len(shared),
                union=len(left.keys() | right.keys()), intersection=len(shared),
                exact_matches=len(shared) - len(conflicts), conflicting_coordinates=[list(key) for key in conflicts])


def verify_transport(source, peer, native, primary, history, comparison):
    """Recompute the published comparison from the hash-bound assigned archives and chronological group receipts."""
    source_packets, source_units, source_ids, source_groups = station_transport(source, native["edogawa"], "edogawa")
    peer_packets, peer_units, peer_ids, peer_groups = station_transport(peer, native["yokohama"], "yokohama")
    peer_primary = None
    if primary is not None:
        packets = {key: body for key, body in peer_packets.items() if key[0] == primary}
        units = {key: body for key, body in peer_units.items() if key[0] == primary}
        peer_primary = dict(
            packets=len(packets),
            matching_packets=sum(source_packets.get(key) == body for key, body in packets.items()),
            complete_dus=len(units),
            equal_dus=sum(source_units.get(key) == body for key, body in units.items()),
            full_native=primary in peer_groups,
        )
    measured = dict(
        ordered_sources=["edogawa", "yokohama"],
        history_count=len(history),
        any_historical_intersection=dict(edogawa=sorted(source_ids & history), yokohama=sorted(peer_ids & history)),
        primary_id_seen_before=primary in history if primary is not None else None,
        primary_peer_receipt=peer_primary,
        comparison_packets=coordinate_overlap(source_packets, peer_packets),
        comparison_whole_dus=coordinate_overlap(source_units, peer_units),
        direct_complete_group_ids_both=sorted(source_groups & peer_groups),
        union_direct_complete_group_count=len(source_groups | peer_groups),
    )
    for name, value in measured.items():
        require(value == comparison[name], f"transport receipt differs for {name}")
    return measured


def field_counts(events):
    counts = scorer.counts(events)
    return dict(eligible=counts["predicted"], checked=counts["checked"], matched=counts["matched"],
                wrong=counts["mismatched"], missing=counts["no_peer"])


def field_summary(events):
    result = {}
    for rule in scorer.RULE_VALUES:
        subset = [event for event in events if event["rule"] == rule]
        positions = {str(pos): field_counts([event for event in subset if event["position"] == pos])
                     for pos in range(1, 5)}
        result[rule] = field_counts(subset) | {"position": positions}
    return result


def direct_signatures(snapshot):
    signatures = {}
    for tick, (unit, present) in snapshot.items():
        counter, phase = divmod(tick, 3)
        for (_, _, cycle, position), octets in unit_locations(counter, phase, unit, present):
            signatures[tick * 20 + cycle * 4 + position - 1] = octets
    return signatures


def signature_counts(slots, source, peer, shift):
    checked = matched = 0
    for slot in slots:
        left = source.get(slot)
        right = peer.get(slot + shift)
        if left is not None and right is not None:
            checked += 1
            matched += left == right
    return dict(eligible=len(slots), checked=checked, matched=matched, wrong=checked - matched,
                missing=len(slots) - checked)


def alignment_controls(decisions, source, peer, primary):
    """Keep each source prediction fixed while moving its peer target along the slot clock."""
    source_words = direct_signatures(source)
    peer_words = direct_signatures(peer)
    inactive = [decision for decision in decisions if decision[3] == "inactive_nibble"]
    inactive_slots = [60 * counter + slot for counter, slot, _, _, _ in inactive]
    primary_slots = [] if primary is None else range(60 * primary, 60 * (primary + 1))
    results = []
    for shift in (-60, -1, 0, 1, 60):
        shifted = []
        for counter, slot, mode, rule, expected in inactive:
            next_counter, next_slot = divmod(60 * counter + slot + shift, 60)
            shifted.append((next_counter, next_slot, mode, rule, expected))
        results.append(dict(
            peer_shift_slots=shift,
            inactive_nibble=field_counts(scorer.observe(shifted, peer)),
            inactive_direct_octets=signature_counts(inactive_slots, source_words, peer_words, shift),
            primary_direct_octets=signature_counts(primary_slots, source_words, peer_words, shift),
        ))
    return results


def verify_fields(decisions, source, peer, primary, saved, comparison, csv_path):
    source_label = saved.get("modes_from")
    peer_label = saved.get("independent_targets_from")
    require((source_label, peer_label) == ("edogawa", "yokohama"), "unexpected field source labels")
    require(saved["secondary_targets"] == "edogawa only where the independent target octet was missing",
            "unexpected fallback label")
    require(saved["chronological_primary"] == primary, "field report uses a different primary")
    require(saved["prior_history_gate"] == comparison["any_historical_intersection"], "history receipts differ")

    peer_events = scorer.observe(decisions, peer)
    missing = [decision for decision, event in zip(decisions, peer_events, strict=True) if event["peer_value"] is None]
    local_events = scorer.observe(missing, source)
    totals = {}
    for cohort in ("all", "primary"):
        totals[cohort] = {}
        for label, events in [(INDEPENDENT, peer_events), (FALLBACK, local_events)]:
            selected = events if cohort == "all" else [e for e in events if e["counter"] == primary]
            totals[cohort][label] = field_summary(selected)
    require(totals == saved["totals"], "field report differs from independent counts")

    buf = StringIO(newline="")
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(CSV_HEADER)
    fallback_rows = iter(local_events)
    for peer_event in peer_events:
        entries = [(INDEPENDENT, peer_event)]
        if peer_event["peer_value"] is None:
            entries.append((FALLBACK, next(fallback_rows)))
        for label, event in entries:
            slot = event["slot"]
            expected = event["expected"]
            observed = event["peer_value"]
            status = "missing" if observed is None else "matched" if observed == expected else "wrong"
            writer.writerow((event["counter"], slot, event["position"], event["mode"].lower(), event["rule"],
                             expected, label, observed, status, MODE_POSITIONS[slot % 20], PACKET_STARTS[slot % 20] + 4))
    encoded = buf.getvalue().encode("ascii")
    digest = sha256(encoded).hexdigest()
    require(digest == saved["individual_csv_sha256"], "regenerated chronological field rows differ")
    require(encoded == csv_path.read_bytes(), "saved field CSV differs from regenerated rows")
    return dict(row_sha256=digest, totals=totals)


def compare_primary(primary, source_path, peer_path, include_slots):
    """Compare only mode and the 21 directly carried payload octets (176 bits per received slot)."""
    if primary is None:
        return None
    projections = [project_group(path, primary, packets=True) for path in (source_path, peer_path)]
    saved_slots_path = source_path.parent / "primary-slots.json"
    evidence = [bit_evidence(group | field_sections(group["slots"])) for group in projections]
    require(evidence[0] == json.loads(saved_slots_path.read_text()),
            "saved Edogawa primary-slot evidence differs from the accepted packet projection")
    keys = ("direct_on_both", "direct_matching", "direct_differing", "edogawa_only", "yokohama_only",
            "missing_on_both", "edogawa_missing", "yokohama_missing",
            "edogawa_full_clear_words", "yokohama_full_clear_words")
    by_position = {p: Counter(dict.fromkeys(keys, 0)) for p in range(1, 5)}
    slots = []
    for edogawa, yokohama in zip(*(pr["slots"] for pr in projections), strict=True):
        slot = edogawa["slot"]
        require(slot == yokohama["slot"] and edogawa["counter"] == yokohama["counter"] == primary,
                "projected slot coordinates differ")
        left, right = edogawa["octets"].split(), yokohama["octets"].split()
        row = Counter(dict.fromkeys(keys, 0))
        row["edogawa_full_clear_words"] = int(edogawa["direct_bits"] == 264)
        row["yokohama_full_clear_words"] = int(yokohama["direct_bits"] == 264)
        for index in PROJECTED_OCTETS:
            a, b = left[index], right[index]
            require("??" not in (a, b), "unexpected hidden field in direct-octet set")
            if a == "--" or b == "--":
                row["edogawa_missing"] += 8 * (a == "--")
                row["yokohama_missing"] += 8 * (b == "--")
                side = "missing_on_both" if a == b else "yokohama_only" if a == "--" else "edogawa_only"
                row[side] += 8
            else:
                differences = (int(a, 16) ^ int(b, 16)).bit_count()
                row["direct_on_both"] += 8
                row["direct_differing"] += differences
                row["direct_matching"] += 8 - differences
        by_position[edogawa["position"]].update(row)
        if include_slots:
            slots.append(dict(slot=slot, phase=edogawa["phase"], cycle=edogawa["cycle"],
                              position=edogawa["position"], **row))
    total = Counter()
    for position in by_position.values():
        total.update(position)
    result = dict(counter=primary, nominal_direct_bits_per_position=15 * 176, by_position=by_position, total=total,
                  primary_slot_reports_equal=evidence[0] == evidence[1],
                  slot_evidence_sha256=sha256(saved_slots_path.read_bytes()).hexdigest(),
                  slot_rule_summary={site: report["total"] for site,report in zip(("edogawa","yokohama"), evidence)},
                  full_clear_words={site: pr["full_clear_words"] for site,pr in zip(("edogawa","yokohama"), projections)},
                  conditional_slot_evidence="python scripts/project_evs_group.py --packets PATH --counter "
                                            f"{primary} --evidence")
    if include_slots:
        result["slots"] = slots
    return result


def replay(case_dir, include_slots):
    comparison = json.loads((case_dir / "comparison.json").read_text())
    sources = json.loads(checked_bytes(case_dir / "sealed-sources.json", comparison["official_source_sha256"]))
    protocol = json.loads(checked_bytes(case_dir / "protocol.json", sources["protocol_sha256"]))
    prior = protocol["history"]
    registry = checked_bytes(case_dir / "history.json.gz", prior["file_sha256"])
    ids = json.loads(gzip.decompress(registry))["counter_ids"]
    history = set(ids)
    require(len(history) == len(ids) == prior["total"], "frozen history count differs")
    saved = json.loads((case_dir / "fields.json").read_text())
    plan = protocol["direct_fields"]
    predictor_sha = sha256((scorer.SCRIPTS / "evs_gsc_fields.py").read_bytes()).hexdigest()
    require(plan["predictor_sha256"] == predictor_sha and plan["predictor"] == "scripts/evs_gsc_fields.py:mode_predictions",
            "predictor differs from the same-carrier protocol")

    source_path = case_dir / "edogawa-packets.npz"
    peer_path = case_dir / "yokohama-packets.npz"
    packet_hashes = {}
    native = {}
    for site, path in (("edogawa", source_path), ("yokohama", peer_path)):
        native[site] = json.loads(checked_bytes(case_dir / f"{site}-native.json", comparison["stations"][site]))
        packet_hashes[path.name] = native[site]["archive_sha256"]["packets.npz"]
        checked_bytes(path, packet_hashes[path.name])
    primary_record = min(native["edogawa"]["direct_complete_groups"], key=lambda group: group["phase0_row"],
                         default=None)
    require(primary_record == comparison["primary"], "primary differs from earliest complete native group")
    primary = primary_record["counter"] if primary_record is not None else None
    source = scorer.snapshot(source_path)
    _, decisions = scorer.forecasts(source)
    peer = scorer.snapshot(peer_path)
    transport = verify_transport(source, peer, native, primary, history, comparison)
    return dict(
        packet_sha256=packet_hashes,
        field_protocol_sha256=sources["protocol_sha256"],
        transport=transport,
        fields=verify_fields(decisions, source, peer, primary, saved, comparison, case_dir / "field-rows.csv"),
        primary_direct=compare_primary(primary, source_path, peer_path, include_slots),
        retrospective_alignment_controls=alignment_controls(decisions, source, peer, primary),
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", type=Path, default=HERE, help="case directory (defaults to the published siblings)")
    parser.add_argument("--slots", action="store_true", help="include direct-bit counts for each chronological primary slot")
    parser.add_argument("--out", type=Path, help="write JSON here (default stdout)")
    args = parser.parse_args()
    output = json.dumps(replay(args.case, args.slots), indent=2, sort_keys=True) + "\n"
    if args.out:
        args.out.write_text(output)
    else:
        print(output, end="")


if __name__ == "__main__":
    main()
