"""Compare the two sealed field domains with independently saved clear sender labels."""
from collections import Counter
import gzip
from hashlib import sha256
import json

from check import CASE, FIRST, GROUPS, RULES, checked
from evs_core_history import previous_core
from evs_transition_tags import allowed_pairs
from verify import coordinate, read_g192


def counters(width):
    return dict(slots=0, abstentions=Counter(), outside_shifted_group=0, compared=0,
                allowed_set_sizes={str(n): 0 for n in range(2 ** width + 1)},
                actual_values={str(v): 0 for v in range(2 ** width)},
                allowed_matches=0, restrictive_cases=0, restrictive_matches=0,
                singleton_cases=0, singleton_exact=0, constant_exact=0, constant_exact_restrictive=0,
                constant_admitted_restrictive=0, disallowed_alternatives=0,
                fixed_bits={str(8 + i): dict(compared=0, matched=0, baseline_matched=0,
                                             actual_zeros=0, actual_ones=0) for i in range(width)})


def tally(counts, field, row, truth, width):
    counts["slots"] += 1
    domain = row[field]
    if domain is None:
        reason = row["tcx_abstention" if field == RULES[0] else "transition_abstention"]
        counts["abstentions"][reason] += 1
        return
    if truth is None:
        counts["outside_shifted_group"] += 1
        return
    value = truth[1] >> (8 - width)
    counts["compared"] += 1
    counts["actual_values"][str(value)] += 1
    counts["allowed_set_sizes"][str(len(domain))] += 1
    counts["allowed_matches"] += value in domain
    counts["constant_exact"] += value == 1  # TCX b8 = 1, transition b8:b9 = 01.
    if len(domain) < 2 ** width:
        counts["restrictive_cases"] += 1
        counts["restrictive_matches"] += value in domain
        counts["constant_exact_restrictive"] += value == 1
        counts["constant_admitted_restrictive"] += 1 in domain
    if len(domain) == 1:
        counts["singleton_cases"] += 1
        counts["singleton_exact"] += value in domain
    counts["disallowed_alternatives"] += sum(v not in domain for v in range(2 ** width) if v != value)
    for i in range(width):
        shift = width - i - 1
        bits = {(v >> shift) & 1 for v in domain}
        if len(bits) == 1:
            actual = (value >> shift) & 1
            summary = counts["fixed_bits"][str(8 + i)]
            summary["compared"] += 1
            summary["matched"] += actual in bits
            summary["baseline_matched"] += actual == ((1 >> shift) & 1)
            summary["actual_ones" if actual else "actual_zeros"] += 1


def evaluate(rows, sender, offset, *, by_position=False):
    result = {}
    for name, width in zip(RULES, (1, 2), strict=True):
        overall = counters(width)
        positions = {str(p): counters(width) for p in range(1, 5)}
        for i, row in enumerate(rows):
            truth = sender[i + offset] if 0 <= row["slot"] + offset < 60 else None
            tally(overall, name, row, truth, width)
            if by_position:
                tally(positions[str(row["position"])], name, row, truth, width)
        result[name] = dict(total=overall, by_position=positions) if by_position else overall
    return result


def complete_sender_opportunities(rows, words):
    """Diagnose receiver abstentions using sender truth only after the seal."""
    result = {name: dict(sender_eligible=0, receiver_eligible=0, receiver_missing=Counter()) for name in RULES}
    for i, (row, word) in enumerate(zip(rows, words, strict=True)):
        mode = word[0]
        eligible = {RULES[0]: (row["slot"] > 0 and mode >> 3 >= 29 and bool(mode & 4)
                               and previous_core(words[i - 1][0]) is not None),
                    RULES[1]: allowed_pairs(mode, word[-1]) is not None}
        for field, yes in eligible.items():
            if row[field] is not None and not yes:
                raise ValueError("receiver marked an ineligible sender slot")
            if not yes:
                continue
            totals = result[field]
            totals["sender_eligible"] += 1
            if row[field] is not None:
                totals["receiver_eligible"] += 1
            else:
                reason = row["tcx_abstention" if field == RULES[0] else "transition_abstention"]
                totals["receiver_missing"][reason] += 1
    return result


def score(ledger, ledger_sha, sender_path):
    groups = ledger["groups"]
    if [g["counter"] for g in groups] != list(range(FIRST, FIRST + GROUPS)):
        raise ValueError("ledger group extent differs from the fixture")
    rows = []
    for group in groups:
        if len(group["slots"]) != 60:
            raise ValueError("expected sixty slots per group")
        for slot, row in enumerate(group["slots"]):
            coords = coordinate(len(rows))
            coords["slot"] = slot
            if any(row[k] != v for k, v in coords.items()):
                raise ValueError("ledger slot coordinates differ from the fixture")
            rows.append(row)
    sender_info = json.loads((CASE / "fixture/sender.json").read_bytes())["files"]["sender.192.gz"]
    raw = gzip.decompress(checked(sender_path, sender_info["gzip_sha256"]))
    if sha256(raw).hexdigest() != sender_info["uncompressed_sha256"]:
        raise ValueError("sender G.192 digest differs from its fixture receipt")
    words = read_g192(raw)
    if None in words:
        raise ValueError("expected an original sender word at every slot")
    observed_inputs = {}
    for key, offset in (("mode", 0), ("last_octet", -1)):
        labels = [(row[key], word[offset]) for row, word in zip(rows, words, strict=True) if row[key] is not None]
        observed_inputs[key] = dict(compared=len(labels), matching=sum(left == right for left, right in labels))
    control = ledger["predecessor_control"]
    witness = (control["counter"] - FIRST) * 60 + control["slot"]
    return dict(format="clear-synthetic-iq-two-rule-score-v1", forecast_sha256=ledger_sha,
                packets_sha256=ledger["packets_sha256"], sender_gzip_sha256=sender_info["gzip_sha256"],
                sender_g192_sha256=sender_info["uncompressed_sha256"], slots=len(rows), observed_inputs=observed_inputs,
                same_slot=evaluate(rows, words, 0, by_position=True),
                shifted_sender={str(d): evaluate(rows, words, d) for d in (-1, 1)},
                complete_sender_opportunities=complete_sender_opportunities(rows, words),
                predecessor_control=dict(**control, target_original_b8=words[witness][1] >> 7,
                                         previous_original_mode=words[witness - 1][0]))
