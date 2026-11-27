"""Predict from contributed 25–26 November modes, then check against published text labels."""
import argparse
from collections import Counter, defaultdict
from contextlib import redirect_stdout
from hashlib import sha256
import io
import json
from pathlib import Path
import tempfile

import numpy as np
from observe import ROOT, MODE_POSITIONS, restriction
from review_supplied_records import review
from salvage_msc_packets import salvage
from render_continuous import PACKET_STARTS

CONTRIB = ROOT / "contrib/kcbsdrm"
INPUTS = {
    "2026-11-25_0448KST_3205_hik": "2026-11-25",
    "2026-11-25_0457KST_3205_hik": "2026-11-25",
    "2026-11-25_1246KST_6140_merged": "2026-11-25_1246KST_merged",
    "2026-11-25_2242KST_3205_hl5ntr": "2026-11-25_2242KST_3205_hl5ntr",
    "2026-11-26_0500KST_3205_hl5ntr": "2026-11-26_0500KST_3205_hl5ntr",
    "2026-11-26_0642KST_merged": "2026-11-26_0642KST_merged",
    "2026-11-26_1008KST_merged": "2026-11-26_1008KST_merged",
}
MODES = ("F9", "FA", "FB")
PROTOCOL_SHA = sha256((Path(__file__).parent / "protocol.md").read_bytes()).hexdigest()


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def assembled(paths, out):
    with redirect_stdout(io.StringIO()):
        salvage(paths, out, transport_only=True)
    with np.load(out / "data_units.npz", allow_pickle=False) as f:
        coordinates = zip(f["counters"], f["phases"], f["du"], strict=True)
        units = {(int(counter), int(phase)): row for counter, phase, row in coordinates}
    reported = json.loads((out / "report.json").read_bytes())
    provenance = json.loads((out / "provenance.json").read_bytes())
    coordinates = {tuple(map(int, key.split(",")[:2])) for key in provenance}
    conflicts = len(reported["conflicting_data_units"])
    bad_crc = reported["reassembly_crc_failures"]
    partial = len(coordinates) - len(units) - conflicts - bad_crc
    if partial < 0:
        raise ValueError("inconsistent transport accounting")
    return units, dict(assigned_du_coordinates=len(coordinates), partial_dus=partial,
                       conflicting_dus=conflicts, reassembled_crc_failures=bad_crc,
                       per_source_complete_dus=len(units))


def transport():
    """Validate complete DUs and intersect with global packet conflict checks across files."""
    reference = CONTRIB / "reference"
    paths = {name: reference / f"sf_{name}.bin" for name in INPUTS}
    if set(paths.values()) != set(reference.glob("sf_2026*.bin")):
        raise ValueError("contributed archive set differs from the frozen population")
    origins = defaultdict(list)
    summary = {}
    with tempfile.TemporaryDirectory() as tmp:
        common, global_summary = assembled(list(paths.values()), Path(tmp) / "joint")
        for name, path in paths.items():
            units, stats = assembled([path], Path(tmp) / name)
            accepted = 0
            for coordinate, unit in units.items():
                if coordinate in common:
                    if not np.array_equal(common[coordinate], unit):
                        raise ValueError("joint receiver DU disagrees with a complete input")
                    origins[coordinate].append(name)
                    accepted += 1
            summary[name] = dict(stats, source_sha256=digest(path),
                                 cross_source_quarantined=len(units) - accepted,
                                 accepted_dus_including_duplicates=accepted)
    global_summary["joint_only_reassemblies_excluded"] = len(common) - len(origins)
    for name, stats in summary.items():
        stats["distinct_dus_assigned_to_input"] = sum(names[0] == name for names in origins.values())
        stats["duplicate_dus_counted_under_earlier_input"] = sum(name in names[1:] for names in origins.values())
    return {k: common[k] for k in origins}, origins, summary, global_summary


def read_modes(units, origins):
    for coordinate, unit in sorted(units.items()):
        counter, phase = coordinate
        for cycle, offset in enumerate(MODE_POSITIONS[::4]):
            yield counter, phase, cycle, int(unit[offset]), origins[coordinate][0]


def predict(mode_rows, summary, joint):
    """Consume coordinates and directly received modes; no label or payload is supplied."""
    cases = []
    physical_words = 0
    for counter, phase, cycle, mode, source in mode_rows:
        physical_words += 1
        allowed = restriction(mode)
        if allowed is not None:
            cases.append(dict(counter=counter, phase=phase, cycle=cycle, position=1,
                              mode=f"{mode:02X}", allowed_high_two_bits=list(allowed), input=source))
    return dict(protocol_sha256=PROTOCOL_SHA, inputs=summary, combined=joint,
                distinct_complete_dus=physical_words // 5, physical_p1_words=physical_words, cases=cases)


def existing_labels(units, origins):
    """Review only the contributor's pre-existing labels against received text tails."""
    result, summaries = {}, {}
    for tag in sorted(set(INPUTS.values())):
        path = CONTRIB / "keys" / f"keys_{tag}.npz"
        matching_inputs = {name for name, label in INPUTS.items() if label == tag}
        ticks = sorted(key for key, names in origins.items() if matching_inputs.intersection(names))
        with np.load(path, allow_pickle=False) as f:
            counters, labels, flags = f["counters"], f["ks"], f["crc_supported"]
        du_counters = np.array([c for c, phase in ticks], dtype=np.uint32)
        phases = np.array([phase for c, phase in ticks], dtype=np.uint8)
        dus = np.array([units[key] for key in ticks], dtype=np.uint8).reshape(-1, 716)
        checked, records = review(counters, labels, flags, du_counters, phases, dus)
        if np.any(checked & ~flags):
            raise ValueError("review unexpectedly added contributor support")
        result[tag] = {
            int(counter): (prefix, supported, reviewed)
            for counter, prefix, supported, reviewed in zip(counters, labels, flags, checked, strict=True)
        }
        summaries[tag] = dict(label_sha256=digest(path), contributor_counters=len(counters),
                              received_crc_checked_ordinary_records=len(records),
                              contributor_full_p1_counters=int(flags[:, :11].all(axis=1).sum()),
                              reviewed_full_p1_counters=int(checked[:, :11].all(axis=1).sum()))
    return result, summaries


def support(counter, names, labels):
    tags = sorted({INPUTS[name] for name in names})
    matches = [labels[tag][counter] for tag in tags if counter in labels[tag]]
    if not matches:
        return {}, "counter_without_label"
    active = [row for row in matches if row[1][0]]
    if not active:
        return {}, "contributor_p0_unsupported"
    octet = int(active[0][0][0])
    accepted = {"contributor_p0": octet}
    for prefix, flags, checked in active:
        for other, other_flags, _ in active:
            common = flags[:11] & other_flags[:11]
            if np.any((prefix[:11] != other[:11]) & common):
                return {}, "conflicting_contributor_labels"
        if flags[:11].all():
            accepted["contributor_full_p1"] = octet
        if checked[0]:
            accepted["reviewed_p0"] = octet
        if checked[:11].all():
            accepted["reviewed_full_p1"] = octet
    return accepted, None


def score(frozen, units, origins):
    labels, label_info = existing_labels(units, origins)
    pools = ("contributor_p0", "contributor_full_p1", "reviewed_p0", "reviewed_full_p1")
    counts = {name: {pool: Counter() for pool in pools} for name in INPUTS}
    modes = {name: Counter() for name in INPUTS}
    unsupported = {name: Counter() for name in INPUTS}
    by_coordinate = {}
    for coordinate, names in origins.items():
        counter, _ = coordinate
        values, reason = support(counter, names, labels)
        by_coordinate[coordinate] = values, reason
        for pool in values:
            counts[names[0]][pool]["all_supported_p1_words"] += 5

    observations = []
    for case in frozen["cases"]:
        coordinate = case["counter"], case["phase"]
        name, mode = case["input"], case["mode"]
        modes[name][mode] += 1
        values, reason = by_coordinate[coordinate]
        if reason:
            unsupported[name][reason] += 1
            continue
        if "reviewed_p0" not in values:
            unsupported[name]["contributor_p0_without_ordinary_crc_review"] += 1
        if "reviewed_p0" in values and "reviewed_full_p1" not in values:
            unsupported[name]["reviewed_p0_without_all_eleven_columns"] += 1

        offset = PACKET_STARTS[4 * case["cycle"]]
        received = int(units[coordinate][offset])
        observed = (received ^ values["contributor_p0"]) >> 6
        passed = observed in case["allowed_high_two_bits"]
        observations.append(dict(case, observed_high_two_bits=observed,
                                 applicable_support=list(values), passed=passed))
        for pool in values:
            by_field = counts[name][pool]
            by_field[mode + "_tested"] += 1
            by_field[mode + "_passed"] += int(passed)
            by_field[mode + "_violations"] += int(not passed)

    def totals(pool, name=None):
        selected = [row for row in observations if pool in row["applicable_support"]
                    and (name is None or row["input"] == name)]
        if name is None:
            data = sum((by_pool[pool] for by_pool in counts.values()), Counter())
        else:
            data = counts[name][pool]
        by_mode = {
            mode: {key: data[mode + "_" + key] for key in ("tested", "passed", "violations")}
            for mode in MODES
        }
        return dict(all_supported_p1_words=data["all_supported_p1_words"], eligible_words=len(selected),
                    eligible_counters=len({row["counter"] for row in selected}), by_mode=by_mode)

    inputs = {}
    for name in INPUTS:
        inputs[name] = dict(transport=frozen["inputs"][name], label_tag=INPUTS[name],
                            eligible_from_modes=dict(modes[name]),
                            exclusions_for_conditional_words=unsupported[name],
                            support={pool: totals(pool, name) for pool in pools})
    return dict(inputs=inputs, label_archives=label_info, totals={pool: totals(pool) for pool in pools},
                observations=observations, raw_iq_in_contribution=False,
                caveat="The two November 25 morning files share one label archive. Contributor CRC checks can pass incorrectly; the separate review checks received ordinary text with those same labels.")


def compact(result, frozen, output):
    exclusions = Counter()
    by_input = {}
    for name, row in result["inputs"].items():
        exclusions.update(row["exclusions_for_conditional_words"])
        by_input[name] = dict(source_sha256=row["transport"]["source_sha256"],
                              label_tag=row["label_tag"], partial_dus=row["transport"]["partial_dus"],
                              eligible_from_modes=row["eligible_from_modes"],
                              exclusions=row["exclusions_for_conditional_words"])
        for pool in ("contributor_p0", "reviewed_full_p1"):
            metrics = row["support"][pool]
            by_input[name][pool] = dict(eligible=metrics["eligible_words"],
                                        counters=metrics["eligible_counters"],
                                        tested={m: metrics["by_mode"][m]["tested"] for m in MODES},
                                        violations=sum(v["violations"] for v in metrics["by_mode"].values()))
    observed = {m: Counter() for m in MODES}
    for row in result["observations"]:
        if "reviewed_full_p1" in row["applicable_support"]:
            observed[row["mode"]][format(row["observed_high_two_bits"], "02b")] += 1
    return dict(protocol_sha256=frozen["protocol_sha256"], predictions_sha256=result["predictions_sha256"],
                full_score_sha256=digest(output), complete_dus=frozen["distinct_complete_dus"],
                transport=frozen["combined"], complete_p1_words=frozen["physical_p1_words"],
                predictions=len(frozen["cases"]), exclusions=exclusions, inputs=by_input,
                label_archives=result["label_archives"], totals=result["totals"],
                reviewed_observed_high_two_bits=observed,
                raw_iq_in_contribution=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("predict", help="Read transport modes, write conditional projections and their SHA-256")
    p.add_argument("output", type=Path)
    p = sub.add_parser("score", help="Verify the prediction digest before opening any label archive")
    p.add_argument("predictions", type=Path)
    p.add_argument("frozen_sha256")
    p.add_argument("output", type=Path)
    p.add_argument("--summary", type=Path, help="also write a compact checksum-linked score report")
    args = parser.parse_args()
    frozen = None
    if args.command == "score":
        paths = [args.output, args.predictions]
        if args.summary:
            paths.append(args.summary)
        if len({path.resolve() for path in paths}) != len(paths):
            parser.error("use separate paths for predictions, score and summary")
        raw = args.predictions.read_bytes()
        if sha256(raw).hexdigest() != args.frozen_sha256:
            raise ValueError("prediction receipt digest mismatch")
        frozen = json.loads(raw)
    units, origins, summary, joint = transport()
    projection = predict(read_modes(units, origins), summary, joint)
    if frozen is None:
        result = projection
    else:
        if frozen != projection:
            raise ValueError("frozen prediction source, coordinates or rules differ")
        result = score(frozen, units, origins)
        result["predictions_sha256"] = args.frozen_sha256
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    if frozen is not None and args.summary:
        report = compact(result, frozen, args.output)
        args.summary.write_text(json.dumps(report, indent=2) + "\n")
    print(digest(args.output))


if __name__ == "__main__":
    main()
