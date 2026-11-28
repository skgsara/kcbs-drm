"""Evaluate original and repaired MSC with the same frozen 60-slot receiver and field scorer."""
import argparse
import gzip
from hashlib import sha256
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
NOV28 = HERE.parent
ROOT = NOV28.parents[1]
IQ = NOV28 / "clear-evs-controls" / "iq"
sys.path.insert(0, str(IQ))
import check as iq

from drm_row_alignment import PACKET_BYTES, ROW_BYTES, read_msc, valid_packets
from project_evs_group import checked_units
from received_evs_packets import read_packet_snapshot

# These are published files, selected before opening either input to this comparison.
PREVIOUS = IQ / "forecasts.json"
LAST_RUN = IQ.parent / "iq-mlc4" / "forecasts.json"
FORECAST_HASHES = (
    "f4b7fcafab4a050ee236c69029533e0f4a793140c0aaed0554a4da811bd59017",
    "7de2fbe6418376526be48c23834ea7278fe706a19db4dc45f94ed5e9c8e0102e",
)


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def prior_ids():
    encoded = iq.HISTORY.read_bytes()
    iq.require(sha256(encoded).hexdigest() == iq.HISTORY_SHA256, "base inventory changed")
    base = set(json.loads(gzip.decompress(encoded))["counter_ids"])
    additional = []
    for path, expected in zip((PREVIOUS, LAST_RUN), FORECAST_HASHES, strict=True):
        iq.require(digest(path) == expected, f"published forecast ledger changed: {path}")
        additional.append(set(json.loads(path.read_bytes())["assigned_counters"]))
    history = base | additional[0]
    last = additional[1]
    iq.require((len(base), len(additional[0]), len(history), len(last)) == (14958, 63, 15021, 29),
               "unexpected historic denominators")
    return history, last


def inventory(assigned, history, last):
    return dict(assigned_counters=sorted(assigned), overlap_with_15021=sorted(assigned & history),
                overlap_with_later_mlc4=sorted(assigned & last),
                absent_from_both=sorted(assigned - (history | last)))


def compare_wires(original, repaired):
    before, after = read_msc(original), read_msc(repaired)
    iq.require(len(before) == len(after), "original and repaired MSC row counts differ")
    changed_rows = changed_packets = newly_passing = 0
    for row, (left, right) in enumerate(zip(before, after, strict=True)):
        iq.require(len(left) == len(right), f"MSC row {row} changed length")
        if left == right:
            continue
        iq.require(len(left) == ROW_BYTES, f"unexpected change to non-packet row {row}")
        changed_rows += 1
        previous, current = valid_packets(left), valid_packets(right)
        for q, packet in previous.items():
            iq.require(current.get(q) == packet, f"original CRC-good packet changed at {row}/{q}")
        for q in range(4):
            start = q * PACKET_BYTES
            stop = start + PACKET_BYTES
            if left[start:stop] != right[start:stop]:
                changed_packets += 1
                newly_passing += q in current
    return dict(msc_rows=len(before), changed_rows=changed_rows, changed_packets=changed_packets,
                changed_packets_passing_header_and_crc=newly_passing)


def arm(msc, directory, forecasts_hash):
    iq.score(msc, directory, forecasts_hash)
    score = json.loads((directory / "score.json").read_bytes())
    stage = directory / "transport"
    provenance = json.loads((stage / "provenance.json").read_bytes())
    # Include every assigned counter, even when packet collisions or a bad DU CRC quarantined it.
    first_rows = {}
    for coord, origins in provenance.items():
        c = int(coord.split(",")[0])
        row = min(r for _, r in origins)
        first_rows[c] = min(first_rows.get(c, row), row)
    archive = stage / "packets.npz"
    ticks, bodies, flags = read_packet_snapshot(archive)
    accepted = set()
    complete = {}
    partial = set()
    for tick, body, present in zip(ticks, bodies, flags, strict=True):
        c, p = divmod(int(tick), 3)
        for q, ok in enumerate(present):
            if ok:
                iq.require(f"{c},{p},{q}" in provenance, "packet is missing its source row")
                accepted.add((c, p, q))
        if present.all():
            complete[c, p] = body.tobytes()
        elif present.any():
            partial.add(c)
    iq.require(complete == {(c, p): u for c, p, u in checked_units(stage / "data_units.npz")},
               "packet archive and complete DU data differ")
    # Same chronological partial-group criterion as the published Yokohama scorer.
    partial_counter = min(partial, key=lambda c: (first_rows[c], c), default=None)
    control = None
    if partial_counter is not None:
        projection = iq.project_group(archive, partial_counter, packets=True)
        projection.update(iq.field_sections(projection["slots"]))
        evidence = iq.bit_evidence(projection)
        iq.write_json(directory / "first-partial.json", evidence)
        control = dict(counter=partial_counter, first_assigned_msc_row=first_rows[partial_counter],
                       total=evidence["total"], by_position=evidence["by_position"],
                       report_sha256=digest(directory / "first-partial.json"))
    primary = score["primary"]
    evidence = primary["bit_evidence"]
    selection = None
    if evidence is not None:
        selection = dict(**primary["native_receipt"], total=evidence["total"], by_position=evidence["by_position"])
    summary = dict(msc_sha256=digest(msc), forecasts_sha256=forecasts_hash,
                   packets_sha256=digest(archive), data_units_sha256=digest(stage / "data_units.npz"),
                   score_sha256=digest(directory / "score.json"), native_transport=score["native_transport"],
                   accepted_packet_coordinates=len(accepted), accepted_complete_dus=len(complete),
                   primary=selection, first_partial=control, all_assigned_direct_field_scores=score["all_assigned"])
    return summary, set(first_rows)


def evaluate(original, repaired, out):
    history, last = prior_ids()
    iq.require(digest(iq.SCRIPTS / "evs_gsc_fields.py") == iq.PREDICTOR_SHA256, "frozen predictor changed")
    wire_comparison = compare_wires(original, repaired)
    out.mkdir(parents=True, exist_ok=False)
    inputs = {"original": original, "repaired": repaired}
    ledgers = {}
    # Both sets of mode-only decisions precede either set of field observations.
    for name, msc in inputs.items():
        iq.freeze(msc, out / name)
        ledgers[name] = digest(out / name / "forecasts.json")
    summaries = {}
    union = set()
    for name, msc in inputs.items():
        summary, assigned = arm(msc, out / name, ledgers[name])
        summary["exposure"] = inventory(assigned, history, last)
        summaries[name] = summary
        union.update(assigned)
    # Only the local Python modules actually loaded, plus this wrapper and prior inventories.
    dependencies = {Path(__file__).resolve(), iq.HISTORY, PREVIOUS, LAST_RUN}
    for module in tuple(sys.modules.values()):
        filename = getattr(module, "__file__", None)
        if filename:
            source = Path(filename).resolve()
            if source.is_relative_to(ROOT) and source.suffix == ".py":
                dependencies.add(source)
    report = dict(format="paired-msc-field-evaluation-v1", local_dependencies_sha256={
                      str(path.relative_to(ROOT)): digest(path) for path in sorted(dependencies)},
                  wire_comparison=wire_comparison, inventory_size=len(history), subsequent_mlc4_counter_count=len(last),
                  combined_inventory_size=len(history | last), combined_exposure=inventory(union, history, last),
                  selection="First consecutive complete native phase 0/1/2 triple in each input's MSC row order. "
                            "Historical overlap is disclosed without changing either selection.",
                  field_basis="Direct observations in the repaired arm depend on the input corrections. "
                              "Both arms use one physical recording. Conditional EVS checks have no independent "
                              "clear-word labels here. Each score.json lists all 60 slots when a primary exists.",
                  **summaries)
    iq.write_json(out / "field.json", report)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("original", type=Path, help="one unmodified length-framed Dream MSC dump")
    parser.add_argument("repaired", type=Path, help="the corresponding repair output, same recording")
    parser.add_argument("--out", required=True, type=Path, help="new output directory")
    args = parser.parse_args()
    try:
        evaluate(args.original.resolve(strict=True), args.repaired.resolve(strict=True), args.out.resolve())
    except (OSError, ValueError, KeyError) as exc:
        parser.exit(1, f"{exc}\n")
