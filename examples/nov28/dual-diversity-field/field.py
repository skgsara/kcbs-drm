"""Score three chronological MSC streams and compare Edogawa-only forecasts with Yokohama-only fields."""
import argparse
from contextlib import redirect_stdout
import gzip
from hashlib import sha256
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
NOV28 = HERE.parent
SCRIPTS = NOV28.parents[1] / "scripts"
sys.path[:0] = [str(NOV28 / "edogawa-audio-branch"), str(NOV28 / "dual-iq-1228"), str(SCRIPTS)]
import primary as native
import score_fields as fields
from salvage_msc_packets import salvage
from drm_row_alignment import parse_msc, witnessed_pairs

HISTORY_SHA256 = "2a58d5882998ff422e684295664b328f7c443c03d3be728016a64509c765f363"


def save(path, obj):
    with path.open("x", encoding="utf-8") as stream:
        print(json.dumps(obj, indent=2), file=stream)


def history():
    raw = gzip.decompress((HERE / "history.json.gz").read_bytes())
    if sha256(raw).hexdigest() != HISTORY_SHA256:
        raise ValueError("case-local prior-exposure inventory digest differs")
    return set(json.loads(raw)["counter_ids"])


def transport(msc, out):
    with (out.parent / (out.name + "-salvage.json")).open("x") as stream, redirect_stdout(stream):
        salvage([msc], out, transport_only=True, save_packets=True)


def bind_combination(inputs, path):
    raw = {site: source.read_bytes() for site, source in inputs.items()}
    hashes = {site: sha256(data).hexdigest() for site, data in raw.items()}
    if not path.exists():
        if raw["combined"] != raw["left"]:
            raise ValueError("a changed combined stream requires its combiner report.json")
        return dict(kind="left_identity_control", msc_sha256=hashes)
    content = path.read_bytes()
    report = json.loads(content)
    if (report["format"] != "drm-witnessed-diversity-v1" or report["output_msc_sha256"] != hashes["combined"]
            or any(report["sources"][s]["msc_sha256"] != hashes[s] for s in ("left", "right"))):
        raise ValueError("ordered inputs or output differ from the combiner report")
    left, right, combined = (parse_msc(raw[site]) for site in ("left", "right", "combined"))
    pairs, _ = witnessed_pairs(left, right)
    ledger = report["rows"]
    if (len(left) != len(combined) or len(combined) != report["output_native_rows"]
            or pairs != [(entry["left_row"], entry["right_row"]) for entry in ledger]):
        raise ValueError("combined chronology differs from the witnessed row map")
    # Every altered wire quarter must belong to a named gain in the same left row.
    restored = list(left)
    for entry in ledger:
        row = entry["left_row"]
        verified = bytearray(left[row])
        for ordinal, expected in entry["new_packets_sha256"].items():
            q = int(ordinal)
            if q not in range(4):
                raise ValueError("invalid combined packet ordinal")
            segment = slice(182*q, 182*(q + 1))
            packet = combined[row][segment]
            if len(packet) != 182 or sha256(packet).hexdigest() != expected:
                raise ValueError("combined packet differs from its receipt")
            verified[segment] = packet
        restored[row] = bytes(verified)
    if restored != combined:
        raise ValueError("unreceipted change to the original left row order or bytes")
    return dict(kind="witnessed_combiner", msc_sha256=hashes, report_sha256=sha256(content).hexdigest(),
                status=report["status"], witnessed_pairs=len(pairs), byte_identical_to_left=combined == left)


def first_partial(archive, rows):
    """Use earliest assigned row of a counter having at least one partial phase, then counter."""
    partial = {tick // 3 for tick, (_, flags) in rows.items() if flags.any() and not flags.all()}
    if not partial:
        return None
    provenance = json.loads((archive / "provenance.json").read_bytes())
    first_row, counter = min((index, int(key.split(",")[0])) for key, origins in provenance.items()
                             if int(key.split(",")[0]) in partial for _, index in origins)
    return dict(counter=counter, first_assigned_row=first_row)


def evidence(path, counter):
    projection = native.project_group(path, counter, packets=True)
    projection.update(native.field_sections(projection["slots"]))
    report = native.bit_evidence(projection)
    return dict(full_clear_words=projection["full_clear_words"], **report)


def cross_score(decisions, modes, source_counters, peer, selections):
    """Held-out target values come only from native peer packet receipts."""
    events = fields.observe(decisions, peer)
    result = dict(rules=fields.alternatives(), all_assigned_source=fields.summarize(events, source_counters, modes),
                  native_peer_assigned_counters=len({tick // 3 for tick in peer}), events=events)
    for name, selected in selections.items():
        counter = selected["counter"] if selected else None
        subset = set() if counter is None else {counter}
        result[name] = dict(counter=counter, **fields.summarize(events, subset, modes))
    return result


def run(left, right, combined, out):
    known = history()
    if sha256((SCRIPTS / "evs_gsc_fields.py").read_bytes()).hexdigest() != fields.PREDICTOR_SHA256:
        raise ValueError("mode-only predictor differs from the published decision rule")
    inputs = {name: (directory / "msc.bin").resolve(strict=True)
              for name, directory in (("left", left), ("right", right), ("combined", combined))}
    archives = {name: out / name for name in inputs}
    out.mkdir(parents=True, exist_ok=False)

    transport(inputs["left"], archives["left"])
    left_rows = fields.snapshot(archives["left"] / "packets.npz")
    modes, decisions = fields.forecasts(left_rows)
    decision_bytes = json.dumps(decisions, separators=(",", ":")).encode("ascii")
    # Persist source-only decisions before reading any peer or combined transport fields.
    decision_digest = sha256(decision_bytes).hexdigest()
    save(out / "native-forecasts.json", dict(sha256=decision_digest,
         columns=["counter", "slot", "mode", "rule", "expected"], decisions=decisions))

    binding = bind_combination(inputs, combined / "report.json")
    for name in ("right", "combined"):
        transport(inputs[name], archives[name])
    observations = {}
    for name, msc in inputs.items():
        original = native.score(msc, archives[name])
        observations[name] = {key: original[key] for key in
                              ("msc_sha256", "packets_sha256", "transport_counts", "native_complete_group_count",
                               "assigned_counters", "primary")}
    left_count = observations["left"]["transport_counts"]["msc_rows"]
    combined_count = observations["combined"]["transport_counts"]["msc_rows"]
    if combined_count != left_count:
        raise ValueError("combined MSC must preserve the number and order of left physical rows")

    selected = dict(primary=observations["combined"]["primary"],
                    first_partial=first_partial(archives["combined"], fields.snapshot(archives["combined"] / "packets.npz")))
    overlap = {name: sorted(known.intersection(obs["assigned_counters"])) for name, obs in observations.items()}
    selection_report = {}
    for name, choice in selected.items():
        if choice is None:
            selection_report[name] = None
            continue
        counter = choice["counter"]
        for stream, archive in archives.items():
            save(out / f"{name}-{stream}-bits.json", evidence(archive / "packets.npz", counter))
        selection_report[name] = dict(**choice, counter_previously_exposed=counter in known,
                                      eligible_with_no_prior_overlap=not any(overlap.values()))
    source_counters = {tick // 3 for tick in left_rows}
    result = cross_score(decisions, modes, source_counters, fields.snapshot(archives["right"] / "packets.npz"), selected)
    save(out / "native-field-comparison.json", result)
    report = dict(history_sha256=HISTORY_SHA256, history_count=len(known), prior_overlap_by_stream=overlap,
                  combination=binding,
                  streams=observations, selections=selection_report, native_forecast_sha256=decision_digest,
                  field_comparison="Edogawa native mode receipts predict fields scored against Yokohama native target receipts.",
                  combined_evidence="Combined fields use both stations. These two recordings supply no third-station validation.",
                  field_comparison_path="native-field-comparison.json")
    save(out / "results.json", report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ("left", "right", "combined"):
        parser.add_argument("--" + option, type=Path, required=True, help="directory containing msc.bin")
    parser.add_argument("--out", type=Path, required=True, help="new output directory")
    args = parser.parse_args()
    try:
        report = run(args.left, args.right, args.combined, args.out)
        print(json.dumps(report["selections"], indent=2))
    except (KeyError, TypeError, ValueError, OSError) as error:
        parser.exit(2, f"{error}\n")
