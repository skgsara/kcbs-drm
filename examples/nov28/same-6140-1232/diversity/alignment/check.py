"""Reproduce the sealed 12:32 UTC cross-station MSC row map from the published wire dumps."""
import argparse
import binascii
from collections import Counter, defaultdict
from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import struct

import numpy as np


HERE = Path(__file__).resolve().parent
STATIONS = ("edogawa", "yokohama")
HEADERS = (0x80, 0x01, 0x02, 0x43)
MAP_SHA256 = "31605d50dea3f9a89ef9fef1b351eedfbb882a234b93038473e23331d8e30207"
PROTOCOL_SHA256 = "df1202c8721b69536db941f761086b13aa6e2b5e3718c2f738d4dd923eef645d"


@dataclass
class Station:
    packet_rows: dict
    row_packets: dict
    coordinates: dict
    assigned: set
    receipt: dict


def wire_index(raw):
    by_packet = defaultdict(list)
    by_row = defaultdict(dict)
    offset = row = 0
    while offset < len(raw):
        if offset + 4 > len(raw):
            raise ValueError("truncated MSC length")
        size, = struct.unpack_from("<I", raw, offset)
        start = offset + 4
        offset = start + size
        if not size or offset > len(raw):
            raise ValueError("invalid MSC record length")
        if size == 728:
            for q, header in enumerate(HEADERS):
                wire = raw[start + 182 * q:start + 182 * (q + 1)]
                if wire[0] != header or (binascii.crc_hqx(wire[:-2], 0xffff) ^ 0xffff) != int.from_bytes(wire[-2:], "big"):
                    continue
                by_packet[q, wire].append(row)
                by_row[row][q] = wire
        row += 1
    return row, by_packet, by_row


def station(case, name):
    raw = (case / f"{name}-msc.bin").read_bytes()
    snapshot = case / f"{name}-packets.npz"
    native = json.loads((case / f"{name}-native.json").read_bytes())
    msc_digest = sha256(raw).hexdigest()
    packet_digest = sha256(snapshot.read_bytes()).hexdigest()
    if msc_digest != native["msc_sha256"] or packet_digest != native["archive_sha256"]["packets.npz"]:
        raise ValueError(f"{name} inputs differ from the published native receipt")
    row_count, by_packet, by_row = wire_index(raw)
    # Valid header and body determine the two transmitted checksum bytes.
    body_rows = {(q, wire[1:-2]): rows for (q, wire), rows in by_packet.items()}
    coords = {}
    assigned = set()
    with np.load(snapshot, allow_pickle=False) as packet_file:
        for tick, bodies, flags in zip(packet_file["ticks"], packet_file["packets"], packet_file["packet_ok"], strict=True):
            coord = divmod(int(tick), 3)
            for q in np.flatnonzero(flags):
                rows = body_rows.get((q, bodies[q].tobytes()), [])
                if len(rows) != 1 or coords.setdefault(rows[0], coord) != coord:
                    raise ValueError(f"{name} assigned packet lacks a unique row and coordinate")
                assigned.add((*coord, int(q)))
    receipt = dict(msc_sha256=msc_digest, packets_sha256=packet_digest,
                   native_rows=row_count, assigned_packets=len(assigned))
    return Station(by_packet, by_row, coords, assigned, receipt)


def check(case, row_map):
    if sha256((HERE / "protocol.json").read_bytes()).hexdigest() != PROTOCOL_SHA256:
        raise ValueError("alignment selection protocol differs from the frozen version")
    saved = row_map.read_bytes()
    if sha256(saved).hexdigest() != MAP_SHA256:
        raise ValueError("row map differs from the pre-combination map")
    edogawa, yokohama = (station(case, name) for name in STATIONS)
    common = edogawa.packet_rows.keys() & yokohama.packet_rows.keys()
    matching = defaultdict(list)
    for key in common:
        left = edogawa.packet_rows[key]
        right = yokohama.packet_rows[key]
        if len(left) == len(right) == 1:
            matching[left[0], right[0]].append(key[0])
    if len({left for left, _ in matching}) != len(matching) or len({right for _, right in matching}) != len(matching):
        raise ValueError("row correspondence is not one-to-one")
    reconstructed = []
    for (left, right), witnesses in sorted(matching.items()):
        packets_a = edogawa.row_packets[left]
        packets_b = yokohama.row_packets[right]
        same = sorted(packets_a.keys() & packets_b.keys())
        coord_a = edogawa.coordinates.get(left)
        coord_b = yokohama.coordinates.get(right)
        if any(packets_a[q] != packets_b[q] for q in same) or (coord_a and coord_b and coord_a != coord_b):
            raise ValueError("matching evidence conflicts at this row")
        coord = coord_a or coord_b
        cohort = "calibration" if left < 72 else "guard" if left < 84 else "evaluation"
        reconstructed.append(dict(edogawa_row=left, yokohama_row=right, delta=right - left, cohort=cohort,
                                  known_coordinate=list(coord) if coord is not None else None,
                                  old_ledger_sites=[s for s, c in zip(STATIONS, (coord_a, coord_b)) if c is not None],
                                  witness_ordinals=sorted(witnesses), raw_joint=same,
                                  raw_edogawa_only=sorted(packets_a.keys() - packets_b.keys()),
                                  raw_yokohama_only=sorted(packets_b.keys() - packets_a.keys()),
                                  raw_neither=sorted(set(range(4)) - (packets_a.keys() | packets_b.keys()))))
    if reconstructed != json.loads(saved):
        raise ValueError("public transport inputs fail to reproduce the sealed alignment map")
    cohorts = {}
    for group in ("calibration", "guard", "evaluation"):
        rows = [r for r in reconstructed if r["cohort"] == group]
        cohorts[group] = dict(rows=len(rows), quarters=4 * len(rows),
                              **{k: sum(len(r[k]) for r in rows) for k in
                                 ("raw_joint", "raw_edogawa_only", "raw_yokohama_only", "raw_neither")})
    return dict(protocol_sha256=PROTOCOL_SHA256, row_map_sha256=MAP_SHA256,
                stations=dict(edogawa=edogawa.receipt, yokohama=yokohama.receipt),
                shared_assigned_packet_coordinates=len(edogawa.assigned & yokohama.assigned), distinct_matching_wires=len(common),
                ambiguous_matching_wires=len(common) - sum(len(witnesses) for witnesses in matching.values()),
                witnessed_row_count=len(reconstructed), row_offset_counts=dict(Counter(r["delta"] for r in reconstructed)),
                cohorts=cohorts)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case-dir", type=Path, required=True, help="released 12:32 directory with both MSCs, snapshots and native receipts")
    parser.add_argument("--row-map", type=Path, required=True, help="pre-combination row-pairs.json")
    args = parser.parse_args()
    try:
        print(json.dumps(check(args.case_dir, args.row_map), indent=2))
    except (ValueError, KeyError, OSError) as error:
        parser.exit(2, f"{error}\n")
