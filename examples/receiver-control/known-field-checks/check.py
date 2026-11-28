"""Seal two existing EVS field rules from received packets, or score a previously sealed forecast."""
import argparse
from hashlib import sha256
from io import BytesIO
import gzip
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
CASE = HERE.parent
sys.path[:0] = [str(CASE), str(CASE.parents[1] / "scripts")]
from evs_core_history import core_history
from evs_transition_tags import transition_tags
from received_evs_packets import PACKET_BYTES, read_packet_snapshot
from render_continuous import MODE_POSITIONS, PACKET_STARTS
from verify import FIRST, GROUPS, coordinate

RULES = ("tcx_previous_core", "transition_tag")
WITNESS = (16909074, 37)
FORMAT = "clear-synthetic-iq-two-rule-forecast-v1"


def checked(path, expected):
    raw = path.read_bytes()
    if sha256(raw).hexdigest() != expected:
        raise ValueError(f"SHA-256 mismatch for {path.name}")
    return raw


def gate_group(rows):
    history = core_history(rows)["slots"]
    transitions = {r["slot"]: r["allowed_high_pairs"] for r in transition_tags(rows)["slots"]}
    result = []
    for row, previous in zip(rows, history, strict=True):
        slot = row["slot"]
        mode = row["mode"]
        tcx = None
        reason = None
        if mode is None:
            reason = "current_mode_unavailable"
        elif mode >> 3 < 29 or not (mode & 4):
            reason = "current_mode_outside_tcx20"
        elif previous["outcome"] == "tcx_conditional":
            tcx = [previous["predicted"]]
        else:
            reason = previous["reason"]
        pair = transitions.get(slot)
        pair_reason = None
        if mode is None:
            pair_reason = "current_mode_unavailable"
        elif mode >> 3 != 12:
            pair_reason = "current_mode_outside_swb_transition"
        elif pair is None:
            pair_reason = "ending_octet_unavailable"
        result.append({k: row[k] for k in ("counter", "phase", "cycle", "position", "slot",
                                           "mode", "last_octet", "wire_word_complete")} |
                      dict(tcx_previous_core=tcx, tcx_abstention=reason,
                           transition_tag=pair, transition_abstention=pair_reason))
    return result


def mode_and_tail(counter, index, receipts):
    coords = coordinate((counter - FIRST) * 60 + index)
    coords["slot"] = index
    phase = coords["phase"]
    unit, ordinals = receipts.get(3 * counter + phase, (None, ()))
    mode_offset, start = MODE_POSITIONS[index % 20], PACKET_STARTS[index % 20]
    mode_q = mode_offset // PACKET_BYTES
    tail_q = (start + 31) // PACKET_BYTES
    mode = int(unit[mode_offset]) if mode_q in ordinals else None
    tail = None
    if mode is not None and mode >> 3 == 12 and tail_q in ordinals:
        tail = int(unit[start + 31])
    complete = all(q in ordinals for q in {mode_q, start // PACKET_BYTES, tail_q})
    # Existing rules accept projection rows. They receive only their declared inputs.
    tokens = ["--"] * 33
    if mode is not None:
        tokens[0] = f"{mode:02x}"
    if tail is not None:
        tokens[-1] = f"{tail:02x}"
    return dict(**coords, receipt="received_packets" if ordinals else "missing_packets",
                mode=mode, last_octet=tail, wire_word_complete=complete, octets=" ".join(tokens))


def gap_control(rows, forecast, receipts):
    counter, slot = WITNESS
    predecessor = rows[slot - 1]
    offset = MODE_POSITIONS[(slot - 1) % 20]
    tick = 3 * counter + predecessor["phase"]
    hidden = list(rows)
    tokens = predecessor["octets"].split()
    tokens[0] = "--"
    hidden[slot - 1] = dict(predecessor, mode=None, octets=" ".join(tokens))
    withheld = gate_group(hidden)[slot]
    if (predecessor["wire_word_complete"] or forecast[slot]["tcx_previous_core"] != [1]
            or withheld["tcx_previous_core"] is not None or withheld["tcx_abstention"] != "previous_mode_unavailable"):
        raise ValueError("known partial-word predecessor control failed")
    return dict(counter=counter, slot=slot, predecessor_slot=slot - 1, predecessor_mode=predecessor["mode"],
                predecessor_mode_du_offset=offset, predecessor_mode_packet=offset // PACKET_BYTES,
                received_packet_ordinals=receipts[tick][1], predecessor_wire_word_complete=False,
                target_mode=rows[slot]["mode"], before=forecast[slot]["tcx_previous_core"],
                after=withheld["tcx_previous_core"], after_reason=withheld["tcx_abstention"])


def forecast(path):
    source = json.loads((CASE / "result/receiver.json").read_bytes())["source_and_receiver_sha256"]
    raw = checked(path, source["packets"])
    ticks, units, flags = read_packet_snapshot(BytesIO(raw))
    receipts = {int(t): (u, [i for i, yes in enumerate(f) if yes]) for t, u, f in zip(ticks, units, flags, strict=True)}
    groups = []
    for counter in range(FIRST, FIRST + GROUPS):
        rows = [mode_and_tail(counter, i, receipts) for i in range(60)]
        slots = gate_group(rows)
        groups.append(dict(counter=counter, slots=slots))
        if counter == WITNESS[0]:
            control = gap_control(rows, slots, receipts)
    return dict(format=FORMAT, packets_sha256=source["packets"], iq_sha256=source["source_iq"],
                msc_sha256=source["msc"], first_counter=FIRST, groups=groups, predecessor_control=control)


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    sub = cli.add_subparsers(dest="command", required=True)
    f = sub.add_parser("forecast", help="seal all 40 groups from the stock receiver packet snapshot")
    f.add_argument("packets", type=Path)
    f.add_argument("out", type=Path, help="new deterministic gzip JSON ledger")
    s = sub.add_parser("score", help="check a sealed ledger against the unmodified stock sender")
    s.add_argument("ledger", type=Path)
    s.add_argument("sha256")
    s.add_argument("sender", type=Path)
    args = cli.parse_args()
    try:
        if args.command == "forecast":
            encoded = (json.dumps(forecast(args.packets), sort_keys=True, separators=(",", ":")) + "\n").encode()
            with args.out.open("xb") as stream:
                with gzip.GzipFile(filename="", mode="wb", fileobj=stream, mtime=0) as out:
                    out.write(encoded)
            print(sha256(args.out.read_bytes()).hexdigest())
        else:
            from scoring import score
            ledger = json.loads(gzip.decompress(checked(args.ledger, args.sha256)))
            if ledger["format"] != FORMAT:
                raise ValueError("expected a two-rule forecast from this fixture")
            print(json.dumps(score(ledger, args.sha256, args.sender), indent=2, allow_nan=False))
    except (OSError, ValueError, KeyError) as error:
        cli.exit(2, f"{cli.prog}: {error}\n")


if __name__ == "__main__":
    main()
