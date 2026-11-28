"""Tabulate the historical P2 labels applicable to the saved 43288730 field report."""
from binascii import crc_hqx
from collections import Counter
import csv
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
HISTORY = HERE.parent / "swb-transition" / "p2"


def suffix_class(hex_octet):
    """The historical fixture groups octets ending in six or more zeros together."""
    octet = int(hex_octet, 16)
    zeros = (octet & -octet).bit_length() - 1 if octet else 8
    return min(zeros, 6)


def witness_ids(row):
    starts = {token.rsplit("/", 1)[0] for token in row["record_counter_phase_byte_offsets"].split("|")}
    return {f"{row['capture']}/{start}" for start in starts}


def body_signature(record):
    """Equal bodies must have the same length and header-neutral CRC."""
    length = record["checked_bytes"] - 2
    header = bytes.fromhex(record["header"])
    header_contribution = crc_hqx(header + bytes(length), 0)
    return length, int(record["crc16"], 16) ^ header_contribution


def summarize(rows, witnesses):
    occurrences = {key for row in rows for key in witness_ids(row)}
    records = [witnesses[key] for key in occurrences]
    # Distinct signatures lower-bound the number of bodies. Distinct full records
    # upper-bound it. Report an exact body count only when the bounds coincide.
    lower = len({body_signature(record) for record in records})
    upper = len({record["sha256"] for record in records})
    labels = Counter(format(int(row["observed_pair_decimal"]), "02b") for row in rows)
    matches = sum(row["observed_pair_decimal"] == row["allowed_pairs_decimal"] for row in rows)
    return {
        "frames": len(rows), "matching_pairs": matches, "observed_pairs": dict(sorted(labels.items())),
        "counters": len({row["counter"] for row in rows}), "text_record_occurrences": len(occurrences),
        "distinct_full_records": upper, "distinct_body_lower_bound": lower,
        "distinct_bodies": lower if lower == upper else None,
    }


def main():
    with (HISTORY / "fixture.csv").open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    if any(suffix_class(row["p31"]) != int(row["z"]) for row in rows):
        raise ValueError("recorded trailing-zero count differs from the received byte")
    witnesses = json.loads((HISTORY / "witnesses.json").read_bytes())
    target = json.loads((HERE / "target-evidence.json").read_bytes())
    singletons = [row for row in rows if row["allowed_pairs_decimal"] in ("0", "1", "2", "3")]
    classes = {}
    for prediction in sorted({row["allowed_pairs_decimal"] for row in singletons}):
        cohort = [row for row in singletons if row["allowed_pairs_decimal"] == prediction]
        classes[format(int(prediction), "02b")] = summarize(cohort, witnesses)

    slots = []
    for slot in target["slots"]:
        if slot["position"] != 2:
            continue
        for event in slot["events"]:
            if event["check"] != "transition_tag" or len(event["allowed_values"]) != 1:
                continue
            octets = slot["octets"].split()
            mode, tail = octets[0].lower(), octets[32].lower()
            same_zeros = [row for row in rows if row["mode"].lower() == mode and
                          int(row["z"]) == suffix_class(tail)]
            same_octet = [row for row in rows if row["mode"].lower() == mode and row["p31"].lower() == tail]
            expected = event["allowed_values"][0]
            if any(row["allowed_pairs_decimal"] != str(expected) for row in [*same_zeros, *same_octet]):
                raise ValueError(f"historical rule and target rule differ at slot {slot['slot']}")
            slots.append({
                "slot": slot["slot"], "mode": mode, "last_octet": tail,
                "conditional_pair": format(expected, "02b"),
                "target_observation": event["observation"],
                "same_mode_and_trailing_zeros": summarize(same_zeros, witnesses),
                "same_mode_and_entire_last_octet": summarize(same_octet, witnesses),
            })
    print(json.dumps({"target": target["counter"], "historical_singletons": summarize(singletons, witnesses),
                      "by_predicted_pair": classes, "target_p2_slots": slots}, indent=2))


if __name__ == "__main__":
    main()
