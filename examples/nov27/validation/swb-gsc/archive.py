"""Check the fixed historical SWB GSC clear-prefix fixture against stock pulse-index domains."""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import csv
from hashlib import sha256
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "late-payload/gsc-control"))
from bounded import build
from check import physical_position

PREFIX_DIGEST = "0d0863dc7ac2086c8b1e9a66a9c5e624263ea6ee024314312fc9759933c79ae9"
OFFSETS = (24, 27)


def index_checks(size, high, width, start):
    remaining = min(1 << width, size - (high << width))
    if remaining <= 0:
        raise ValueError("the observed bucket has no legal codebook entries")
    for offset in OFFSETS:
        first = (1 + offset) * 8
        weights = {physical_position(start, width, bit) - first: 1 << bit for bit in range(width)
                   if first <= physical_position(start, width, bit) < first + 8}
        if not weights:
            continue
        # The other raw-index bits may all be zero. This gives the exact
        # projection of this one codebook bound onto the selected octet.
        if sum(weights.values()) < remaining:
            yield offset, None
            continue
        rejected = [byte for byte in range(256)
                    if sum(weight for i, weight in weights.items() if byte & (128 >> i)) >= remaining]
        yield offset, dict(size=size, high=high, width=width, start=start,
                           residual_limit_exclusive=remaining, rejected=rejected)


def scan_chunk(native, indexed_prefixes):
    rows = []
    with tempfile.TemporaryDirectory() as directory:
        record = Path(directory) / "prefix.192"
        for index, prefix in indexed_prefixes:
            known = [0x81 if octet & (128 >> i) else 0x7f for octet in prefix for i in range(8)]
            runs = []
            for filler in (0x7f, 0x81):
                record.write_bytes(struct.pack("<266H", 0x6b21, 264, *known, *([filler] * 136)))
                proc = subprocess.run([native, "-q", "-no_delay_cmp", "16", record, os.devnull],
                                      capture_output=True, timeout=10)
                if proc.returncode not in (0, 42):
                    raise ValueError(f"prefix {index} failed with exit {proc.returncode}")
                events = [line for line in proc.stderr.splitlines() if line.startswith((b"P,", b"N,"))]
                runs.append((proc.returncode, events))
            if runs[0] != runs[1]:
                raise ValueError(f"unavailable suffix affected the prefix observer at row {index}")
            events = runs[0][1]
            entered = any(line.startswith(b"P,") for line in events)
            intersections = Counter()
            checks = []
            for line in events:
                if line.startswith(b"N,"):
                    frame, size, high, width, start = map(int, line.split(b",")[1:])
                    if frame != 0 or not entered:
                        raise ValueError("expected one cold-reset word")
                    for offset, check in index_checks(size, high, width, start):
                        intersections[offset] += 1
                        if check is not None:
                            checks.append(dict(offset=offset, **check))
            rows.append((index, entered, intersections, checks))
    return rows


def scan(native, prefixes, coordinates, jobs):
    if sha256(prefixes).hexdigest() != PREFIX_DIGEST or len(prefixes) != 16 * len(coordinates):
        raise ValueError("requires the fixed 6,716 historical prefixes and their coordinates")
    items = [(i, prefixes[16*i:16*(i+1)]) for i in range(len(coordinates))]
    for (i, prefix), row in zip(items, coordinates, strict=True):
        if (int(row["row"]) != i or int(row["mode_hex"], 16) != prefix[0]
                or prefix[0] >> 3 not in (13, 14)):
            raise ValueError(f"archive coordinate mismatch at row {i}")
    chunks = [items[worker::jobs] for worker in range(jobs)]
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        batches = list(pool.map(lambda chunk: scan_chunk(native, chunk), chunks))
    summaries = {}
    decisions = []
    for index, entered, intersections, checks in sorted(row for batch in batches for row in batch):
        coordinate = coordinates[index]
        counts = summaries.setdefault(coordinate["cohort"], Counter())
        counts["words"] += 1
        counts["entered_prefix_walk"] += int(entered)
        for offset in OFFSETS:
            counts[f"index_intersections_p{offset}"] += intersections[offset]
            counts[f"words_with_located_p{offset}"] += int(intersections[offset] > 0)
        for check in checks:
            decisions.append(dict(row=index, cohort=coordinate["cohort"], counter=int(coordinate["counter"]),
                                  slot=int(coordinate["slot"]), **check))
    return dict(prefix_sha256=PREFIX_DIGEST, summaries=summaries, decisions=decisions)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="pristine TS 26.443 c-code directory")
    parser.add_argument("prefix_directory", type=Path, help="directory containing prefixes.bin and coordinates.csv")
    parser.add_argument("out", type=Path)
    parser.add_argument("--jobs", type=int, default=4, choices=range(1, 17))
    args = parser.parse_args()
    with (args.prefix_directory / "coordinates.csv").open(newline="") as f:
        coords = list(csv.DictReader(f))
    with tempfile.TemporaryDirectory() as tmp:
        observer = build(Path(tmp), args.source.resolve(), stop_after_prefix=True)
        result = scan(observer, (args.prefix_directory / "prefixes.bin").read_bytes(), coords, args.jobs)
    args.out.write_text(json.dumps(result, indent=2) + "\n")
