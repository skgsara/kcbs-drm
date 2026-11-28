"""Score the public SWB GSC AUDIO b40 rule and fixed adjacent-slot timing controls."""
import argparse
from collections import Counter
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import sys


def load_source(raw, whole_dus):
    from project_evs_group import checked_units
    from received_evs_packets import read_packet_snapshot
    if whole_dus:
        return {3*c+p: (du, (True,)*4) for c, p, du in checked_units(BytesIO(raw))}
    ticks, units, flags = read_packet_snapshot(BytesIO(raw))
    return {int(tick): (unit, present) for tick, unit, present in zip(ticks, units, flags, strict=True)
            if present.any()}


def freeze(rows):
    from evs_gsc_fields import mode_predictions
    from received_evs_packets import PACKET_BYTES
    from render_continuous import MODE_POSITIONS
    modes, decisions = {}, []
    for tick in sorted(rows):
        unit, present = rows[tick]
        for index, offset in enumerate(MODE_POSITIONS):
            if not present[offset // PACKET_BYTES]:
                continue
            slot = 20 * tick + index
            mode = int(unit[offset])
            modes[slot] = mode
            for rule, expected in mode_predictions(mode):
                if rule == "audio_noisy":
                    counter, phase = divmod(tick, 3)
                    cycle, position = divmod(index, 4)
                    decisions.append([counter, phase, cycle, position + 1, mode, expected])
    return modes, decisions


def outcome(observed, expected):
    if observed is None:
        return "missing"
    return "matched" if observed == expected else "wrong"


def target(rows, slot):
    from evs_gsc_fields import observed_field
    from received_evs_packets import PACKET_BYTES
    from render_continuous import PACKET_STARTS
    tick, index = divmod(slot, 20)
    if tick not in rows:
        return None
    unit, present = rows[tick]
    offset = PACKET_STARTS[index] + 4
    return observed_field("audio_noisy", int(unit[offset])) if present[offset // PACKET_BYTES] else None


def summary(records):
    result = {}
    for branch in (0, 1):
        selected = [row for row in records if row["expected"] == branch]
        shifts = {}
        for delta in (-1, 0, 1):
            counts = Counter(eligible=len(selected), checked=0, matched=0, wrong=0, missing=0)
            baseline = Counter(matched=0, wrong=0, missing=0)
            for row in selected:
                observed = row["observed_b40"][delta + 1]
                counts["checked"] += int(observed is not None)
                counts[outcome(observed, branch)] += 1
                baseline[outcome(observed, 1)] += 1
            shifts[delta] = dict(**counts, constant_one=dict(baseline),
                                 extra_matches_over_constant_one=counts["matched"] - baseline["matched"])
        result[branch] = shifts
    return result


def score(raw, whole_dus=False):
    from evs_gsc_fields import mode_predictions
    rows = load_source(raw, whole_dus)
    groups = {tick // 3 for tick in rows}
    complete = {c for c in groups if all(3*c+p in rows and all(rows[3*c+p][1]) for p in range(3))}
    modes, decisions = freeze(rows)
    canonical = json.dumps(decisions, separators=(",", ":")).encode("ascii")
    decision_hash = sha256(canonical).hexdigest()
    secondary = next((row[:4] for row in decisions if row[-1] == 0), None)
    ledger = []
    for counter, phase, cycle, position, mode, expected in decisions:
        slot = 60*counter + 20*phase + 4*cycle + position - 1
        observed = [target(rows, slot + shift) for shift in (-1, 0, 1)]
        neighbors = []
        for shift in (-1, 1):
            neighbor = modes.get(slot + shift)
            if neighbor is None:
                neighbors.append("mode_missing")
            else:
                next_branch = dict(mode_predictions(neighbor)).get("audio_noisy")
                neighbors.append("outside_audio" if next_branch is None else
                                 "same_branch" if expected == next_branch else "other_branch")
        ledger.append(dict(counter=counter, phase=phase, cycle=cycle, position=position, mode_hex=f"{mode:02X}",
                           expected=expected, observed_b40=observed, neighbor_gate=neighbors))
    return dict(
        format="swb-audio-b40-reception-v1", archive_sha256=sha256(raw).hexdigest(),
        input_kind="complete_crc_dus" if whole_dus else "assigned_packet_bodies",
        assigned_counters=len(groups), complete_groups=len(complete), received_modes=len(modes),
        frozen_decision_columns=["counter", "phase", "cycle", "position", "mode", "expected"],
        frozen_decision_sha256=decision_hash,
        secondary_rule="Lowest (counter,phase,cycle,position) with a received AUDIO mode 6C–6F, including partial DUs. "
                       "Select before reading b40; retain missing or contradictory targets. No replacement.",
        secondary_coordinate=secondary, secondary_row=next((r for r in ledger if r["expected"] == 0), None),
        target_order=[-1, 0, 1], neighbor_gate_order=[-1, 1],
        coordinate_basis="Offsets are on the absolute 20 ms slot clock at fixed source decision coordinates; "
                         "a missing shifted target is counted, without seeking another slot.",
        all=summary(ledger), in_complete_groups=summary([row for row in ledger if row["counter"] in complete]),
        by_phase={p: summary([r for r in ledger if r["phase"] == p]) for p in range(3)},
        by_position={p: summary([r for r in ledger if r["position"] == p]) for p in range(1, 5)},
        ledger=ledger,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path, help="future packets.npz, or historical data_units.npz with --data-units")
    parser.add_argument("--repo", type=Path, required=True, help="published kcbs-drm checkout containing scripts/")
    parser.add_argument("--data-units", action="store_true", help="read a development-only whole-DU archive")
    parser.add_argument("--out", type=Path, help="new JSON output file; default stdout")
    args = parser.parse_args()
    sys.path.insert(0, str((args.repo / "scripts").resolve()))
    try:
        report = score(args.archive.read_bytes(), args.data_units)
        text = json.dumps(report, indent=2) + "\n"
        if args.out:
            with args.out.open("x") as stream:
                stream.write(text)
        else:
            sys.stdout.write(text)
    except (ValueError, OSError) as error:
        parser.exit(2, f"{parser.prog}: {error}\n")
