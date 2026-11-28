"""Account for observed EVS bits and the five existing projector field checks."""
import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
from string import hexdigits
import sys

from check_evs_origin import PROJECTED_OCTETS
from evs_core_history import COORDINATES, core_history
from evs_gsc_fields import gsc_fields
from evs_hq_neighbors import hq_neighbors
from evs_intra_word import intra_word
from evs_transition_tags import transition_tags
from render_continuous import MODE_POSITIONS, PACKET_STARTS


OUTCOMES = ("match", "mismatch", "unavailable", "restricted", "unrestricted", "contradiction")
BIT_COUNTS = ("direct_bits", "carried_unknown_bits", "no_receipt_bits")


def field_sections(slots):
    """Compute the five existing field reports on the same chronological projection."""
    return {rule.__name__: rule(slots)
            for rule in (transition_tags, core_history, intra_word, gsc_fields, hq_neighbors)}


def packet_ordinals(projection):
    phases = projection.get("received_du_phases")
    if (not isinstance(phases, list) or any(type(p) is not int or p not in range(3) for p in phases)
            or len(set(phases)) != len(phases)):
        raise ValueError("invalid received data-unit phases")
    if projection["format"] == "kcbs-evs-projection-v1":
        return [range(4) if p in phases else () for p in range(3)]
    ordinal_map = projection.get("received_packet_ordinals")
    if not isinstance(ordinal_map, dict) or ordinal_map.keys() - {"0", "1", "2"}:
        raise ValueError("invalid received packet ordinals")
    groups = [ordinal_map.get(str(p), []) for p in range(3)]
    for p, ordinals in enumerate(groups):
        if (not isinstance(ordinals, list) or any(type(q) is not int or q not in range(4) for q in ordinals)
                or len(set(ordinals)) != len(ordinals) or (len(ordinals) == 4) != (p in phases)):
            raise ValueError(f"packet ordinals disagree with the reported phases at phase {p}")
    return groups


def field_value(tokens, start, end):
    """Return the MSB-first field only when all its bits come from direct octets."""
    if not 0 <= start < end <= 264:
        raise ValueError(f"invalid EVS word bit range [{start},{end})")
    field = tokens[start // 8:(end + 7) // 8]
    if "--" in field:
        return "no_receipt", None
    if "??" in field:
        return "carried_unknown", None
    packed = int("".join(field), 16)
    return "direct", (packed >> (-end % 8)) & ((1 << (end - start)) - 1)


def projected_slots(projection):
    if not isinstance(projection, dict) or projection.get("format") not in (
            "kcbs-evs-projection-v1", "kcbs-evs-packet-projection-v1"):
        raise ValueError("expected a group or packet projection from project_evs_group.py")
    if projection.get("direct_word_octet_indices") != list(PROJECTED_OCTETS):
        raise ValueError("unexpected directly transmitted octet indices")
    packets = packet_ordinals(projection)
    source = projection.get("slots")
    if not isinstance(source, list) or len(source) != 60:
        raise ValueError("expected 60 chronological EVS slots")
    slots, words = [], []
    for i, row in enumerate(source):
        expected = (i, projection["counter"], i // 20, (i % 20) // 4, i % 4 + 1)
        if tuple(row[k] for k in COORDINATES) != expected:
            raise ValueError(f"unexpected coordinates for EVS slot {i}")
        tokens = row["octets"].split()
        if len(tokens) != 33 or any(token not in ("??", "--") and
                                    (len(token) != 2 or any(c not in hexdigits for c in token))
                                    for token in tokens):
            raise ValueError(f"invalid octets in EVS slot {i}")
        unknown, missing = 8 * tokens.count("??"), 8 * tokens.count("--")
        direct = 264 - unknown - missing
        i_in_phase = i % 20
        first = PACKET_STARTS[i_in_phase]
        offsets = (MODE_POSITIONS[i_in_phase], *range(first, first + 32))
        if any((token != "--") != (offset // 179 in packets[i // 20])
               for token, offset in zip(tokens, offsets, strict=True)):
            raise ValueError(f"octets disagree with the physical packet receipt in slot {i}")
        if any(token != "--" and (token != "??") != (j in PROJECTED_OCTETS)
               for j, token in enumerate(tokens)):
            raise ValueError(f"octet sources disagree with the direct projection in slot {i}")
        if missing == 264:
            receipt = "missing_du" if projection["format"] == "kcbs-evs-projection-v1" else "missing_packets"
        else:
            receipt = "received_du" if len(packets[i // 20]) == 4 else "received_packets"
        if row["receipt"] != receipt:
            raise ValueError(f"octets disagree with the receipt in slot {i}")
        if row["direct_bits"] != direct:
            raise ValueError(f"direct bit count differs from the octets in slot {i}")
        slots.append({k: row[k] for k in COORDINATES} | dict(
            receipt=row["receipt"], octets=row["octets"], direct_bits=direct, carried_unknown_bits=unknown,
            no_receipt_bits=missing, word_erased=direct != 264, events=[]))
        words.append(tokens)
    return slots, words


def event_spec(section, row, report):
    """Translate the reported domain and identify the input bit ranges the original rule read."""
    s = row["slot"]
    if section == "transition_tags":
        return ("transition_tag", "conditional", report["word_bits"], row["allowed_high_pairs"],
                [(s, 0, 5), (s, 6, 8), (s, 256, 264)])
    if section == "core_history":
        bit = row["target_word_bit"]
        if bit not in (6, 8):
            raise ValueError(f"unexpected core history target {bit}")
        check, kind = ("hq_previous_core", "direct_check") if bit == 6 else ("tcx_previous_core", "conditional")
        return check, kind, (bit, bit + 1), [row["predicted"]], [(s - 1, 0, 5), (s, 0, 6)]
    if section == "intra_word":
        check = row["check"]
        lower, upper = row["allowed"]  # Inclusive endpoints in the original report.
        if check == "swb_hq_class":
            kind, mode_bits = "conditional", 8
        elif check in ("wb_gsc_audio", "swb_gsc_inactive"):
            kind, mode_bits = "direct_check", 5
        else:
            raise ValueError(f"unknown intra-word check {check}")
        return check, kind, row["word_bits"], range(lower, upper + 1), [(s, 0, mode_bits)]
    if section == "gsc_fields":
        check = row["check"]
        if check not in ("audio_noisy", "inactive_nibble", "noisy_pitch_fill"):
            raise ValueError(f"unknown GSC check {check}")
        inputs = [(s, 0, 6)]
        if check == "noisy_pitch_fill":
            inputs.append((s, 40, 45))
        return check, "direct_check", report["fields"][check]["word_bits"], [row["predicted"]], inputs
    # The original HQ neighbour rule used successor bit 7 as a held-out witness.
    # Its hypothesis concerns the *central* word; that bit remains a separate target.
    bit = report["target_word_bit"]
    return ("hq_neighbor_class", "conditional", (bit, bit + 1), row["allowed_central_b8"],
            [(s - 1, 0, 8), (s, 0, 8), (s + 1, 0, 7), (s + 1, 7, 8)])


def normalize_event(section, row, report, words):
    s = row["slot"]
    check, kind, bounds, domain, sources = event_spec(section, row, report)
    start, end = bounds
    observation, observed = field_value(words[s], start, end)
    width = end - start
    allowed = sorted(set(domain))
    if any(type(v) is not int or not 0 <= v < 1 << width for v in allowed):
        raise ValueError(f"invalid allowed value for {check} at slot {s}")
    fixed = {}
    for bit in range(start, end):
        values = {(v >> (end - 1 - bit)) & 1 for v in allowed}
        if len(values) == 1:
            fixed[str(bit)] = values.pop()

    if kind == "direct_check":
        if observed != row["observed"]:
            raise ValueError(f"reported observation differs from the projected word for {check}, slot {s}")
        if observed is None:
            outcome = "unavailable"
        else:
            outcome = "match" if observed in allowed else "mismatch"
        original = {"hq_match": "match", "pass": "match", "hq_mismatch": "mismatch", "reject": "mismatch"}
        if original.get(row["outcome"], row["outcome"]) != outcome:
            raise ValueError(f"reported outcome differs from the observation for {check}, slot {s}")
    elif not allowed:
        outcome = "contradiction"
    else:
        outcome = "unrestricted" if len(allowed) == 1 << width else "restricted"

    inputs = []
    for source_slot, first, stop in sources:
        if not 0 <= source_slot < len(words):
            raise ValueError(f"{check} crosses the group boundary at slot {s}")
        _, value = field_value(words[source_slot], first, stop)
        if value is None:
            raise ValueError(f"missing input for an applicable {check} at slot {s}")
        role = "condition"
        if check == "hq_neighbor_class" and source_slot == s + 1 and first == 7:
            role = "withheld_witness"
            if value != row["successor_b7"]:
                raise ValueError(f"successor witness disagrees with its projected octet at slot {source_slot}")
        inputs.append(dict(slot=source_slot, word_bits=[first, stop], observed=value, role=role))
    return dict(section=section, check=check, kind=kind, word_bits=[start, end],
                allowed_values=allowed, excluded_value_count=(1 << width) - len(allowed),
                observation=observation, observed=observed, outcome=outcome, source_outcome=row["outcome"],
                fixed_bits=fixed, inputs=inputs)


def direct_fixed_counts(slots):
    """Compare uniquely fixed bits of direct checks with the received octets in this projection."""
    predictions = defaultdict(set)
    observed = {}
    for row in slots:
        octets = row["octets"].split()
        for event in row["events"]:
            if event["kind"] != "direct_check":
                continue
            for bit_string, value in event["fixed_bits"].items():
                bit = int(bit_string)
                coordinate = (row["slot"], bit)
                predictions[coordinate].add(value)
                octet = octets[bit // 8]
                if octet not in ("??", "--"):
                    observed[coordinate] = (int(octet, 16) >> (7 - bit % 8)) & 1
    fixed = {coord: next(iter(values)) for coord, values in predictions.items() if len(values) == 1}
    compared = fixed.keys() & observed.keys()
    matching = sum(fixed[coord] == observed[coord] for coord in compared)
    return dict(unique_direct_fixed_bits=len(fixed), unique_direct_fixed_bits_checked=len(compared),
                unique_direct_fixed_bits_matching=matching, unique_direct_fixed_bits_mismatching=len(compared) - matching,
                unique_direct_fixed_bits_unavailable=len(fixed) - len(compared),
                unique_conflicting_direct_bits=len(predictions) - len(fixed))


def summarize(slots, *, version=1):
    counts = {name: sum(row[name] for row in slots) for name in BIT_COUNTS}
    counts.update(slots=len(slots), word_erasures=sum(row["word_erased"] for row in slots),
                  rule_events=0, direct_check_events=0, conditional_events=0,
                  slots_with_rule_events=sum(bool(row["events"]) for row in slots))
    outcomes = Counter(dict.fromkeys(OUTCOMES, 0))
    targets, checked = set(), set()
    conditional = defaultdict(set)
    for row in slots:
        slot = row["slot"]
        for event in row["events"]:
            counts["rule_events"] += 1
            outcomes[event["outcome"]] += 1
            coordinates = {(slot, bit) for bit in range(*event["word_bits"])}
            targets.update(coordinates)
            if event["kind"] == "direct_check":
                counts["direct_check_events"] += 1
                if event["observed"] is not None:
                    checked.update(coordinates)
            else:
                counts["conditional_events"] += 1
                for bit, value in event["fixed_bits"].items():
                    conditional[slot, int(bit)].add(value)
    if version == 2:
        counts.update(direct_fixed_counts(slots))
    return counts | dict(events_by_outcome=dict(outcomes), unique_target_bits=len(targets),
                         unique_direct_checked_bits=len(checked),
                         unique_conditional_fixed_bits=sum(len(v) == 1 for v in conditional.values()),
                         unique_conflicting_conditional_bits=sum(len(v) > 1 for v in conditional.values()))


def bit_evidence(projection, *, version=1):
    """Return a new report. Conditional predictions never change the observed octets."""
    if type(version) is not int or version not in (1, 2):
        raise ValueError("unsupported EVS bit-evidence version")
    slots, words = projected_slots(projection)
    for section, expected in field_sections(projection["slots"]).items():
        report = projection.get(section)
        if not isinstance(report, dict) or not isinstance(report.get("slots"), list):
            raise ValueError(f"missing or malformed {section} field report")
        if report != expected:
            raise ValueError(f"saved {section} section disagrees with the supported field rules")
        for row in report["slots"]:
            s = row["slot"]
            if not isinstance(s, int) or not 0 <= s < len(slots):
                raise ValueError(f"invalid slot in {section}")
            if any(row[k] != slots[s][k] for k in COORDINATES):
                raise ValueError(f"{section} coordinates disagree at slot {s}")
            if section == "core_history" and row["outcome"] == "abstain":
                slots[s]["core_history_abstention"] = row["reason"]
                continue
            slots[s]["events"].append(normalize_event(section, row, report, words))
    result = dict(format=f"kcbs-evs-bit-evidence-v{version}", counter=projection["counter"],
                  total=summarize(slots, version=version),
                  by_position={str(p): summarize(slots[p - 1::4], version=version) for p in range(1, 5)}, slots=slots)
    if version == 2:
        result["direct_check_count_basis"] = (
            "unique_direct_checked_bits counts observed bit positions covered by field membership checks. "
            "unique_direct_fixed_bits counts positions where a direct rule's allowed values all give one "
            "bit value and all rules fixing that bit agree. Checked fixed bits use the same projection's "
            "received octets. Independent verification requires a separate source.")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("projection", help="project_evs_group.py --field-checks JSON, or - for stdin")
    parser.add_argument("--version", choices=(1, 2), type=int, default=1,
                        help="evidence format, with individual directly fixed bit counts in version 2")
    args = parser.parse_args()
    try:
        if args.projection == "-":
            projection = json.load(sys.stdin)
        else:
            with Path(args.projection).open(encoding="utf-8") as stream:
                projection = json.load(stream)
        result = bit_evidence(projection, version=args.version)
    except (OSError, ValueError, TypeError, KeyError) as error:
        parser.exit(2, f"{parser.prog}: {error}\n")
    print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
