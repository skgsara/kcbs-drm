"""Recheck assigned packet and complete DU changes between two decodes of the same IQ."""
import argparse
import gzip
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
NOV28 = HERE.parents[1]
sys.path.insert(0, str(HERE.parent / "transport-mlc4"))
from check import capture, decision_rows, digest, require
sys.path.insert(0, str(NOV28 / "same-6140-1232"))
from native_groups import native_groups


def difference(left, right):
    return dict(mlc1=len(left), mlc4=len(right), shared=len(left & right),
                gained=sorted(right - left), lost=sorted(left - right))


def compare(mlc1, mlc4, forecasts):
    source = json.loads(forecasts.read_bytes())
    before, after = capture(mlc1), capture(mlc4)
    require(source["msc_sha256"] == after.file_sha256, "forecasts apply to another primary input")
    counts = []
    for path, site in ((mlc1, before), (mlc4, after)):
        stats, chronology, groups, _ = native_groups(path.read_bytes())
        assigned = {key[0] for key in site.packets}
        complete = {c for c, _ in site.units if all((c,p) in site.units for p in range(3))}
        counts.append((assigned, complete, set(groups)))
        site.report.update(native_stats=stats, complete_native_groups=len(groups),
                           first_chronological_native_group=chronology[0]["counter"] if chronology else None)
    require(sorted(counts[1][0]) == source["assigned_counters"], "assigned packet IDs differ from forecasts")
    archive = NOV28 / "dual-diversity-field/history.json.gz"
    raw = archive.read_bytes()
    require(digest(raw) == source["history_sha256"], "earlier history differs")
    frozen = set(json.loads(gzip.decompress(raw))["counter_ids"])
    previous = HERE.parent / "iq/forecasts.json"
    earlier_ids = set(json.loads(previous.read_bytes())["assigned_counters"])
    history = frozen | earlier_ids
    require(len(frozen) == 14958 and len(earlier_ids) == 63 and len(history) == 15021, "previous IDs differ")
    classification = {}
    for kind in ("packets", "units"):
        rows = decision_rows(before, after, kind)
        classes = {s:sum(r["status"] == s for r in rows) for s in ("equal", "added", "lost", "conflicting")}
        classification[kind] = dict(mlc1=len(getattr(before,kind)), mlc4=len(getattr(after,kind)),
                                     counts=classes, changes=[r for r in rows if r["status"] != "equal"])
    old, new = counts
    return dict(format="drm-3205-360-420-transport-v1", comparison_basis="Both receiver runs use the same station recording.",
                msc_sha256=dict(mlc1=before.file_sha256, mlc4=after.file_sha256),
                primary_predictions_sha256=digest(forecasts.read_bytes()), mlc1=before.report, mlc4=after.report,
                assigned_counters=difference(old[0], new[0]), assigned_complete_groups=difference(old[1], new[1]),
                native_complete_groups=difference(old[2], new[2]), **classification,
                exposure=dict(frozen_history_gzip_sha256=digest(raw), previous_forecasts_sha256=digest(previous.read_bytes()),
                              union_count=len(history), mlc1_overlap=sorted(old[0] & history), mlc4_overlap=sorted(new[0] & history)))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--mlc1", type=Path, default=HERE / "mlc1-msc.bin")
    ap.add_argument("--mlc4", type=Path, default=HERE / "mlc4-msc.bin")
    ap.add_argument("--forecasts", type=Path, default=HERE / "forecasts.json")
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    report = compare(a.mlc1, a.mlc4, a.forecasts)
    with a.out.open("x") as out:
        out.write(json.dumps(report, indent=2) + "\n")
