"""Locate CRC-good phase tags between two directly received counters in one native MSC."""
from argparse import ArgumentParser
from collections import defaultdict
from contextlib import redirect_stdout
from hashlib import sha256
from itertools import combinations
import io
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

import numpy as np

SCRIPTS = Path(__file__).resolve().parents[3] / "scripts"
sys.path.insert(0, str(SCRIPTS))
from received_evs_packets import read_packet_snapshot
from salvage_msc_packets import crc, records, salvage

MODULUS = 1 << 32


def is_anchor(row):
    return row and row["packet_ok"][0] and row["packet_ok"][3] and row["phase"] == 0


def fits(row, offset, first):
    phase = offset % 3
    if row["packet_ok"][0] and row["phase"] != phase:
        return False
    return phase != 0 or not row["packet_ok"][3] or row["counter"] == (first + offset // 3) % MODULUS


def embeddings(rows, indices, first, span):
    for offsets in combinations(range(1, span), len(indices)):
        if all(fits(rows[i], offset, first) for i, offset in zip(indices, offsets, strict=True)):
            yield offsets


def tagged_assignments(rows):
    anchors = [i for i, row in enumerate(rows) if is_anchor(row)]
    assigned = {}
    for left, right in zip(anchors, anchors[1:]):
        first = rows[left]["counter"]
        distance = (rows[right]["counter"] - first) % MODULUS
        if distance not in (1, 2) or right - left > 3 * distance:
            continue
        segment = rows[left:right + 1]
        if any(row is None or not any(row["packet_ok"]) for row in segment):
            continue
        first_packets = [row["du"][:179] for row in segment if row["packet_ok"][0]]
        if len(set(first_packets)) != len(first_packets):
            continue
        interior = list(range(left + 1, right))
        span = 3 * distance
        # Reject inconsistent callback sequences. An opaque row supplies no phase label.
        if next(embeddings(rows, interior, first, span), None) is None:
            continue
        tagged = [i for i in interior if rows[i]["packet_ok"][0]]
        placements = list(embeddings(rows, tagged, first, span))
        if not placements:
            continue
        for i, offsets in zip(tagged, zip(*placements), strict=True):
            if len(set(offsets)) == 1:
                delta, phase = divmod(offsets[0], 3)
                assigned[i] = ((first + delta) % MODULUS, phase)
    return assigned


def stock_and_extra(path, stock_out):
    with redirect_stdout(io.StringIO()):
        salvage([path], stock_out, transport_only=True, save_packets=True)
    rows = list(records(path))
    stock = {}
    provenance = json.loads((stock_out / "provenance.json").read_text())
    for key, receipts in provenance.items():
        counter, phase, ordinal = map(int, key.split(","))
        for _, index in receipts:
            coordinate = (counter, phase)
            if rows[index] is None or not rows[index]["packet_ok"][ordinal]:
                raise ValueError("stock provenance points to a rejected packet")
            if stock.setdefault(index, coordinate) != coordinate:
                raise ValueError("stock assigned a native row to multiple coordinates")
    extra = {}
    for index, coordinate in tagged_assignments(rows).items():
        if index in stock:
            if stock[index] != coordinate:
                raise ValueError("new phase placement conflicts with a stock assignment")
        else:
            extra[index] = coordinate
    return rows, stock, extra


def read_assignments(path):
    """Return parsed native rows, stock index-to-coordinate map and strict additions."""
    with TemporaryDirectory() as tmp:
        return stock_and_extra(Path(path), Path(tmp) / "stock")


def merge_extra(rows, stock, extra, stock_path):
    ticks, units, flags = read_packet_snapshot(stock_path)
    baseline = {}
    for tick, unit, present in zip(ticks, units, flags, strict=True):
        baseline[divmod(int(tick), 3)] = {q: bytes(unit[q * 179:(q + 1) * 179])
                                          for q in range(4) if present[q]}
    result = dict(baseline)
    prior_quarantine = set(stock.values()) - baseline.keys()
    additions = defaultdict(list)
    for i, coordinate in extra.items():
        additions[coordinate].append(i)
    rejected = []
    for coordinate, indices in sorted(additions.items()):
        original = baseline.get(coordinate, {})
        packets = dict(original)
        reason = None
        if coordinate in prior_quarantine:
            reason = "quarantined_by_stock"
        else:
            for i in indices:
                for q, ok in enumerate(rows[i]["packet_ok"]):
                    if ok and packets.setdefault(q, rows[i]["payload"][q]) != rows[i]["payload"][q]:
                        reason = "conflicting_packet"
            if reason is None and len(packets) == 4:
                du = b"".join(packets[q] for q in range(4))
                if crc(du[:714]) != int.from_bytes(du[714:], "big"):
                    reason = "reassembled_du_crc"
        if reason is None:
            result[coordinate] = packets
        else:
            rejected.append(dict(counter=coordinate[0], phase=coordinate[1], extra_rows=indices,
                                 reason=reason, preserved_stock_ordinals=sorted(original)))
    return result, rejected


def write_extended(snapshot, out):
    ticks, flags, data, complete = [], [], bytearray(), []
    for coordinate, packets in sorted(snapshot.items()):
        present = [q in packets for q in range(4)]
        unit = b"".join(packets.get(q, bytes(179)) for q in range(4))
        if all(present):
            complete.append((coordinate, unit))
        counter, phase = coordinate
        ticks.append(3 * counter + phase)
        flags.append(present)
        data.extend(unit)
    out.mkdir()
    np.savez_compressed(out / "packets.npz", ticks=np.asarray(ticks, np.int64),
                        packet_ok=np.asarray(flags, bool).reshape(-1, 4),
                        packets=np.frombuffer(data, np.uint8).reshape(-1, 4, 179))
    np.savez_compressed(out / "data_units.npz",
                        counters=np.asarray([c for (c, _), _ in complete], np.uint32),
                        phases=np.asarray([p for (_, p), _ in complete], np.uint8),
                        du=np.frombuffer(b"".join(u for _, u in complete), np.uint8).reshape(-1, 716))


def snapshot_summary(directory):
    path = directory / "packets.npz"
    ticks, _, flags = read_packet_snapshot(path)
    return dict(ticks=len(ticks), packets=int(flags.sum()), complete_dus=int(flags.all(axis=1).sum()),
                packets_sha256=sha256(path.read_bytes()).hexdigest(),
                data_units_sha256=sha256((directory / "data_units.npz").read_bytes()).hexdigest())


def run(path, out):
    out.mkdir(parents=True, exist_ok=False)
    rows, stock, extra = stock_and_extra(path, out / "stock")
    snapshot, rejected = merge_extra(rows, stock, extra, out / "stock" / "packets.npz")
    write_extended(snapshot, out / "extended")
    report = dict(native_msc_sha256=sha256(path.read_bytes()).hexdigest(), native_rows=len(rows),
                  stock=snapshot_summary(out / "stock"), extended=snapshot_summary(out / "extended"),
                  extra_rows=[dict(native_row=i, counter=c, phase=p,
                                   crc_valid_ordinals=[q for q, ok in enumerate(rows[i]["packet_ok"]) if ok])
                              for i, (c, p) in sorted(extra.items())],
                  extended_quarantine=rejected)
    (out / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


if __name__ == "__main__":
    cli = ArgumentParser(description=__doc__)
    cli.add_argument("native", type=Path)
    cli.add_argument("--out", type=Path, required=True, help="new output directory")
    args = cli.parse_args()
    print(json.dumps(run(args.native, args.out), indent=2))
