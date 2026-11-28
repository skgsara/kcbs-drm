"""Forecast and verify the directly carried HQ switch flag across consecutive native DRM groups."""
import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT / "scripts"), str(ROOT / "examples/nov28/same-6140-1232")]
from check_evs_group_boundary import ENDPOINTS, predict
from drm_row_alignment import parse_msc, valid_packets
from native_groups import native_groups

FORMAT = "kcbs-native-hq-boundary-plan-v1"


@dataclass
class Group:
    counter: int
    start: int
    units: tuple
    wires: tuple


def read_groups(path):
    raw = path.read_bytes()
    rows = parse_msc(raw)
    anchors = defaultdict(list)
    intact = []
    for start, row in enumerate(rows):
        packets = valid_packets(row)
        if 0 not in packets or 3 not in packets or packets[0][2] >> 4 != 0:
            continue
        # The counter begins at DU byte 664, inside q3's 179-byte body.
        counter_index = 1 + 664 - 3 * 179
        counter = int.from_bytes(packets[3][counter_index:counter_index + 4], "big")
        anchors[counter].append(start)
        # Check the three original rows together. A damaged or intervening row breaks the group.
        triple = b"".join(len(wire).to_bytes(4, "little") + wire for wire in rows[start:start + 3])
        _, receipts, wires, units = native_groups(triple)
        if receipts:
            if receipts[0]["counter"] != counter or receipts[0]["phase0_row"] != 0:
                raise ValueError("pristine group disagrees with the phase-zero anchor")
            intact.append(Group(counter, start, units[counter], wires[counter]))
    repeats = {str(counter): starts for counter, starts in anchors.items() if len(starts) > 1}
    unique = {g.counter: g for g in intact if len(anchors[g.counter]) == 1}
    summary = dict(msc_sha256=sha256(raw).hexdigest(), native_rows=len(rows),
                   intact_group_occurrences=len(intact), unique_intact_groups=len(unique),
                   first_intact_counter=intact[0].counter if intact else None,
                   last_intact_counter=intact[-1].counter if intact else None,
                   repeated_anchor_rows=repeats)
    return unique, summary


def adjacent_left(groups, right):
    if right.counter == 0:
        return None, "counter_zero_or_wrap"
    left = groups.get(right.counter - 1)
    if left is None:
        return None, "previous_group_missing_or_repeated"
    if left.start + 3 != right.start:
        return None, "nonconsecutive_native_rows"
    return left, None


def features(left, right):
    # Do not pass the target bit, lower mode bit, packets, CRCs or hashes to the predictor.
    return left.units[2][ENDPOINTS[2]] >> 3, right.units[0][ENDPOINTS[0]] >> 2


def make_plan(groups, summary):
    abstentions = Counter()
    forecasts = []
    adjacent = 0
    for right in groups.values():  # Native file order, including after a discontinuity.
        left, reason = adjacent_left(groups, right)
        if reason:
            abstentions[reason] += 1
            continue
        adjacent += 1
        prior_top5, current_top6 = features(left, right)
        prediction, reason = predict(prior_top5 << 3, current_top6)
        if reason:
            abstentions[reason] += 1
            continue
        older, shifted_reason = adjacent_left(groups, left)
        shifted = older_top5 = None
        if older is not None:
            older_top5 = older.units[2][ENDPOINTS[2]] >> 3
            shifted, shifted_reason = predict(older_top5 << 3, current_top6)
        forecasts.append(dict(counter=right.counter, phase0_rows=[left.start, right.start],
                              previous_p4_top5=prior_top5, current_p1_top6=current_top6,
                              predicted=prediction, always_zero=0, shifted_c_minus_2=shifted,
                              shifted_previous_p4_top5=older_top5, shifted_abstention=shifted_reason))
    return dict(format=FORMAT, source=summary, target_word_bit=6, consecutive_native_edges=adjacent,
                abstentions=dict(abstentions), forecast_count=len(forecasts), forecasts=forecasts)


def endpoint_witness(group, phase):
    ordinal = ENDPOINTS[phase] // 179
    wire = group.wires[phase][ordinal * 182:(ordinal + 1) * 182]
    return dict(row=group.start + phase, counter=group.counter, phase=phase, packet_ordinal=ordinal,
                mode_du_offset=ENDPOINTS[phase], packet_crc=wire[-2:].hex(),
                du_crc=group.units[phase][-2:].hex())


def score(seal_path, expected_sha, path, peer):
    data = seal_path.read_bytes()
    if sha256(data).hexdigest() != expected_sha:
        raise ValueError("plan SHA-256 differs from the external seal")
    plan = json.loads(data)
    if plan.get("format") != FORMAT:
        raise ValueError("unrecognized forecast format")
    groups, source = read_groups(path)
    if not peer:
        if source["msc_sha256"] != plan["source"]["msc_sha256"]:
            raise ValueError("scoring MSC differs from source; a second observation requires --peer")
        if make_plan(groups, source) != plan:
            raise ValueError("forecast could not be reproduced from the sealed source")
    tallies = {key: dict(match=0, mismatch=0, unavailable=0)
               for key in ("predicted", "always_zero", "shifted_c_minus_2")}
    rows = []
    for forecast in plan["forecasts"]:
        counter = forecast["counter"]
        right = groups.get(counter)
        left, reason = adjacent_left(groups, right) if right else (None, "current_group_missing_or_repeated")
        observed = None
        witnesses = None
        raw_target = None
        if left is not None:
            witnesses = [endpoint_witness(left, 2), endpoint_witness(right, 0)]
            raw_target = (right.units[0][ENDPOINTS[0]] >> 1) & 1
            if features(left, right) == (forecast["previous_p4_top5"], forecast["current_p1_top6"]):
                observed = raw_target
            else:
                reason = "reference_mode_prefix_disagrees"
        outcomes = {}
        for method, counts in tallies.items():
            proposed = forecast[method]
            outcome = "unavailable" if observed is None or proposed is None else (
                "match" if proposed == observed else "mismatch")
            counts[outcome] += 1
            outcomes[method] = outcome
        rows.append(dict(counter=counter, predicted=forecast["predicted"], source_phase0_rows=forecast["phase0_rows"],
                         native_witnesses=witnesses, raw_target_b6=raw_target, observed=observed,
                         reference_abstention=reason, outcomes=outcomes))
    return dict(format="kcbs-native-hq-boundary-score-v1", forecast_sha256=expected_sha,
                source_msc_sha256=plan["source"]["msc_sha256"], reference=source,
                reference_mode="separate_input" if peer else "sealed_source", methods=tallies, rows=rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest="action", required=True)
    create = subs.add_parser("seal", help="write the native-group forecasts as JSON to stdout")
    create.add_argument("msc", type=Path)
    check = subs.add_parser("score", help="verify the external plan digest before reading target bits")
    check.add_argument("plan", type=Path)
    check.add_argument("sha256")
    check.add_argument("msc", type=Path)
    check.add_argument("--peer", action="store_true", help="score against a second arm or independent recording")
    args = parser.parse_args()
    try:
        result = (make_plan(*read_groups(args.msc)) if args.action == "seal" else
                  score(args.plan, args.sha256, args.msc, args.peer))
    except (ValueError, OSError) as error:
        parser.exit(2, f"{parser.prog}: {error}\n")
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
