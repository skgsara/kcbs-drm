"""Replay the two-receiver direct-field scores and compare the selected primary's 60 EVS projections."""
import argparse
from collections import Counter
import csv
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
from project_evs_group import project_group
from render_continuous import MODE_POSITIONS, PACKET_STARTS

INDEPENDENT = "independent_yokohama"
FALLBACK = "secondary_edogawa_only"
CSV_HEADER = ("counter", "slot", "position", "mode", "field", "predicted", "target_source", "observed",
              "outcome", "mode_du_offset", "target_du_offset")


def require(condition, message):
    if not condition:
        raise ValueError(message)


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
    protocol = json.loads((case_dir / "protocol.json").read_text())
    comparison = json.loads((case_dir / "comparison.json").read_text())
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
        receipt = (case_dir / f"{site}-native.json").read_bytes()
        require(sha256(receipt).hexdigest() == comparison["stations"][site], f"{site} native receipt differs")
        native[site] = json.loads(receipt)
        packet_hashes[path.name] = sha256(path.read_bytes()).hexdigest()
        require(packet_hashes[path.name] == native[site]["archive_sha256"]["packets.npz"],
                f"{site} packet snapshot differs from native receipt")
    primary_record = min(native["edogawa"]["direct_complete_groups"], key=lambda group: group["phase0_row"],
                         default=None)
    require(primary_record == comparison["primary"], "primary differs from earliest complete native group")
    primary = primary_record["counter"] if primary_record is not None else None
    source = scorer.snapshot(source_path)
    _, decisions = scorer.forecasts(source)
    peer = scorer.snapshot(peer_path)
    if primary is not None:
        fingerprints = []
        for phase in range(3):
            row = source.get(3*primary + phase)
            require(row is not None and row[1].all(), "selected primary lacks a complete Edogawa DU")
            fingerprints.append(sha256(row[0].tobytes()).hexdigest())
        require(fingerprints == primary_record["du_sha256"], "primary DUs disagree with the selection receipt")
    return dict(
        packet_sha256=packet_hashes,
        field_protocol_sha256=sha256((case_dir / "protocol.json").read_bytes()).hexdigest(),
        fields=verify_fields(decisions, source, peer, primary, saved, comparison, case_dir / "field-rows.csv"),
        primary_direct=compare_primary(primary, source_path, peer_path, include_slots),
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
