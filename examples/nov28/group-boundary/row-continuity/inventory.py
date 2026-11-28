"""Recount the next received phase-zero counter after pristine native MSC triples."""
import argparse
import csv
from collections import Counter, defaultdict
import gzip
from hashlib import sha256
import json
from pathlib import Path
import sys


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
sys.path[:0] = [str(ROOT / "scripts"), str(ROOT / "examples/nov28/same-6140-1232")]
from drm_row_alignment import parse_msc, valid_packets
from native_groups import native_groups


def sweep(raw, seams):
    rows = parse_msc(raw)
    counts = Counter(native_rows=len(rows), pristine_triples=0, checked=0,
                     counter_disagreements=0, next_anchor_unavailable=0, eof=0,
                     excerpt_seam=0)
    observations = []
    unresolved = []
    # The joined excerpts declare their discontinuities. Do not treat a splice as a native edge.
    for begin, end in zip([0, *seams], [*seams, len(rows)], strict=True):
        if not 0 <= begin <= end <= len(rows):
            raise ValueError("invalid native excerpt limits")
        segment = rows[begin:end]
        framed = b"".join(len(row).to_bytes(4, "little") + row for row in segment)
        _, receipts, _, _ = native_groups(framed)
        for receipt in receipts:
            counts["pristine_triples"] += 1
            start = begin + receipt["phase0_row"]
            counter = receipt["counter"]
            next_row = start + 3
            if next_row == end:
                reason = "eof" if end == len(rows) else "excerpt_seam"
                counts[reason] += 1
                unresolved.append([start, counter, reason, None, None])
                continue
            packets = valid_packets(rows[next_row])
            phase = packets[0][2] >> 4 if 0 in packets else None
            if phase != 0 or 3 not in packets:
                counts["next_anchor_unavailable"] += 1
                unresolved.append([start, counter, "next_anchor_unavailable", sorted(packets), phase])
                continue
            # DU byte 664 falls at byte 128 of the 182-byte q3 wire including its header.
            next_counter = int.from_bytes(packets[3][128:132], "big")
            counts["checked"] += 1
            counts["counter_disagreements"] += next_counter != (counter + 1) % (1 << 32)
            witness = sha256(b"".join(rows[start:next_row]) + packets[0] + packets[3]).hexdigest()
            observations.append((counter, next_counter, witness, start))
    return counts, observations, unresolved


def measure():
    source = (HERE / "inputs.json").read_bytes()
    inventory = json.loads(source)
    seen_files = {}
    observations = defaultdict(list)
    sources = defaultdict(set)
    per_file = []
    totals = Counter()
    for index, entry in enumerate(inventory["files"]):
        path = ROOT / entry["path"]
        data = path.read_bytes()
        if sha256(data).hexdigest() != entry["sha256"]:
            raise ValueError(f"{entry['path']}: input SHA-256 mismatch")
        raw = gzip.decompress(data) if path.suffix == ".gz" else data
        digest = sha256(raw).hexdigest()
        if digest in seen_files:
            per_file.append(dict(path=entry["path"], identical_to=inventory["files"][seen_files[digest]]["path"]))
            continue
        seen_files[digest] = index
        counts, found, unresolved = sweep(raw, entry.get("breaks_before_row", []))
        totals.update(counts)
        per_file.append(dict(path=entry["path"], **counts, unresolved=unresolved))
        for counter, following, witness, start in found:
            key = (counter, following, witness)
            observations[key].append([index, start])
            if len(entry["recordings"]) == 1:
                sources[key].update(entry["recordings"])
    distinct_digests = sorted({witness for _, _, witness in observations})
    witness_digest = sha256("".join(digest + "\n" for digest in distinct_digests).encode("ascii")).hexdigest()
    multi_source = Counter(tuple(sorted(labels)) for labels in sources.values() if len(labels) > 1)
    disagreements = [dict(counter=counter, following_counter=following, sha256=witness,
                          occurrences=[[inventory["files"][i]["path"], row] for i, row in occurrences])
                     for (counter, following, witness), occurrences in sorted(observations.items())
                     if following != (counter + 1) % (1 << 32)]
    totals.update(file_paths=len(inventory["files"]), distinct_files=len(seen_files),
                  distinct_wire_witnesses=len(distinct_digests),
                  distinct_starting_counters=len({key[0] for key in observations}),
                  distinct_witnesses_from_multiple_recordings=sum(multi_source.values()),
                  distinct_disagreeing_witnesses=len(disagreements))
    report = dict(inventory_sha256=sha256(source).hexdigest(), totals=dict(totals),
                  sorted_witness_set_sha256=witness_digest,
                  witness_set_hash_basis="Each distinct lowercase wire SHA-256, sorted lexicographically, ASCII, LF after each.",
                  wire_sha256_basis="Three original 728-byte rows, then the next row's complete q0 and q3 wires in that order.",
                  multiple_recordings=[dict(recordings=list(labels), distinct_witnesses=n)
                                       for labels, n in sorted(multi_source.items())],
                  multiple_recordings_basis="The same witness in fixtures with different single-source recording labels. Repeat passes and excerpts of one recording count once.",
                  unresolved_columns=["first_native_row", "starting_counter", "reason",
                                      "following_row_valid_ordinals", "following_row_q0_phase"],
                  disagreements=disagreements, per_file=per_file)
    return report, observations, inventory["files"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    output = parser.add_mutually_exclusive_group()
    output.add_argument("--witnesses", action="store_true", help="write one CSV row per checkable occurrence")
    output.add_argument("--emit", action="store_true", help="write the full report as JSON to stdout")
    args = parser.parse_args()
    report, observations, files = measure()
    if args.witnesses:
        rows = csv.writer(sys.stdout, lineterminator="\n")
        rows.writerow(["starting_counter", "following_counter", "wire_sha256", "path", "first_native_row"])
        for key, occurrences in sorted(observations.items()):
            for index, start in occurrences:
                rows.writerow([*key, files[index]["path"], start])
        return
    if args.emit:
        print(json.dumps(report, indent=2))
        return
    if json.loads((HERE / "inventory.json").read_bytes()) != report:
        raise ValueError("recomputed report differs from inventory.json")
    print(json.dumps(report["totals"], indent=2))


if __name__ == "__main__":
    main()
