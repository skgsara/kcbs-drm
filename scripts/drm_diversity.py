"""Combine independently aligned DRM MSC observations and write a conservative left-chronology wire stream."""
import argparse
from collections import Counter, defaultdict
from hashlib import sha256
import json
from pathlib import Path
import struct
import subprocess
from tempfile import TemporaryDirectory

import numpy as np

from drm_msc_cells import combine, decode, read_blocks
from drm_row_alignment import parse_msc, valid_packets, witnessed_pairs
from salvage_msc_packets import PACKET_HEADERS
from tail_fill_audit import crc


def digest(raw):
    return sha256(raw).hexdigest()


def data_unit(packets):
    if len(packets) != 4:
        return None
    unit = b"".join(packets[q][1:-2] for q in range(4))
    return unit if crc(unit[:-2]) == int.from_bytes(unit[-2:], "big") else None


def integrity_barrier(row, packets):
    if len(row) != 728:
        return "unsupported_row_size"
    for q, header in enumerate(PACKET_HEADERS):
        packet = row[q*182:q*182+182]
        if packet[0] != header and crc(packet[:-2]) == int.from_bytes(packet[-2:], "big"):
            return "crc_valid_wrong_header"
    if len(packets) == 4 and data_unit(packets) is None:
        return "invalid_complete_du_crc"
    return None


def read_site(path):
    native = (path / "msc.bin").read_bytes()
    soft = (path / "cells.bin").read_bytes()
    rows = parse_msc(native)
    blocks = read_blocks(soft) if soft else []
    sizes = Counter(map(len, rows))
    packets = dus = 0
    barriers = Counter()
    for row in rows:
        observed = valid_packets(row)
        reason = integrity_barrier(row, observed)
        if reason:
            barriers[reason] += 1
        else:
            packets += len(observed)
            dus += int(data_unit(observed) is not None)
    metadata = dict(msc_sha256=digest(native), cells_sha256=digest(soft), native_rows=len(rows),
                    row_sizes=dict(sizes), observer_blocks=len(blocks), accepted_native_packets=packets,
                    complete_native_dus=dus, rejected_native_rows=dict(barriers))
    return rows, blocks, metadata


def map_blocks(rows, blocks):
    """Anchor callbacks to distinct complete hard record bytes, preserving order on this receiver."""
    candidates = defaultdict(list)
    for block in blocks:
        # The file-only decoder handles a single stream 0 with a 728-byte part B.
        if block.header[18:26] == (0, 728, 0, 0, 0, 0, 0, 0) and len(block.hard) >= 728:
            candidates[block.hard[:728]].append(block)
    copies = Counter(rows)
    unique = [(i, candidates[row][0]) for i, row in enumerate(rows)
              if copies[row] == 1 and len(candidates.get(row, ())) == 1]
    kept = {}
    previous_max = -1
    reverse_min = [len(blocks)] * (len(unique) + 1)
    for i in range(len(unique) - 1, -1, -1):
        reverse_min[i] = min(unique[i][1].header[0], reverse_min[i+1])
    for i, (row, block) in enumerate(unique):
        ordinal = block.header[0]
        if previous_max < ordinal < reverse_min[i+1]:
            kept[row] = block
        previous_max = max(previous_max, ordinal)
    return kept


def unsupported(block):
    h = block.header
    if h[5] != 1 or h[12] != 2:
        return "unsupported_coding_scheme"
    if not (0 <= h[3] <= 3 and 0 <= h[4] <= 5 and h[6] in (0, 1) and h[7] in (0, 1)
            and 0 <= h[11] <= 10 and h[2] >= 728*8 and h[1] == h[26]):
        return "unsupported_decoder_parameters"
    if not np.isfinite(block.cells).all():
        return "nonfinite_native_input"
    channel = block.cells[:, 2]
    if not np.any((channel > 0) & (channel < 1e30)):
        return "no_usable_channel_cells"
    return None


def soft_candidates(pairs, left, right, decoder):
    """Independently reproduce both original MLC blocks before using their cell estimates."""
    result = {}
    failures = {}
    for start in range(0, len(pairs), 16):
        batch = []
        for li, ri in pairs[start:start+16]:
            a, b = left.get(li), right.get(ri)
            if a is None or b is None:
                failures[li] = "no_unique_native_to_soft_binding"
                continue
            reason = unsupported(a) or unsupported(b)
            if reason or a.geometry() != b.geometry():
                failures[li] = reason or "incompatible_cell_geometry"
                continue
            batch.append((li, a, b))
        baseline = [(block, block.cells) for _, a, b in batch for block in (a, b)]
        original = iter(decode(decoder, baseline))
        jobs, indices = [], []
        for li, a, b in batch:
            lbits, rbits = next(original), next(original)
            if lbits != a.hard or rbits != b.hard:
                failures[li] = "standalone_hard_decision_mismatch"
                continue
            try:
                with np.errstate(over="raise", invalid="raise", divide="raise"):
                    cells = combine(a, b, 0)
            except (OverflowError, FloatingPointError):
                failures[li] = "unrepresentable_cell_weights"
                continue
            jobs.append((a, cells))
            indices.append(li)
        for li, bits in zip(indices, decode(decoder, jobs), strict=True):
            result[li] = bits[:728]
    return result, failures


def overlay(row, packets):
    return b"".join(packets.get(q, row[182*q:182*q+182]) for q in range(4))


def resolve_row(left, right, candidate):
    """Retain original left bytes on a conflict; a new FEC packet requires a valid whole DU."""
    a, b = valid_packets(left), valid_packets(right)
    conflicts = sorted(q for q in a.keys() & b.keys() if a[q] != b[q])
    result = dict(left_valid=sorted(a), right_valid=sorted(b), hard_conflict_ordinals=conflicts, peer_added=[],
                  soft_valid=[], soft_conflict_ordinals=[], soft_added=[], union_du=False, soft_du=False)
    barrier = integrity_barrier(left, a) or integrity_barrier(right, b)
    if conflicts or barrier:
        return left, dict(result, status=barrier or "independent_packet_conflict")
    union = {**a, **b}
    if len(union) == 4 and data_unit(union) is None:
        return left, dict(result, status="hard_union_du_crc_failed")
    result.update(peer_added=sorted(b.keys() - a.keys()), union_du=data_unit(union) is not None)
    pooled = overlay(left, union)
    if candidate is None:
        return pooled, dict(result, status="hard_pool")
    soft = valid_packets(candidate)
    conflicts = sorted(q for q in soft.keys() & union.keys() if soft[q] != union[q])
    result.update(soft_valid=sorted(soft), soft_conflict_ordinals=conflicts, soft_du=data_unit(soft) is not None)
    barrier = integrity_barrier(candidate, soft)
    if conflicts or barrier:
        return pooled, dict(result, status=barrier or "soft_packet_conflict")
    merged = {**union, **soft}
    extra = sorted(soft.keys() - union.keys())
    if extra and data_unit(merged) is not None:
        result["soft_added"] = extra
        return overlay(left, merged), dict(result, status="soft_gain")
    return pooled, dict(result, status="unconfirmed_soft_packets" if extra else "hard_pool")


def compare(left_dir, right_dir, decoder):
    decoder = decoder.resolve()
    decoder_hash = digest(decoder.read_bytes())
    left, left_blocks, left_meta = read_site(left_dir)
    right, right_blocks, right_meta = read_site(right_dir)
    pairs, alignment = witnessed_pairs(left, right)
    bound_left, bound_right = map_blocks(left, left_blocks), map_blocks(right, right_blocks)
    left_meta["uniquely_bound_blocks"] = len(bound_left)
    right_meta["uniquely_bound_blocks"] = len(bound_right)
    tested = [(li, ri) for li, ri in pairs if not (
        integrity_barrier(left[li], valid_packets(left[li])) or integrity_barrier(right[ri], valid_packets(right[ri])))]
    soft, failures = soft_candidates(tested, bound_left, bound_right, decoder)
    output = list(left)
    ledger = []
    coverage = Counter(dict.fromkeys(("witnessed_pairs", "soft_decoded_rows", "changed_rows", "peer_added_packets",
                                     "soft_added_packets", "soft_observed_packets", "soft_conflicting_packets",
                                     "soft_observed_complete_dus", "new_complete_dus_from_hard_pool", "new_complete_dus_from_soft",
                                     "preserved_left_packets", "output_accepted_packets", "output_complete_dus"), 0))
    for li, ri in pairs:
        row, entry = resolve_row(left[li], right[ri], soft.get(li))
        output[li] = row
        before = data_unit(valid_packets(left[li]))
        after = data_unit(valid_packets(row))
        entry.update(left_row=li, right_row=ri, soft_skip_reason=failures.get(li),
                     new_packets_sha256={q: digest(row[182*q:182*q+182]) for q in entry["peer_added"] + entry["soft_added"]},
                     complete_output_du_sha256=digest(after) if after is not None else None)
        ledger.append(entry)
        coverage.update(witnessed_pairs=1, soft_decoded_rows=int(li in soft), changed_rows=int(row != left[li]),
                        peer_added_packets=len(entry["peer_added"]), soft_added_packets=len(entry["soft_added"]),
                        soft_observed_packets=len(entry["soft_valid"]), soft_conflicting_packets=len(entry["soft_conflict_ordinals"]),
                        soft_observed_complete_dus=int(entry["soft_du"]), new_complete_dus_from_hard_pool=int(before is None and entry["union_du"]),
                        new_complete_dus_from_soft=int(after is not None and bool(entry["soft_added"])))
    for original, row in zip(left, output, strict=True):
        prior = valid_packets(original)
        final = valid_packets(row)
        if any(final.get(q) != packet for q, packet in prior.items()):
            raise ValueError("an existing CRC-valid left packet was lost or altered")
        if not integrity_barrier(original, prior):
            coverage["preserved_left_packets"] += len(prior)
        if not integrity_barrier(row, final):
            coverage["output_accepted_packets"] += len(final)
            coverage["output_complete_dus"] += int(data_unit(final) is not None)
    raw = b"".join(struct.pack("<I", len(row)) + row for row in output)
    status = "soft_comparison"
    if not pairs:
        status = "no_witnessed_pairs"
    elif not soft:
        status = "hard_pool_only"
    report = dict(format="drm-witnessed-diversity-v1", status=status, sources=dict(left=left_meta, right=right_meta),
                  decoder_sha256=decoder_hash, alignment=alignment, coverage=coverage, soft_skip_reasons=Counter(failures.values()),
                  output_native_rows=len(output), output_msc_sha256=digest(raw), rows=ledger,
                  scope="All output ordinals follow the left MSC file. Unwitnessed rows are copied unchanged. "
                        "The file preserves received wire bytes, including existing invalid quarters. "
                        "Absolute counter/phase assignment requires the ordinary transport parser.")
    return raw, report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--left", type=Path, required=True, help="reference chronology; contains msc.bin and cells.bin")
    parser.add_argument("--right", type=Path, required=True, help="independent peer; contains msc.bin and cells.bin")
    parser.add_argument("--decoder", type=Path, required=True, help="stock 16-QAM harness executable")
    parser.add_argument("--out", type=Path, required=True, help="fresh output directory")
    args = parser.parse_args()
    try:
        if args.out.exists():
            raise ValueError("output directory already exists")
        raw, report = compare(args.left, args.right, args.decoder)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(dir=args.out.parent) as temp:
            staged = Path(temp) / "result"
            staged.mkdir()
            (staged / "msc.bin").write_bytes(raw)
            (staged / "report.json").write_text(json.dumps(report, indent=2) + "\n")
            # Claim an unused name atomically before publishing both finished files.
            args.out.mkdir()
            try:
                staged.replace(args.out)
            except OSError:
                args.out.rmdir()
                raise
        print(json.dumps({"status": report["status"], **report["coverage"]}))
    except (OSError, ValueError, struct.error, subprocess.CalledProcessError) as error:
        parser.exit(2, f"{parser.prog}: {error}\n")


if __name__ == "__main__":
    main()
