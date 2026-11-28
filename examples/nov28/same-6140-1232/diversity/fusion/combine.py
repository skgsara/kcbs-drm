"""Replay the frozen 12:32 development comparison using deinterleaved MSC cells and a native decoder."""
import argparse
from collections import Counter, defaultdict
from hashlib import sha256
import json
from pathlib import Path
import struct
import subprocess

import sys

from proof import CASES, accepted, data_unit, receipts, wire_rows

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[4] / "scripts"))
from drm_msc_cells import combine, decode, read_blocks
ALIGNMENT_SHA = "31605d50dea3f9a89ef9fef1b351eedfbb882a234b93038473e23331d8e30207"
PROTOCOL_SHA = "a5c3c01b4331ad40672d6c9d95f2dd9fb6192cec421200c8697c26c85d964870"
SITES = ("edogawa", "yokohama")
SHIFTS = {"aligned": (0, 0), "cell_minus1": (0, -1), "cell_plus1": (0, 1),
          "block_minus1": (-1, 0), "block_plus1": (1, 0)}
COHORTS = ("calibration", "guard", "evaluation")
METRICS = ("rows", "edogawa_packets", "yokohama_packets", "union_packets", "combined_packets", "matching_packets",
           "added_packets", "lost_packets", "conflicting_packets", "edogawa_dus", "yokohama_dus", "union_dus",
           "combined_dus", "matching_dus", "added_dus", "lost_dus", "conflicting_dus")


def checked_file(path, digest):
    raw = path.read_bytes()
    if sha256(raw).hexdigest() != digest:
        raise ValueError(f"{path.name} differs from its published checksum")
    return raw


def load_site(observer, site, decoder):
    base = observer / site
    receipt = json.loads((HERE.parents[1] / f"{site}-native.json").read_bytes())
    wire = wire_rows(checked_file(base / "msc.bin", receipt["msc_sha256"]))
    raw = (base / "cells.bin").read_bytes()
    blocks = read_blocks(raw)
    by_wire = defaultdict(list)
    for block in blocks:
        if block.header[18:20] == (0, 728):
            by_wire[block.hard[:728]].append(block)
    # This fixture has no repeated hard row at either site. Require a unique
    # whole-row binding rather than assuming one native record per MLC callback.
    multiplicity = Counter(wire)
    if any(multiplicity[w] != 1 or len(by_wire[w]) != 1 for w in wire):
        raise ValueError(f"{site}: an original hard row lacks a unique observer match")
    rows = [by_wire[w][0] for w in wire]
    if any(left.header[0] >= right.header[0] for left, right in zip(rows, rows[1:])):
        raise ValueError(f"{site}: native hard-row order differs from the observer")
    reproduced = decode(decoder, [(b, b.cells) for b in rows])
    if any(got != b.hard for got, b in zip(reproduced, rows, strict=True)):
        raise ValueError(f"{site}: standalone decode differs from the original native bits")
    summary = dict(native_rows=len(wire), standalone_exact=len(reproduced), msc_sha256=receipt["msc_sha256"],
                   soft_sha256=sha256(raw).hexdigest())
    return wire, rows, summary


def grade(left, right, candidate):
    a, b, out = map(accepted, (left, right, candidate))
    if any(x and y and x != y for x, y in zip(a, b)):
        raise ValueError("two accepted physical packets disagree at a reference coordinate")
    union = [x or y for x, y in zip(a, b)]
    counts = Counter(rows=1, edogawa_packets=sum(map(bool, a)), yokohama_packets=sum(map(bool, b)),
                     union_packets=sum(map(bool, union)), combined_packets=sum(map(bool, out)))
    for reference, new in zip(union, out):
        if reference and new:
            counts["matching_packets" if reference == new else "conflicting_packets"] += 1
        elif new:
            counts["added_packets"] += 1
        elif reference:
            counts["lost_packets"] += 1
    ref_du, new_du = data_unit(union), data_unit(out)
    counts.update(edogawa_dus=int(data_unit(a) is not None), yokohama_dus=int(data_unit(b) is not None),
                  union_dus=int(ref_du is not None), combined_dus=int(new_du is not None))
    if ref_du and new_du:
        counts["matching_dus" if ref_du == new_du else "conflicting_dus"] += 1
    elif new_du:
        counts["added_dus"] += 1
    elif ref_du:
        counts["lost_dus"] += 1
    return counts


def records_bytes(rows):
    return b"".join(struct.pack("<I", len(row)) + row for row in rows)


def replay(observer, alignment, decoder, out):
    checked_file(HERE.parent / "protocol.md", PROTOCOL_SHA)
    witness = json.loads(checked_file(alignment, ALIGNMENT_SHA))
    left, left_blocks, left_stats = load_site(observer, SITES[0], decoder)
    right, right_blocks, right_stats = load_site(observer, SITES[1], decoder)
    variants, gains = {}, {}
    for label, (block_shift, cell_shift) in SHIFTS.items():
        counts = {group: Counter(dict.fromkeys(METRICS, 0)) for group in COHORTS}
        cases, items = [], []
        for pair in witness:
            left_index = pair["edogawa_row"]
            right_index = pair["yokohama_row"] + block_shift
            if not 0 <= right_index < len(right_blocks):
                continue
            a, b = left_blocks[left_index], right_blocks[right_index]
            if a.geometry() == b.geometry():
                cases.append(pair)
                items.append((a, combine(a, b, cell_shift)))
        for pair, bits in zip(cases, decode(decoder, items), strict=True):
            li, ri = pair["edogawa_row"], pair["yokohama_row"]
            wire = bits[:728]
            stats = grade(left[li], right[ri], wire)
            counts[pair["cohort"]].update(stats)
            if label == "aligned" and stats["added_packets"]:
                gains[li, ri] = wire
        variants[label] = dict(by_cohort=counts, skipped=len(witness) - len(cases))
    # Bind the compact proof to the two independently preidentified all-receiver q0 losses.
    if set(gains) != set(CASES):
        raise ValueError("aligned gain coordinates differ from the published fixture")
    original = [w for li, ri in CASES for w in (left[li], right[ri])]
    combined = [gains[pair] for pair in CASES]
    proof = receipts(original, combined)
    metrics = dict(stations=dict(edogawa=left_stats, yokohama=right_stats), variants=variants,
                   protocol_sha256=PROTOCOL_SHA, alignment_sha256=ALIGNMENT_SHA)
    out.mkdir(parents=True, exist_ok=False)
    for name, obj in (("metrics.json", metrics), ("proof.json", proof)):
        (out / name).write_text(json.dumps(obj, indent=2) + "\n")
    (out / "original-witnesses.msc.bin").write_bytes(records_bytes(original))
    (out / "recovered.msc.bin").write_bytes(records_bytes(combined))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--observer", type=Path, required=True, help="directory containing both station replay directories")
    parser.add_argument("--alignment", type=Path, default=HERE.parent / "alignment" / "row-pairs.json")
    parser.add_argument("--decoder", type=Path, required=True, help="executable built with harness.mk")
    parser.add_argument("--out", type=Path, required=True, help="new output directory")
    args = parser.parse_args()
    try:
        replay(args.observer, args.alignment, args.decoder.resolve(), args.out)
    except (OSError, ValueError, struct.error, subprocess.CalledProcessError) as error:
        parser.exit(1, f"{error}\n")
