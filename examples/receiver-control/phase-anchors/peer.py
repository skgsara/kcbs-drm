"""Compare single-receiver phase-bracket additions with the opposite station's stock assignments."""
import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
EXAMPLES = HERE.parents[1]
sys.path.insert(0, str(EXAMPLES.parent / "scripts"))
from drm_row_alignment import parse_msc, valid_packets
from salvage_msc_packets import crc
from phase_anchors import read_assignments


CASES = {
    "12:32 6140 kHz": {
        "Edogawa": ("nov28/same-6140-1232/edogawa-msc.bin", "ffd62e982e8dbd4d415d0c1d51a81b10bb380244bc2fcab8248ce48a5ec86172"),
        "Yokohama": ("nov28/same-6140-1232/yokohama-msc.bin", "267261e04afc6f48ef05a547f7784feb4cc9cf39401bf518697992153bdb0c64"),
    },
    "21:26 3205 kHz": {
        "Yokohama": ("nov28/packet-bit-repair/peer-2126/primary.msc.bin", "b1c5bcb0d4c8bbf22841e75c1dea491a93f7ead03a402d04c82698a84ec9b9f9"),
        "Edogawa": ("nov28/packet-bit-repair/peer-2126/witness.msc.bin", "c36d4f0763a02d87b28d4afb033140fae970666bcc73c8dfb50df1e1a107e7fc"),
    },
}


def packet_index(rows, assignments):
    packets, origins = {}, defaultdict(list)
    by_tick = defaultdict(dict)
    for row, (counter, phase) in sorted(assignments.items()):
        for ordinal, wire in rows[row].items():
            key = (counter, phase, ordinal)
            if packets.setdefault(key, wire) != wire:
                raise ValueError(f"conflicting source wires at {key}")
            origins[key].append(row)
            by_tick[counter, phase][ordinal] = wire
    for tick, received in by_tick.items():
        if len(received) == 4:
            unit = b"".join(received[q][1:-2] for q in range(4))
            if crc(unit[:-2]) != int.from_bytes(unit[-2:], "big"):
                raise ValueError(f"failed reassembled DU CRC at {tick}")
    return packets, origins


@dataclass
class Site:
    name: str
    stock: dict
    stock_rows: dict
    added: dict
    extra_rows: dict
    origins: dict
    raw: list
    wire_frequency: Counter
    complete_groups: dict


def load_site(name, path, expected):
    raw = path.read_bytes()
    if sha256(raw).hexdigest() != expected:
        raise ValueError(f"wrong native MSC for {path.name}")
    parsed, stock, extra = read_assignments(path)
    wires = [valid_packets(row) for row in parse_msc(raw)]
    if len(parsed) != len(wires):
        raise ValueError("native row indexing differs")
    for row in stock.keys() | extra.keys():
        if parsed[row] is None or set(wires[row]) != {q for q, ok in enumerate(parsed[row]["packet_ok"]) if ok}:
            raise ValueError(f"receipt flags differ from physical packet CRCs at row {row}")
    baseline, origins = packet_index(wires, stock)
    augmented, _ = packet_index(wires, stock | extra)
    added = {key: wire for key, wire in augmented.items() if key not in baseline}
    complete_groups = {}
    for i in range(len(parsed) - 2):
        triple = parsed[i:i+3]
        if all(r and r["complete"] for r in triple) and [r["phase"] for r in triple] == [0, 1, 2]:
            for phase in range(3):
                complete_groups[i + phase] = (triple[0]["counter"], phase)
    return Site(name, baseline, stock, added, extra, origins, wires,
                Counter(key for packets in wires for key in packets.items()), complete_groups)


def compare(site, peer):
    totals = Counter(added=0, equal=0, different=0, peer_missing=0, equal_unique_wire_at_both=0,
                     equal_in_peer_native_complete_group=0)
    row_counts = Counter(extra=0, some_peer_equal=0, has_peer_disagreement=0, wholly_unchecked=0)
    ledger = []
    seen = set()
    fingerprint = sha256()
    for row, (counter, phase) in sorted(site.extra_rows.items()):
        equal, different, missing = [], [], []
        peer_rows = set()
        for ordinal in sorted(site.raw[row]):
            key = (counter, phase, ordinal)
            if key in seen or key not in site.added:
                continue
            seen.add(key)
            wire = site.added[key]
            reference = peer.stock.get(key)
            other_rows = peer.origins.get(key, [])
            peer_rows.update(other_rows)
            totals["added"] += 1
            if reference is None:
                missing.append(ordinal)
                totals["peer_missing"] += 1
            elif wire != reference:
                different.append(ordinal)
                totals["different"] += 1
            else:
                equal.append(ordinal)
                totals["equal"] += 1
                signature = (ordinal, wire)
                totals["equal_unique_wire_at_both"] += site.wire_frequency[signature] == peer.wire_frequency[signature] == 1
                totals["equal_in_peer_native_complete_group"] += any(
                    peer.complete_groups.get(i) == (counter, phase) for i in other_rows)
            # Bind all 182 wire bytes and physical row origins, including missing and unequal observations.
            proof = [row, *key, sha256(wire).hexdigest(), other_rows,
                     sha256(reference).hexdigest() if reference is not None else None]
            fingerprint.update((json.dumps(proof, separators=(",", ":")) + "\n").encode("ascii"))
        row_counts["extra"] += 1
        if different:
            row_counts["has_peer_disagreement"] += 1
        elif equal:
            row_counts["some_peer_equal"] += 1
        else:
            row_counts["wholly_unchecked"] += 1
        ledger.append([row, counter, phase, equal, different, missing, sorted(peer_rows)])
    if seen != site.added.keys():
        raise ValueError("packet ledger omitted an addition")
    return dict(source=site.name, peer=peer.name, source_stock_rows=len(site.stock_rows),
                source_stock_packets=len(site.stock), row_totals=dict(row_counts), packet_totals=dict(totals),
                wire_ledger_sha256=fingerprint.hexdigest(), rows=ledger)


def study():
    comparisons = {}
    overall = Counter()
    for label, stations in CASES.items():
        left, right = [load_site(name, EXAMPLES / path, digest) for name, (path, digest) in stations.items()]
        directions = [compare(left, right), compare(right, left)]
        for direction in directions:
            overall.update(direction["packet_totals"])
        comparisons[label] = dict(inputs={name: dict(path=path, sha256=digest) for name, (path, digest) in stations.items()},
                                  directions=directions)
    return dict(format="phase-anchor-peer-v1",
                basis="Both primary directions are frozen using one original receiver at a time. The independent "
                      "peer supplies only its stock counter, phase and ordinal. Comparisons cover whole 182-byte "
                      "wires already passing physical header and CRC. Counts are directional site observations.",
                row_fields=["source_row", "counter", "phase", "equal_ordinals", "different_ordinals", "missing_ordinals",
                            "peer_stock_rows"], totals=dict(overall), cases=comparisons)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", type=Path, help="verify against an existing JSON receipt")
    args = parser.parse_args()
    result = study()
    if args.check:
        if result != json.loads(args.check.read_bytes()):
            parser.exit(1, "receipt differs from the reconstructed packet and row results\n")
        print(json.dumps(result["totals"], sort_keys=True))
    else:
        print(json.dumps(result, indent=2))
