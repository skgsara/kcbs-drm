"""Count RF word geometry on a sealed field recording and retain its incomplete control."""
import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
NOV = HERE.parents[1] / "nov28"
sys.path.insert(0, str(NOV / "packet-bit-repair"))
from score_field import prior_ids
from project_evs_group import project_group


def classify(row):
    mode, *body = [byte != "--" for byte in row["octets"].split()]
    present = sum(body)
    if present == 32:
        return "full_physical_word" if mode else "only_mode_missing"
    if present == 0:
        return "only_mode_received" if mode else "no_physical_octets"
    return "partial_payload_with_mode" if mode else "partial_payload_without_mode"


def measure(work, expected):
    ledger = (work / "forecasts.json").read_bytes()
    if sha256(ledger).hexdigest() != expected:
        raise ValueError("forecast digest differs from seal")
    forecast = json.loads(ledger)
    stage = work / "transport"
    packets = stage / "packets.npz"
    if sha256(packets.read_bytes()).hexdigest() != forecast["packet_archive_sha256"]:
        raise ValueError("packet archive differs from forecast ledger")
    origins = json.loads((stage / "provenance.json").read_bytes())
    first_rows = {}
    for key, sources in origins.items():
        counter = int(key.split(",")[0])
        row = min(index for _, index in sources)
        first_rows[counter] = min(row, first_rows.get(counter, row))
    old, last = prior_ids()
    previous = json.loads((NOV / "packet-bit-repair/field/group-evaluation.json").read_bytes())
    history = old | last | set(previous["combined_exposure"]["assigned_counters"])
    if len(history) != 15074:
        raise ValueError("previously seen counter inventory changed")
    selected = forecast["primary"]["counter"] if forecast["primary"] else None
    totals = {str(p): Counter() for p in range(1, 5)}
    primary = partial = None
    for counter in sorted(forecast["assigned_counters"], key=lambda c: (first_rows[c], c)):
        projection = project_group(packets, counter, packets=True)
        by_pos = {str(p): Counter() for p in range(1, 5)}
        for row in projection["slots"]:
            pos = str(row["position"])
            kind = classify(row)
            totals[pos][kind] += 1
            by_pos[pos][kind] += 1
        if counter == selected or (partial is None and projection["physically_complete_slots"] < 60):
            receipt = dict(counter=counter, first_assigned_row=first_rows[counter], by_position=by_pos,
                           directly_received_bits=projection["confirmed_direct_bits"],
                           physically_complete_slots=projection["physically_complete_slots"],
                           full_clear_words=projection["full_clear_words"])
            if counter == selected:
                primary = receipt
            if projection["physically_complete_slots"] < 60 and partial is None:
                partial = receipt
                partial["slots"] = projection["slots"]
    return dict(forecasts_sha256=expected, native_transport=forecast["native_transport"],
                native_complete_groups=len(forecast["complete_native_groups"]), prior_inventory=len(history),
                all_assigned_counters=sorted(first_rows), overlap=sorted(history.intersection(first_rows)),
                groups_with_packet_receipts=len(forecast["assigned_counters"]), word_counts_by_position=totals,
                primary=primary, first_incomplete_group=partial)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("work", type=Path)
    parser.add_argument("--seal", required=True)
    args = parser.parse_args()
    print(json.dumps(measure(args.work, args.seal), indent=2))
