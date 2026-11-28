"""Report physical and conditional clear-bit evidence at the sealed field selections."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ANCHORS = HERE.parent / "phase-anchors"
sys.path.insert(0, str(ANCHORS))
from score_air import NOV, prior_ids, selected_projection


def report(output, seal_path, expected):
    raw = seal_path.read_bytes()
    if sha256(raw).hexdigest() != expected:
        raise ValueError("placement seal differs from supplied digest")
    ledger = json.loads(raw)
    old, additional = prior_ids()
    previous = json.loads((NOV / "packet-bit-repair/field/group-evaluation.json").read_bytes())
    earlier = json.loads((ANCHORS.parent / "on-air/coverage.json").read_bytes())
    last = json.loads((ANCHORS / "field/seal.json").read_bytes())
    registry = old | additional | set(previous["combined_exposure"]["assigned_counters"])
    registry.update(earlier["all_assigned_counters"], last["extended"]["assigned_counters"])
    digest = sha256(",".join(map(str, sorted(registry))).encode("ascii")).hexdigest()
    if digest != "e586971034668bee5a39208f551bcbbb4ad8a8c716486a4f9d0e30747c9f8b5f":
        raise ValueError("historical registry changed")
    result = dict(sealed_transport_sha256=expected, prior_registry_size=len(registry), prior_registry_sha256=digest)
    for arm in ("stock", "extended"):
        path = output / arm / "packets.npz"
        if sha256(path.read_bytes()).hexdigest() != ledger["archive_sha256"][arm]:
            raise ValueError(f"{arm} packet archive differs from the seal")
        result[arm] = dict(overlap=sorted(registry.intersection(ledger[arm]["assigned_counters"])))
        for key in ("pristine_primary", "incomplete_control"):
            selected = ledger[key]
            result[arm][key] = selected_projection(path, selected["counter"] if selected else None)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("receiver_output", type=Path)
    parser.add_argument("seal", type=Path)
    parser.add_argument("expected_sha256")
    args = parser.parse_args()
    print(json.dumps(report(args.receiver_output, args.seal, args.expected_sha256), indent=2))
