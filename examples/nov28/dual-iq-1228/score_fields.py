"""Score the two sealed mode-only 3205 kHz forecasts against independent 6140 kHz receipts."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys

SCRIPTS = Path(__file__).resolve().parents[3] / "scripts"
sys.path.insert(0, str(SCRIPTS))
from evs_gsc_fields import FIELD_DEFINITIONS, mode_predictions, observed_field
from received_evs_packets import PACKET_BYTES, read_packet_snapshot
from render_continuous import MODE_POSITIONS, PACKET_STARTS

RULE_VALUES = {"audio_noisy": (0, 1), "inactive_nibble": (12,)}
PREDICTOR_SHA256 = "204b9b920134255a2507bdc656364283c1587db34a218a6ef5d8d92b54ad84e9"
PROTOCOL_SHA256 = "433ac5487264516e337cf2833125cf0cc53b44b742ba69755a6a347c73504cb8"


def snapshot(path):
    ticks, units, flags = read_packet_snapshot(path)
    return {int(tick): (unit, present) for tick, unit, present in zip(ticks, units, flags, strict=True)
            if present.any()}


def forecasts(source):
    modes = []
    decisions = []
    for tick, (unit, present) in source.items():
        counter, phase = divmod(tick, 3)
        for index, offset in enumerate(MODE_POSITIONS):
            if not present[offset // PACKET_BYTES]:
                continue
            slot = 20 * phase + index
            mode = int(unit[offset])
            modes.append((counter, slot))
            for rule, expected in mode_predictions(mode):
                decisions.append((counter, slot, mode, rule, expected))
    return modes, decisions


def observe(decisions, peer):
    events = []
    for counter, slot, mode, rule, expected in decisions:
        phase, index = divmod(slot, 20)
        offset = PACKET_STARTS[index] + 4  # Zero-based payload octet 4, full word octet 5.
        row = peer.get(3 * counter + phase)
        value = None
        if row is not None:
            unit, present = row
            if present[offset // PACKET_BYTES]:
                value = observed_field(rule, int(unit[offset]))
        events.append(dict(counter=counter, slot=slot, phase=phase, cycle=index // 4, position=index % 4 + 1,
                           mode=f"{mode:02X}", rule=rule, expected=expected, peer_value=value))
    return events


def counts(events):
    checked = sum(event["peer_value"] is not None for event in events)
    matches = sum(event["expected"] == event["peer_value"] for event in events)
    return dict(predicted=len(events), checked=checked, matched=matches, mismatched=checked - matches,
                no_peer=len(events) - checked)


def by_position(events):
    return {position: counts([event for event in events if event["position"] == position]) for position in range(1, 5)}


def summarize(events, counters, modes):
    selected = [event for event in events if event["counter"] in counters]
    received_modes = sum(counter in counters for counter, slot in modes)
    by_rule = {}
    for rule in RULE_VALUES:
        subset = [event for event in selected if event["rule"] == rule]
        by_rule[rule] = counts(subset) | {"by_position": by_position(subset)}
    return dict(counters=len(counters), nominal_slots=60 * len(counters), received_modes=received_modes,
                total=counts(selected), by_position=by_position(selected), by_rule=by_rule)


def alternatives():
    rules = {}
    for name, predictions in RULE_VALUES.items():
        start, stop = FIELD_DEFINITIONS[name]["word_bits"]
        domain = range(1 << (stop - start))
        rules[name] = dict(word_bits=[start, stop], basis=FIELD_DEFINITIONS[name]["basis"],
                           excluded_given_prediction={expected: [v for v in domain if v != expected]
                                                      for expected in predictions})
    return rules


def score(source_path, peer_path, primary):
    if sha256((SCRIPTS / "evs_gsc_fields.py").read_bytes()).hexdigest() != PREDICTOR_SHA256:
        raise ValueError("field predictor differs from the sealed protocol")
    source = snapshot(source_path)
    source_counters = {tick // 3 for tick in source}
    modes, decisions = forecasts(source)
    sealed = sha256(json.dumps(decisions, separators=(",", ":")).encode("ascii")).hexdigest()

    peer = snapshot(peer_path)
    events = observe(decisions, peer)
    primary_counters = set() if primary is None else {primary}
    primary_summary = summarize(events, primary_counters, modes)
    primary_summary.update(counter=primary, source_assigned=primary in source_counters,
                           cases=[event for event in events if event["counter"] == primary])
    return dict(
        protocol_sha256=PROTOCOL_SHA256, predictor_sha256=PREDICTOR_SHA256,
        source_packets_sha256=sha256(source_path.read_bytes()).hexdigest(),
        peer_packets_sha256=sha256(peer_path.read_bytes()).hexdigest(),
        source_decisions_sha256=sealed,
        digest_basis="Compact JSON of ordered [counter, slot, mode, rule, expected] rows, without a newline.",
        peer_assigned_counters=len({tick // 3 for tick in peer}), rules=alternatives(),
        all_assigned_source=summarize(events, source_counters, modes), primary=primary_summary,
        mismatches=[event for event in events if event["peer_value"] is not None and
                    event["peer_value"] != event["expected"]],
    )


def primary_counter(value):
    if value.lower() == "none":
        return None
    try:
        counter = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("primary must be a uint32 counter or none") from error
    if not 0 <= counter <= 0xffffffff:
        raise argparse.ArgumentTypeError("primary counter is outside uint32")
    return counter


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="3205 kHz transport-only packets.npz")
    parser.add_argument("peer", type=Path, help="6140 kHz transport-only packets.npz")
    parser.add_argument("--primary", type=primary_counter, help="previously selected counter, or none (default)")
    parser.add_argument("--out", type=Path, help="write JSON here (default stdout)")
    args = parser.parse_args()
    result = json.dumps(score(args.source, args.peer, args.primary), indent=2, sort_keys=True) + "\n"
    if args.out:
        args.out.write_text(result)
    else:
        print(result, end="")


if __name__ == "__main__":
    main()
