"""Verify the placement seal and report ordinary receiver fields on the two selected groups."""
import argparse
import hashlib
import json
from pathlib import Path
import sys


HERE = Path(__file__).resolve().parent
ANCHORS = HERE.parent / "phase-anchors"
sys.path.insert(0, str(ANCHORS))
from score_air import NOV, prior_ids, selected_projection


def history():
    base, later = prior_ids()
    seen = base | later
    earlier = json.loads((NOV / "packet-bit-repair/field/group-evaluation.json").read_bytes())
    seen.update(earlier["combined_exposure"]["assigned_counters"])
    earlier = json.loads((HERE.parent / "on-air/coverage.json").read_bytes())
    seen.update(earlier["all_assigned_counters"])
    for archive in (ANCHORS / "field/seal.json", HERE.parent / "direct-octet/field/group-seal.json"):
        seen.update(json.loads(archive.read_bytes())["extended"]["assigned_counters"])
    digest = hashlib.sha256(",".join(map(str, sorted(seen))).encode("ascii")).hexdigest()
    if digest != "3fa7b3ad29857f9d8c144f5c57e3421892f435d62d23a7fc677d02456e19e2a3":
        raise ValueError("historical inventory differs from the frozen one")
    return seen, digest


def report(seal_path, expected, packets):
    raw = seal_path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError("supplied placement seal has a different digest")
    seal = json.loads(raw)
    if hashlib.sha256(packets.read_bytes()).hexdigest() != seal["archive_sha256"]["extended"]:
        raise ValueError("packet archive differs from the seal")
    seen, digest = history()
    assigned = set(seal["extended"]["assigned_counters"])
    result = dict(placement_seal_sha256=expected, prior_ids=len(seen), inventory_sha256=digest,
                  assigned_counters=len(assigned), previously_seen=sorted(assigned & seen))
    for key in ("pristine_primary", "incomplete_control"):
        selected = seal[key]
        result[key] = dict(selection=selected, in_history=selected["counter"] in seen,
                           fields=selected_projection(packets, selected["counter"])) if selected else None
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("placement_seal", type=Path)
    parser.add_argument("seal_sha256")
    parser.add_argument("packets", type=Path)
    args = parser.parse_args()
    print(json.dumps(report(args.placement_seal, args.seal_sha256, args.packets), indent=2))
