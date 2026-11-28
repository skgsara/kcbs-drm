"""Check the directly carried HQ predecessor flag at adjacent EVS group boundaries."""
import argparse
from collections import Counter
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
from zipfile import BadZipFile

from compare_evs_group import valid_integer
from evs_core_history import previous_core
from project_evs_group import checked_units
from received_evs_packets import PACKET_BYTES, read_packet_snapshot
from render_continuous import MODE_POSITIONS


ENDPOINTS = {0: MODE_POSITIONS[0], 2: MODE_POSITIONS[-1]}


def endpoints(raw, packets):
    """Return counters represented in this archive and just the witnessed endpoint modes."""
    stream = BytesIO(raw)
    represented, modes = set(), {}
    if packets:
        ticks, units, flags = read_packet_snapshot(stream)
        for tick, unit, present in zip(ticks, units, flags, strict=True):
            c, phase = divmod(int(tick), 3)
            represented.add(c)
            offset = ENDPOINTS.get(phase)
            if offset is not None and present[offset // PACKET_BYTES]:
                modes[c, phase] = int(unit[offset])
    else:
        for c, phase, unit in checked_units(stream):
            represented.add(c)
            if phase in ENDPOINTS:
                modes[c, phase] = unit[ENDPOINTS[phase]]
    return represented, modes


def predict(previous, current_top_six):
    """Select and predict using previous signalling and current word bits [0,6) only."""
    if current_top_six is None:
        return None, "current_mode_unavailable"
    if previous is None:
        return None, "previous_mode_unavailable"
    prior = previous_core(previous)
    if prior is None:
        return None, "previous_signalling_index_outside_scope"
    if current_top_six >> 1 not in (29, 30, 31) or current_top_six & 1:
        return None, "current_mode_is_not_hq"
    return int(prior == "ACELP"), None


def check_boundaries(path, *, counter=None, packets=False):
    if counter is not None and not valid_integer(counter, 0, 0xffffffff):
        raise ValueError("counter must be an unsigned 32-bit integer")
    raw = Path(path).read_bytes()
    counters, modes = endpoints(raw, packets)
    targets = sorted(counters) if counter is None else [int(counter)]
    rows = []
    for c in targets:
        previous = modes.get((c - 1, 2)) if c else None
        current = modes.get((c, 0))
        top = None if current is None else current >> 2
        if c == 0:
            predicted, reason = None, "counter_zero_has_no_predecessor"
        else:
            predicted, reason = predict(previous, top)
        rows.append(dict(counter=c, left=[c - 1, 2, 4, 4] if c else None, right=[c, 0, 0, 1],
                         previous_mode_top_five=None if previous is None else previous >> 3, current_mode_top_six=top,
                         predicted=predicted, reason=reason, allowed_values=None if reason else [predicted],
                         rejected_values=None if reason else [1 - predicted]))

    selection = [(r["counter"], r["predicted"]) for r in rows if r["reason"] is None]
    commitment = sha256(json.dumps(selection, separators=(",", ":")).encode()).hexdigest()
    counts = dict.fromkeys(("match", "mismatch", "abstain"), 0)
    reasons = Counter()
    for row in rows:
        if row["reason"] is None:
            observed = (modes[row["counter"], 0] >> 1) & 1
            row.update(observed=observed, outcome="match" if observed == row["predicted"] else "mismatch")
        else:
            row.update(observed=None, outcome="abstain")
            reasons[row["reason"]] += 1
        counts[row["outcome"]] += 1
    return dict(format="kcbs-evs-hq-group-boundary-v1", input_sha256=sha256(raw).hexdigest(),
                input_kind="packet_receipts" if packets else "complete_data_units",
                coordinates=["counter", "phase", "cycle", "position"], target_word_bit=6,
                selection_sha256=commitment, targets=len(rows), eligible=len(selection),
                counts=counts, abstention_reasons=dict(reasons), rows=rows,
                basis="Stock 13.2 kb/s HQ coding with continuous encoder history across adjacent groups. "
                      "Each right endpoint is P1 slot 0. Its predecessor is P4 slot 59 at counter minus one. "
                      "Both mode octets must have receipts in the supplied archive. Physical source continuity "
                      "depends on the archive provenance. Selection withholds current bits 6 and 7.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument("data_units", nargs="?", type=Path, help="CRC-checked data_units.npz")
    src.add_argument("--packets", type=Path, help="packets.npz with packet-level CRC receipt flags")
    parser.add_argument("--counter", type=int, help="check only this right-hand counter")
    args = parser.parse_args()
    try:
        result = check_boundaries(args.packets or args.data_units, counter=args.counter, packets=args.packets is not None)
    except (OSError, ValueError, EOFError, BadZipFile) as error:
        parser.exit(2, f"{parser.prog}: {error}\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
