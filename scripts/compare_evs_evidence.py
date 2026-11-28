"""Compare a saved --field-checks projection with a slot-addressed EVS reference."""
import argparse
from hashlib import sha256
import json
from pathlib import Path

from check_evs_origin import unique_fields
from compare_evs_group import group_words, valid_integer
from evs_evidence import bit_evidence


SLOT_OUTCOMES = ("direct_agreement", "direct_disagreement", "reference_only",
                 "reference_erasure", "outside_extent")
RULE_OUTCOMES = ("match", "mismatch", "unrestricted", "contradiction", "quarantined",
                 "reference_only", "reference_erasure", "outside_extent")
COORDINATES = ("slot", "counter", "phase", "cycle", "position")


def compare_slot(slot, word):
    differing = []
    compared = 0
    if word is None:
        status = "outside_extent"
    elif not word:
        status = "reference_erasure"
    else:
        for octet, token in enumerate(slot["octets"].split()):
            if token in ("??", "--"):
                continue
            compared += 8
            different = int(token, 16) ^ word[octet]
            differing.extend(octet * 8 + bit for bit in range(8) if different & (0x80 >> bit))
        if not compared:
            status = "reference_only"
        else:
            status = "direct_disagreement" if differing else "direct_agreement"
    return dict(status=status, compared_direct_bits=compared, matching_direct_bits=compared - len(differing),
                differing_direct_bits=len(differing), differing_word_bit_offsets=differing)


def word_field(word, bounds):
    """Extract an MSB-first field with half-open bit bounds."""
    if not word:
        return None
    start, end = bounds
    return (int.from_bytes(word, "big") >> (264 - end)) & ((1 << (end - start)) - 1)


def compare_event(event, slot, words, receipts):
    target = word_field(words[slot], event["word_bits"])
    inputs = []
    dependencies = {slot}
    for observed in event["inputs"]:
        i = observed["slot"]
        dependencies.add(i)
        value = word_field(words[i], observed["word_bits"])
        inputs.append({**observed, "reference_value": value,
                       "agrees_with_reference": None if value is None else value == observed["observed"]})
    conflicts = sorted(i for i in dependencies if receipts[i]["status"] == "direct_disagreement")
    allowed = event["allowed_values"]
    status = receipts[slot]["status"]
    if conflicts:
        outcome = "quarantined"
    elif status != "direct_agreement":
        outcome = status
    elif not allowed:
        outcome = "contradiction"
    elif event["excluded_value_count"] == 0:
        outcome = "unrestricted"
    else:
        outcome = "match" if target in allowed else "mismatch"
    return dict(section=event["section"], check=event["check"], kind=event["kind"],
                word_bits=event["word_bits"], allowed_values=allowed,
                target_receipt=event["observation"], projection_value=event["observed"],
                projection_outcome=event["source_outcome"],
                reference_value=target, outcome=outcome, conflicting_slots=conflicts, inputs=inputs)


def empty_counts():
    return {"slots": dict.fromkeys(SLOT_OUTCOMES, 0), "compared_direct_bits": 0, "matching_direct_bits": 0,
            "differing_direct_bits": 0, "predicates": dict.fromkeys(RULE_OUTCOMES, 0)}


def compare_evidence(projection_path, reference_path, *, start):
    projection_path, reference_path = Path(projection_path), Path(reference_path)
    raw = projection_path.read_bytes()
    projection = json.loads(raw, object_pairs_hook=unique_fields)
    if (not isinstance(projection, dict) or projection.get("format") not in
            ("kcbs-evs-projection-v1", "kcbs-evs-packet-projection-v1")
            or not valid_integer(projection.get("counter"), 0, 0xffffffff)):
        raise ValueError("expected a saved EVS group projection with a uint32 counter")
    evidence = bit_evidence(projection)
    counter = evidence["counter"]
    before = reference_path.stat()
    words = group_words(reference_path, start, counter)
    digest = sha256()
    with reference_path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    after = reference_path.stat()
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
            after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns):
        raise ValueError("reference file changed during comparison")

    slots = evidence["slots"]
    receipts = [compare_slot(slot, word) for slot, word in zip(slots, words, strict=True)]
    total = empty_counts()
    positions = {str(p): empty_counts() for p in range(1, 5)}
    rules = {}
    results = []
    for slot, receipt in zip(slots, receipts, strict=True):
        events = [compare_event(e, slot["slot"], words, receipts) for e in slot["events"]]
        for counts in (total, positions[str(slot["position"])]):
            counts["slots"][receipt["status"]] += 1
            for key in ("compared_direct_bits", "matching_direct_bits", "differing_direct_bits"):
                counts[key] += receipt[key]
            for event in events:
                counts["predicates"][event["outcome"]] += 1
        for event in events:
            counts = rules.setdefault(event["check"], dict.fromkeys(RULE_OUTCOMES, 0))
            counts[event["outcome"]] += 1
        coords = {key: slot[key] for key in COORDINATES}
        results.append({**coords, "receipt": slot["receipt"], "available_direct_bits": slot["direct_bits"],
                        **receipt, "predicates": events})
    return dict(format="kcbs-evs-reference-evidence-v1", counter=counter,
                projection_sha256=sha256(raw).hexdigest(), reference_sha256=digest.hexdigest(),
                reference_start=list(start), total=total, by_position=positions, by_rule=rules, slots=results,
                scope="Direct agreement measures the supplied octets at the stated coordinates. "
                      "Reference-only slots have no direct coordinate witness. A conflicting directly "
                      "observed octet quarantines every predicate depending on that slot. "
                      "Unrestricted and empty allowed sets are counted separately. "
                      "Independent broadcast accuracy requires separate source provenance.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("projection", type=Path, help="saved JSON from project_evs_group.py --field-checks")
    parser.add_argument("reference", type=Path, help="G.192 or mono EVS storage file, optionally gzipped")
    parser.add_argument("--start", required=True, type=int, nargs=4,
                        metavar=("COUNTER", "PHASE", "CYCLE", "POSITION"),
                        help="receiver coordinates of the first slot in the reference")
    args = parser.parse_args()
    try:
        result = compare_evidence(args.projection, args.reference, start=args.start)
    except (OSError, ValueError, KeyError, TypeError, IndexError) as error:
        parser.exit(2, f"{parser.prog}: {error}\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
