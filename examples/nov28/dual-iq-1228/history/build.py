"""Make the frozen pre-result inventory using only historical transport coordinates."""
import csv
import gzip
import hashlib
import io
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

REV = "901d23e091c13c8b350dbee41024303ac0995ec8"
repo = Path(sys.argv[1])
out = Path(sys.argv[2])
out.mkdir(parents=True, exist_ok=True)
history = set()
sources = []


def git(*args):
    return subprocess.check_output(["git", "-C", str(repo), *args])


def record(path, blob, selector, values):
    ids = set(map(int, values))
    if any(c < 0 or c > 2**32 - 1 for c in ids):
        raise ValueError(path)
    added = len(ids - history)
    history.update(ids)
    sources.append({"path": path, "sha256": hashlib.sha256(blob).hexdigest(),
                    "coordinates": selector, "distinct_ids": len(ids), "new_to_union": added})


files = git("ls-tree", "-r", "--name-only", REV).decode().splitlines()
for p in files:
    if p.endswith(("/history.json.gz", "/historical-counter-ids.json.gz")):
        raw = git("show", REV + ":" + p)
        record(p, raw, "counter_ids", json.loads(gzip.decompress(raw))["counter_ids"])

base = "examples/nov28/"
metadata = {
    "airspy-150-gap/target-result.json": "historically_unseen_union_including_partial",
    "bit-evidence/tail-reception.json": "assigned_counters",
    "group-boundary/reception.json": "assigned_ids",
    "group-boundary/second-pass.json": "retrospective_assigned_counters",
    "member-3205-20min/second-pass.json": "new_distinct_counters",
}
for name, key in metadata.items():
    p = base + name
    raw = git("show", REV + ":" + p)
    record(p, raw, key, json.loads(raw)[key])

p = base + "member-3205-20min/reception.json"
raw = git("show", REV + ":" + p)
union = json.loads(raw)["union"]
a, b = union["counter_range_inclusive"]
ids = set(range(a, b + 1))
for a, b in union["no_assigned_packet_counters"]:
    ids.difference_update(range(a, b + 1))
assert len(ids) == union["distinct_assigned_counters"]
record(p, raw, "union inclusive counter range, excluding each inclusive no-assigned interval", ids)

p = base + "four-frequency/member-100239/reception.json"
raw = git("show", REV + ":" + p)
full = json.loads(raw)["drm_splits"][0]
a, b = full["complete_counter_bounds"]
assert b - a + 1 == full["complete_counter_count"]
record(p, raw, "full-file contiguous complete_counter_bounds, plus explicit first and last assigned",
       [*range(a,b+1),full["first_assigned_coordinate"][0],full["last_assigned_coordinate"][0]])

for p in files:
    name = Path(p).name.lower()
    if p.startswith("examples/") and name.endswith(".npz") and any(
            term in name for term in ["units", "packet", "-dus.", "dual-"]):
        raw = git("show", REV + ":" + p)
        with np.load(io.BytesIO(raw), allow_pickle=False) as z:
            if "counters" in z.files:
                selector, ids = "counters", z["counters"]
            elif "ticks" in z.files:
                selector, ids = "ticks // 3", z["ticks"] // 3
            elif "tick" in z.files:
                selector, ids = "tick // 3", z["tick"] // 3
            else:
                raise ValueError((p,z.files))
            record(p, raw, selector, ids)

p = "examples/nov15/validation/complete-counters.csv"
raw = git("show", REV + ":" + p)
record(p, raw, "counter", [r["counter"] for r in csv.DictReader(io.StringIO(raw.decode()))])

plain = (json.dumps({"counter_ids": sorted(history)}, separators=(",",":")) + "\n").encode()
buf = io.BytesIO()
with gzip.GzipFile(fileobj=buf, mode="wb", filename="", mtime=0) as fh:
    fh.write(plain)
packed = buf.getvalue()
(out / "history.json.gz").write_bytes(packed)
result = {"revision": REV, "distinct_ids": len(history), "serialization":"UTF-8 compact JSON, sorted distinct integers under counter_ids, trailing LF, gzip mtime=0",
          "json_sha256":hashlib.sha256(plain).hexdigest(), "gzip_sha256":hashlib.sha256(packed).hexdigest(),
          "scope":"Union of the eight committed historical inventories, later published assigned counters (including partials), available coordinate arrays in the named public transport snapshots, and the Nov 15 complete-counter list. Earlier inventory inclusions retain their original provenance. Not a survey of private or unpublished captures. No trial files, masks, plaintext or application labels are used.",
          "sources":sources}
(out / "sources.json").write_text(json.dumps(result,indent=2)+"\n")
print({k:result[k] for k in ["distinct_ids","json_sha256","gzip_sha256"]})
