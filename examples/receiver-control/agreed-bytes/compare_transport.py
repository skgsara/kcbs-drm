"""Compare the sealed packet overlay to the three original 12:11 demodulations."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory


HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent / "phase-anchors"), str(HERE.parent / "disagreement")]
from phase_anchors import run
from score_air import inventory, project_group, read_packet_snapshot
from materialize import export
from field_groups import history


def compare(field, seal, work):
    paths = {name: field / f"{name}-msc.bin" for name in ("wiener1", "linear4", "wiener4")}
    material = export(paths["wiener1"].read_bytes(), paths["linear4"].read_bytes(),
                      field / "packet-proposals.json", seal, work / "overlay")
    paths["proposed"] = work / "overlay/proposed.msc.bin"
    groups = sorted({row["counter_if_transmitted_here"] for row in material["rows"]
                     if row["counter_if_transmitted_here"] is not None})
    arms = {}
    all_ids = set()
    coordinates = {}
    bodies = {}
    for name, path in paths.items():
        output = work / name
        run(path, output)
        packets_path = output / "extended/packets.npz"
        packets, units, full, ids = inventory(packets_path)
        coordinates[name] = packets
        ticks, data, flags = read_packet_snapshot(packets_path)
        bodies[name] = {(int(tick), q): bytes(unit[q * 179:(q + 1) * 179])
                        for tick, unit, present in zip(ticks, data, flags, strict=True)
                        for q, ok in enumerate(present) if ok}
        all_ids.update(ids)
        projections = {}
        for counter in groups:
            result = project_group(packets_path, counter, packets=True)
            projections[str(counter)] = {k: result[k] for k in (
                "received_packet_ordinals", "physically_complete_slots", "physically_partial_slots",
                "physically_missing_slots", "confirmed_direct_bits", "full_clear_words")}
        arms[name] = dict(msc_sha256=sha256(path.read_bytes()).hexdigest(), received_packets=len(packets),
                          complete_data_units=len(units), complete_groups=len(full), selected_groups=projections)
    added = coordinates["proposed"] - coordinates["wiener1"]
    removed = coordinates["wiener1"] - coordinates["proposed"]

    def coords(items):
        return [[*divmod(tick, 3), q] for tick, q in sorted(items)]

    comparison = []
    for tick, q in sorted(added):
        proposed = bodies["proposed"][tick, q]
        source_check = bodies["wiener4"].get((tick, q))
        comparison.append(dict(counter=tick // 3, phase=tick % 3, ordinal=q,
                               proposed_body_sha256=sha256(proposed).hexdigest(),
                               same_iq_wiener4_body_exact=proposed == source_check if source_check is not None else None))
    prior, _ = history()
    return dict(decision_sha256=seal, arms=arms, proposal_origins=material["rows"],
                proposed_minus_wiener1=coords(added), wiener1_minus_proposed=coords(removed),
                proposed_minus_any_single_pass=coords(added - coordinates["linear4"] - coordinates["wiener4"]),
                gained_body_comparisons=comparison, all_arm_assigned_counters=sorted(all_ids),
                all_arm_prior_overlap=sorted(prior & all_ids))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("field", type=Path)
    parser.add_argument("--seal", required=True)
    args = parser.parse_args()
    with TemporaryDirectory() as temp:
        print(json.dumps(compare(args.field, args.seal, Path(temp)), indent=2))
