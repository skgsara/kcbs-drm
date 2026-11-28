"""Select the first chronological complete group and project all 60 received EVS slots."""
import argparse
import gzip
from hashlib import sha256
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
HISTORY_SHA256 = "33d4925c8e8f0a3f0520aeea11a37df9eaeecd67e0a54deb9004f3ada8213ab4"
sys.path.insert(0, str(HERE.parents[2] / "scripts"))
sys.path.insert(0, str(HERE.parent / "same-6140-1232"))
from evs_evidence import bit_evidence, field_sections
from native_groups import native_groups
from project_evs_group import project_group
from received_evs_packets import read_packet_snapshot


def score(msc, transport):
    history = gzip.decompress((HERE / "history.json.gz").read_bytes())
    if sha256(history).hexdigest() != HISTORY_SHA256:
        raise ValueError("unexpected prior counter inventory")
    known = set(json.loads(history)["counter_ids"])
    packet_path = transport / "packets.npz"
    ticks, bodies, flags = read_packet_snapshot(packet_path)
    complete = {int(t): b.tobytes() for t, b, f in zip(ticks, bodies, flags, strict=True) if f.all()}
    provenance = json.loads((transport / "provenance.json").read_bytes())
    assigned = {int(coordinate.split(",")[0]) for coordinate in provenance}
    raw = msc.read_bytes()
    counts, receipts, _, units = native_groups(raw)
    for counter, triple in units.items():
        for phase, du in enumerate(triple):
            if complete.get(3 * counter + phase) != du:
                raise ValueError(f"native reception differs from packet archive at {counter}/{phase}")
    overlap = sorted(known & assigned)
    selection = receipts[0] if receipts else None
    evidence = None
    if selection:
        projection = project_group(packet_path, selection["counter"], packets=True)
        projection.update(field_sections(projection["slots"]))
        evidence = bit_evidence(projection)
    return dict(msc_sha256=sha256(raw).hexdigest(), packets_sha256=sha256(packet_path.read_bytes()).hexdigest(),
                transport_counts=counts, native_complete_group_count=len(units), assigned_counters=sorted(assigned),
                history_overlap=overlap, primary=selection, eligible_as_unseen=bool(selection and not overlap),
                primary_bits=evidence)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("msc", type=Path)
    parser.add_argument("transport", type=Path)
    args = parser.parse_args()
    print(json.dumps(score(args.msc, args.transport), indent=2))
