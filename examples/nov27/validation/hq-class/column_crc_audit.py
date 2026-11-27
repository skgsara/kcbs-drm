"""Audit column-zero support in the fixed November 25–26 ordinary-record score."""
import argparse
from collections import Counter, defaultdict
from hashlib import sha256
import json
from pathlib import Path

import numpy as np

from archived import CONTRIB, INPUTS, MODES, transport
from parse_text_records import crc
from review_supplied_records import review


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("frozen_score", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--details", type=Path, help="also write every original record witness offset")
    args = parser.parse_args()
    paths = [args.frozen_score, args.output]
    if args.details:
        paths.append(args.details)
    if len({path.resolve() for path in paths}) != len(paths):
        parser.error("use separate paths for score, summary, and optional witnesses")

    score_bytes = args.frozen_score.read_bytes()
    digest = sha256(score_bytes).hexdigest()
    if digest != "9441fb8dcff43d04ad04a7bdcace63a2a22715232390fb5816c1d33175885349":
        raise ValueError("unrecognized full score")
    score = json.loads(score_bytes)
    scored = [row for row in score["observations"]
              if "reviewed_full_p1" in row["applicable_support"]]
    targets = {row["counter"] for row in scored}
    units, origins, sources, _ = transport()
    for name, source in sources.items():
        if source != score["inputs"][name]["transport"]:
            raise ValueError(f"transport differs from frozen score for {name}")
    receipts = defaultdict(list)
    labels_by_tag = {}
    for tag in sorted(set(INPUTS.values())):
        names = {name for name in INPUTS if INPUTS[name] == tag}
        ticks = sorted(t for t, src in origins.items() if names.intersection(src))
        label_path = CONTRIB / "keys" / f"keys_{tag}.npz"
        if sha256(label_path.read_bytes()).hexdigest() != score["label_archives"][tag]["label_sha256"]:
            raise ValueError(f"label archive differs from frozen score for {tag}")
        with np.load(label_path, allow_pickle=False) as data:
            counters, labels, mask = data["counters"], data["ks"], data["crc_supported"]
        du = np.array([units[t] for t in ticks], dtype=np.uint8)
        actual_counters = np.array([c for c, _ in ticks])
        actual_phases = np.array([p for _, p in ticks])
        checked, records = review(counters, labels, mask, actual_counters, actual_phases, du)
        label_map = {int(c): i for i, c in enumerate(counters)}
        labels_by_tag[tag] = {int(c) for c, row in zip(counters, checked, strict=True) if row[:11].all()}
        for record in records:
            start = 16 * (3 * record["counter"] + record["phase"])
            end = 2 + record["body_length"]
            record_bytes = bytearray()
            columns = defaultdict(list)
            for relative in range(record["size"]):
                block, col = divmod(start + relative, 16)
                counter, phase = divmod(block, 3)
                index = label_map[counter]
                if not mask[index, col]:
                    raise ValueError("accepted record contains unsupported byte")
                record_bytes.append(units[counter, phase][698 + col] ^ labels[index, col])
                if counter in targets and col == 0:
                    columns[counter].append(relative)
            stored = int.from_bytes(record_bytes[end:end + 2], "big")
            if crc(record_bytes[:end]) != stored:
                raise ValueError("ordinary record no longer passes in independent reconstruction")
            for counter, offsets in columns.items():
                body = [o for o in offsets if o < end]
                checksum = [o for o in offsets if end <= o < end + 2]
                # Evaluate fixed checksum, then account for the same column in the
                # two stored CRC octets. Keep original boundaries in every control.
                fixed, physical = [], []
                for delta in (0x80, 0x40, 0xc0):
                    changed = record_bytes.copy()
                    for off in offsets:
                        changed[off] ^= delta
                    recalculated = crc(changed[:end])
                    if recalculated != stored:
                        fixed.append(delta)
                    if recalculated != int.from_bytes(changed[end:end + 2], "big"):
                        physical.append(delta)
                receipts[tag, counter].append(dict(
                    record_start_counter=record["counter"], record_start_phase=record["phase"],
                    header_or_body=body, stored_crc=checksum, padding_or_fill=[o for o in offsets if o >= end + 2],
                    crc_failure_with_fixed_checksum=fixed, crc_failure_with_all_column_occurrences=physical))

    by_mode = {mode: Counter() for mode in MODES}
    by_counter = defaultdict(set)
    witnesses = {}
    mode_counters = defaultdict(lambda: defaultdict(set))
    high_two_bits = defaultdict(Counter)
    for row in scored:
        counter, phase, mode = row["counter"], row["phase"], row["mode"]
        tags = sorted({INPUTS[n] for n in origins[counter, phase] if counter in labels_by_tag[INPUTS[n]]})
        records = [w for tag in tags for w in receipts[tag, counter]]
        if not records:
            raise ValueError("no source-scoped reviewed record for scored word")
        flags = {"all_scored"}
        if any(r["header_or_body"] for r in records):
            flags.add("overlaps_header_or_body")
        if any(r["stored_crc"] for r in records):
            flags.add("overlaps_stored_crc")
        if all(not r["stored_crc"] and not r["header_or_body"] for r in records):
            flags.add("only_padding_or_fill")
        for delta in (0x80, 0x40, 0xc0):
            for field in ("crc_failure_with_fixed_checksum", "crc_failure_with_all_column_occurrences"):
                if any(delta in r[field] for r in records):
                    flags.add(f"{field}_{delta:02x}")
                if any(delta in r[field] and r["header_or_body"] for r in records):
                    flags.add(f"body_witness_{field}_{delta:02x}")
        for flag in flags:
            by_mode[mode][flag] += 1
            by_counter[flag].add(counter)
            mode_counters[mode][flag].add(counter)
        if "overlaps_header_or_body" in flags:
            high_two_bits[mode][format(row["observed_high_two_bits"], "02b")] += 1
        witnesses[str(counter)] = {tag: receipts[tag, counter] for tag in tags}
    result = dict(frozen_score_sha256=digest, by_mode=by_mode,
                  distinct_counters={f: len(values) for f, values in sorted(by_counter.items())},
                  witnesses=witnesses)
    complete = (json.dumps(result, sort_keys=True, indent=2) + "\n").encode()
    if args.details:
        args.details.write_bytes(complete)
    fields = {
        "scored": "all_scored",
        "header_or_body": "overlaps_header_or_body",
        "stored_checksum_octet": "overlaps_stored_crc",
        "padding_or_fill_only": "only_padding_or_fill",
    }
    for delta in ("80", "40", "c0"):
        fields["fixed_checksum_failure_" + delta] = "crc_failure_with_fixed_checksum_" + delta
        fields["all_column_occurrences_failure_" + delta] = "crc_failure_with_all_column_occurrences_" + delta
    by_class = {}
    for mode in MODES:
        by_class[mode] = {
            "words": {name: by_mode[mode][flag] for name, flag in fields.items()},
            "distinct_counters": {name: len(mode_counters[mode][flag]) for name, flag in fields.items()},
            "header_or_body_high_two_bits": high_two_bits[mode],
        }
    summary = {
        "frozen_score_sha256": digest,
        "full_audit_sha256": sha256(complete).hexdigest(),
        "distinct_counters": {name: len(by_counter[flag]) for name, flag in fields.items()},
        "by_mode": by_class,
        "control": "Each predetermined XOR change applies to text-tail column zero of one counter within one fixed-boundary ordinary record. A word is counted when at least one witnessed record meets the condition.",
    }
    args.output.write_text(json.dumps(summary, indent=2) + "\n")
    print(sha256(args.output.read_bytes()).hexdigest())


if __name__ == "__main__":
    main()
