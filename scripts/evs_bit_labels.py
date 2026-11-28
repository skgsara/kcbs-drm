"""Compare explicitly supplied bit labels to the direct observations and published field predicates."""
import csv
from collections import Counter, defaultdict
from hashlib import sha256
from io import StringIO
import json
from pathlib import Path

from check_evs_origin import unique_fields
from evs_core_history import COORDINATES
from evs_evidence import bit_evidence, field_value


COLUMNS = ("counter", "phase", "cycle", "position", "first_bit", "bits")
COORDINATE_COUNTS = ("no_labels", "coordinates_only", "direct_agreement", "direct_disagreement", "conflicting_labels")
COUNT_FIELDS = ("slots", "slots_with_labels", "supplied_bit_observations", "labelled_bits", "unambiguous_labelled_bits",
                "conflicting_labelled_bits", "direct_compared_bits", "direct_match_bits", "direct_mismatch_bits",
                "direct_conflicted_bits", "fixed_bit_comparisons", "fixed_bit_matches", "fixed_bit_mismatches",
                "fixed_bit_quarantined", "fixed_bit_conflicts", "fields_with_conflicting_labels",
                "fields_partially_labelled", "fields_fully_labelled", "field_comparisons",
                "field_matches", "field_mismatches", "rule_events_quarantined")


def read_labels(raw, selected_counter):
    reader = csv.DictReader(StringIO(raw.decode("utf-8-sig"), newline=""), strict=True)
    names = reader.fieldnames or []
    if not set(COLUMNS).issubset(names) or len(names) != len(set(names)) or any(not n.strip() for n in names):
        raise ValueError("expected distinct CSV column names including " + ", ".join(COLUMNS))
    observations = defaultdict(lambda: defaultdict(Counter))
    witness_ids = set()
    rows = selected = unattributed = 0
    for row in reader:
        rows += 1
        try:
            if None in row or any(row[name] is None for name in COLUMNS):
                raise ValueError("row has unexpected column count")
            coords = [row[name].strip() for name in COLUMNS[:-1]]
            if not all(s.isascii() and s.isdecimal() for s in coords):
                raise ValueError("expected decimal integer coordinates")
            c, phase, cycle, pos, first = map(int, coords)
            bits = row["bits"].strip()
            if not (0 <= c <= 0xffffffff and phase < 3 and cycle < 5 and 1 <= pos <= 4):
                raise ValueError("invalid counter, phase, cycle or position")
            if not bits or set(bits) - {"0", "1"} or first + len(bits) > 264:
                raise ValueError("expected a nonempty binary string within word bits [0,264)")
        except ValueError as exc:
            raise ValueError(f"CSV line {reader.line_num}: {exc}") from exc
        if c == selected_counter:
            selected += 1
            witness = (row.get("witness") or "").strip()
            if witness:
                witness_ids.add(witness)
            else:
                unattributed += 1
            slot = phase * 20 + cycle * 4 + pos - 1
            for bit, value in enumerate(bits, first):
                observations[slot][bit][int(value), witness] += 1
    return observations, dict(rows_read=rows, rows_selected=selected, unattributed_selected_rows=unattributed,
                              witness_ids=sorted(witness_ids), distinct_witness_ids=len(witness_ids))


def labelled_slot(slot, claims):
    tokens = slot["octets"].split()
    labels = {}
    for bit, entries in sorted(claims.items()):
        target_receipt, direct = field_value(tokens, bit, bit + 1)
        values = sorted({value for value, _ in entries})
        rows = []
        for value in values:
            occurrences = {w: n for (v, w), n in entries.items() if v == value}
            witnesses = {w: occurrences[w] for w in sorted(occurrences) if w}
            rows.append(dict(value=value, count=sum(occurrences.values()), witness_ids=list(witnesses),
                             witness_occurrences=witnesses, unattributed_count=occurrences.get("", 0),
                             matches_direct=None if direct is None else value == direct))
        if direct is None:
            relation = "not_direct"
        elif len(values) > 1:
            relation = "conflict"
        else:
            relation = "match" if values[0] == direct else "mismatch"
        labels[str(bit)] = dict(values=values, observations=rows, receipt=target_receipt, direct_value=direct,
                                direct_relation=relation)
    relations = {label["direct_relation"] for label in labels.values()}
    if "conflict" in relations:
        status = "conflicting_labels"
    elif "mismatch" in relations:
        status = "direct_disagreement"
    elif "match" in relations:
        status = "direct_agreement"
    else:
        status = "coordinates_only" if labels else "no_labels"
    disputed = [int(bit) for bit, label in labels.items() if len(label["values"]) > 1]
    return {key: slot[key] for key in COORDINATES} | dict(
        receipt=slot["receipt"], labels=labels, conflicting_label_bits=disputed, coordinate_agreement=status,
        receiver_word_erased=slot["word_erased"], predicates=[])


def compare_predicate(event, row, conflicts):
    start, end = event["word_bits"]
    labels = row["labels"]
    target = [labels[str(i)]["values"] for i in range(start, end) if str(i) in labels]
    if not target:
        coverage = "none"
    elif len(target) < end - start:
        coverage = "partial"
    else:
        coverage = "complete"
    competing = sum(len(values) > 1 for values in target)
    field = membership = None
    if coverage == "complete" and not competing:
        field = int("".join(str(values[0]) for values in target), 2)
        if not event["allowed_values"]:
            membership = "contradiction"
        elif event["excluded_value_count"] == 0:
            membership = "unrestricted"
        else:
            membership = "match" if field in event["allowed_values"] else "mismatch"
    deps = {row["slot"], *(input_row["slot"] for input_row in event["inputs"])}
    blocked = sorted(conflicts.intersection(deps))
    fixed = {}
    for bit, predicted in event["fixed_bits"].items():
        values = labels.get(bit, {}).get("values", [])
        label = values[0] if len(values) == 1 else None
        if label is not None:
            relation = "match" if label == predicted else "mismatch"
        else:
            relation = "conflict" if values else "no_label"
        fixed[bit] = dict(predicted=predicted, label_value=label, relation=relation,
                          outcome="quarantined" if blocked and values else relation)
    if blocked:
        outcome = "quarantined"
    elif competing:
        outcome = "conflicting_labels"
    else:
        outcome = membership or coverage
    return dict(section=event["section"], check=event["check"], kind=event["kind"], word_bits=[start, end],
                allowed_values=event["allowed_values"], target_receipt=event["observation"],
                projection_outcome=event["source_outcome"], inputs=event["inputs"],
                field_coverage=coverage, labelled_target_bits=len(target), conflicting_target_bits=competing,
                label_value=field, membership=membership, fixed_bits=fixed, quarantined_slots=blocked,
                field_outcome=outcome)


def summary(slots):
    counts = dict.fromkeys(COUNT_FIELDS, 0)
    coord_counts = dict.fromkeys(COORDINATE_COUNTS, 0)
    for row in slots:
        counts["slots"] += 1
        coord_counts[row["coordinate_agreement"]] += 1
        counts["slots_with_labels"] += bool(row["labels"])
        for label in row["labels"].values():
            counts["supplied_bit_observations"] += sum(v["count"] for v in label["observations"])
            counts["labelled_bits"] += 1
            counts["conflicting_labelled_bits"] += len(label["values"]) > 1
            counts["direct_conflicted_bits"] += label["direct_relation"] == "conflict"
            counts["direct_match_bits"] += label["direct_relation"] == "match"
            counts["direct_mismatch_bits"] += label["direct_relation"] == "mismatch"
        for event in row["predicates"]:
            counts["fields_partially_labelled"] += event["field_coverage"] == "partial"
            counts["fields_fully_labelled"] += event["field_coverage"] == "complete"
            counts["fields_with_conflicting_labels"] += event["conflicting_target_bits"] > 0
            blocked = bool(event["quarantined_slots"])
            counts["rule_events_quarantined"] += blocked
            for bit in event["fixed_bits"].values():
                counts["fixed_bit_quarantined"] += bit["outcome"] == "quarantined"
                counts["fixed_bit_conflicts"] += bit["relation"] == "conflict"
                counts["fixed_bit_matches"] += bit["outcome"] == "match"
                counts["fixed_bit_mismatches"] += bit["outcome"] == "mismatch"
            counts["field_matches"] += event["field_outcome"] == "match"
            counts["field_mismatches"] += event["field_outcome"] == "mismatch"
    counts["unambiguous_labelled_bits"] = counts["labelled_bits"] - counts["conflicting_labelled_bits"]
    counts["direct_compared_bits"] = counts["direct_match_bits"] + counts["direct_mismatch_bits"]
    counts["fixed_bit_comparisons"] = counts["fixed_bit_matches"] + counts["fixed_bit_mismatches"]
    counts["field_comparisons"] = counts["field_matches"] + counts["field_mismatches"]
    return counts | {"coordinate_agreement": coord_counts}


def compare_bit_labels(projection_path, labels_path):
    """Evaluate only supplied observations. No absent bit or reference word is constructed."""
    projected = Path(projection_path).read_bytes()
    label_bytes = Path(labels_path).read_bytes()
    projection = json.loads(projected, object_pairs_hook=unique_fields)
    evidence = bit_evidence(projection)
    counter = evidence["counter"]
    if type(counter) is not int or not 0 <= counter <= 0xffffffff:
        raise ValueError("expected a uint32 projection counter")
    try:
        labels, ledger = read_labels(label_bytes, counter)
    except csv.Error as exc:
        raise ValueError(f"invalid bit label CSV: {exc}") from exc
    slots = [labelled_slot(s, labels.get(s["slot"], {})) for s in evidence["slots"]]
    conflicts = {s["slot"] for s in slots if s["coordinate_agreement"] in ("direct_disagreement", "conflicting_labels")}
    for slot, source in zip(slots, evidence["slots"], strict=True):
        slot["predicates"] = [compare_predicate(e, slot, conflicts) for e in source["events"]]
    return dict(format="kcbs-evs-bit-label-comparison-v1", counter=counter, projection_sha256=sha256(projected).hexdigest(),
                labels_sha256=sha256(label_bytes).hexdigest(), ledger=ledger, total=summary(slots),
                by_position={str(p): summary(slots[p-1::4]) for p in range(1, 5)}, slots=slots,
                receiver_word_erasures=evidence["total"]["word_erasures"], new_receiver_words=0,
                scope="Coordinates without overlapping direct bits rely on the supplied ledger alignment. "
                      "Direct comparisons count unique coordinates with unambiguous labels. "
                      "Fixed-bit and field comparisons count predicate events and may overlap. "
                      "Direct anchor disagreements quarantine dependent predicates. A disputed hidden bit "
                      "withholds that bit and membership of fields containing it. Other labels remain usable. "
                      "Witness IDs record attribution and may share a source.")
