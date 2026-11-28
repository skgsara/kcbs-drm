"""Freeze mode-only forecasts from native MSC, then score those forecasts on the same recording."""
import argparse
from contextlib import chdir
import gzip
from hashlib import sha256
import json
from pathlib import Path
import sys

NOV28 = Path(__file__).resolve().parents[2]
SCRIPTS = NOV28.parents[1] / "scripts"
sys.path[:0] = list(map(str, (SCRIPTS, NOV28 / "dual-iq-1228", NOV28 / "same-6140-1232")))
from evs_evidence import bit_evidence, field_sections
from native_groups import native_groups
from project_evs_group import project_group
from salvage_msc_packets import salvage
from score_fields import PREDICTOR_SHA256, alternatives, forecasts, observe, snapshot, summarize

HISTORY = NOV28 / "dual-diversity-field" / "history.json.gz"
HISTORY_SHA256 = "42985e72a35104e6590acc6a2f5a6e006b723cbcb3558d9ea99d5f41ffe82587"


def digest(data):
    return sha256(data).hexdigest()


def require(ok, message):
    if not ok:
        raise ValueError(message)


def write_json(path, obj, *, compact=False):
    with path.open("x", encoding="utf-8") as f:
        json.dump(obj, f, indent=None if compact else 2, separators=(",", ":") if compact else None,
                  allow_nan=False)
        f.write("\n")
    print(path, digest(path.read_bytes()))


def ledger(msc, packet_archive):
    """Only transport validation, coordinates, mode octets and their old predictions."""
    raw = msc.read_bytes()
    stats, chronology, _, _ = native_groups(raw)
    source = snapshot(packet_archive)
    modes, decisions = forecasts(source)
    encoded_history = HISTORY.read_bytes()
    require(digest(encoded_history) == HISTORY_SHA256, "counter history differs from the frozen inventory")
    history = set(json.loads(gzip.decompress(encoded_history))["counter_ids"])
    require(len(history) == 14958, "unexpected historical counter count")
    ids = sorted({tick // 3 for tick in source})
    return dict(schema="single-receiver-mode-forecasts-v1", msc_sha256=digest(raw),
                packet_archive_sha256=digest(packet_archive.read_bytes()), predictor_sha256=PREDICTOR_SHA256,
                history_sha256=HISTORY_SHA256, history_count=len(history), assigned_counters=ids,
                historical_overlap=sorted(history.intersection(ids)), native_transport=stats,
                complete_native_groups=chronology, primary=chronology[0] if chronology else None,
                received_mode_coordinates=modes, prediction_columns=["counter", "slot", "mode", "rule", "expected"],
                predictions=decisions)


def freeze(msc, out):
    out = out.resolve()
    msc = msc.resolve(strict=True)
    out.mkdir(parents=True, exist_ok=False)
    stage = out / "transport"
    # Keep salvage's original row provenance relative to the source directory.
    with chdir(msc.parent):
        salvage([msc.name], stage, transport_only=True, save_packets=True)
    write_json(out / "forecasts.json", ledger(msc, stage / "packets.npz"), compact=True)


def score(msc, out, expected_digest):
    raw_ledger = (out / "forecasts.json").read_bytes()
    require(digest(raw_ledger) == expected_digest, "forecast file differs from the separately recorded digest")
    frozen = json.loads(raw_ledger)
    archive = out / "transport" / "packets.npz"
    # Recompute from modes and native CRCs before opening any field as an observation.
    current = ledger(msc, archive)
    require(json.loads(json.dumps(current)) == frozen, "the MSC or archived forecasts differ from the freeze")
    source = snapshot(archive)
    events = observe(frozen["predictions"], source)
    def summary(ids):
        # The published helper labels its observation column peer_value. Here it comes
        # from the same physical packet snapshot on which the mode forecasts were made.
        return summarize(events, ids, frozen["received_mode_coordinates"])

    first = frozen["primary"]
    first_id = first["counter"] if first else None
    primary = summary({first_id} if first is not None else set())
    primary.update(native_receipt=first, cases=[e for e in events if e["counter"] == first_id])
    if first is not None:
        projection = project_group(archive, first_id, packets=True)
        require(projection["total_slots"] == 60 and len(projection["received_du_phases"]) == 3,
                "primary packet projection lacks three complete native phases")
        for phase, expected in enumerate(first["du_sha256"]):
            unit, present = source[3 * first_id + phase]
            require(present.all() and digest(bytes(unit)) == expected, "primary archive and native MSC differ")
        projection.update(field_sections(projection["slots"]))
        primary["bit_evidence"] = bit_evidence(projection)
        primary["projection"] = projection
    else:
        primary["projection"] = None
        primary["bit_evidence"] = None
    all_ids = set(frozen["assigned_counters"])
    report = dict(schema="single-receiver-direct-field-score-v1", msc_sha256=frozen["msc_sha256"],
                  packet_archive_sha256=frozen["packet_archive_sha256"], forecasts_sha256=expected_digest,
                  history_sha256=HISTORY_SHA256, history_count=frozen["history_count"],
                  historical_overlap=frozen["historical_overlap"], rules=alternatives(), primary=primary,
                  all_assigned=summary(all_ids), native_transport=frozen["native_transport"], observations=events,
                  observation_basis="Same-slot directly carried bits in the recorded packet archive. "
                                    "In the published summary schema, no_peer counts missing observed targets.")
    for event in events:
        event["observed"] = event.pop("peer_value")
    write_json(out / "score.json", report)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest="action", required=True)
    for action in ("freeze", "score"):
        sub = subs.add_parser(action)
        sub.add_argument("msc", type=Path)
        sub.add_argument("out", type=Path)
        if action == "score":
            sub.add_argument("expected_ledger_sha256")
    args = parser.parse_args()
    try:
        require(digest((SCRIPTS / "evs_gsc_fields.py").read_bytes()) == PREDICTOR_SHA256,
                "predictor differs from the published rule")
        if args.action == "freeze":
            freeze(args.msc, args.out)
        else:
            score(args.msc, args.out, args.expected_ledger_sha256)
    except (OSError, ValueError, KeyError) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
