"""Seal Edogawa-only MLC4 coordinate changes, then score the sealed gains on Yokohama."""
import argparse
from collections import Counter
from dataclasses import dataclass
import gzip
from hashlib import sha256
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "scripts"))
from drm_row_alignment import read_msc, valid_packets
from project_evs_group import checked_units
from received_evs_packets import read_packet_snapshot
from salvage_msc_packets import salvage

CASE = ROOT / "examples/nov28/same-6140-1232"
NATIVE = {
    "edogawa": "ffd62e982e8dbd4d415d0c1d51a81b10bb380244bc2fcab8248ce48a5ec86172",
    "yokohama": "267261e04afc6f48ef05a547f7784feb4cc9cf39401bf518697992153bdb0c64",
}


def digest(data):
    return sha256(data).hexdigest()


def require(test, message):
    if not test:
        raise ValueError(message)


@dataclass
class Capture:
    file_sha256: str
    packets: dict
    units: dict
    rows: dict
    native_wires: set
    quarantined: set
    report: dict


def capture(path, published_station=None):
    """Resolve coordinates using only one MSC and verify every accepted wire in the native row."""
    path = path.resolve()
    file_sha = digest(path.read_bytes())
    if published_station:
        require(file_sha == NATIVE[published_station], "native input differs from the published source")
    wires = [valid_packets(row) for row in read_msc(path)]
    packets, origins, assembled = {}, {}, {}
    with TemporaryDirectory() as directory:
        out = Path(directory) / "transport"
        salvage([path], out, transport_only=True, save_packets=True)
        provenance = json.loads((out / "provenance.json").read_bytes())
        report = json.loads((out / "report.json").read_bytes())
        ticks, data, flags = read_packet_snapshot(out / "packets.npz")
        if published_station:
            expected = read_packet_snapshot(CASE / f"{published_station}-packets.npz")
            require(all((a.shape == b.shape and (a == b).all())
                        for a, b in zip((ticks, data, flags), expected, strict=True)),
                    "assigned packets differ from saved baseline")
        for tick, unit, good in zip(ticks, data, flags, strict=True):
            coord = divmod(int(tick), 3)
            for q, ok in enumerate(good):
                if not ok:
                    continue
                key = (*coord, q)
                body = bytes(unit[179*q:179*(q+1)])
                evidence = provenance[",".join(map(str, key))]
                rows = []
                for source, index in evidence:
                    require(Path(source).resolve() == path and 0 <= index < len(wires), "wrong provenance source or row")
                    wire = wires[index].get(q)
                    require(wire is not None and wire[1:-2] == body, "wire CRC, ordinal or body disagrees")
                    require(packets.setdefault(key, wire) == wire, "conflicting accepted wires")
                    rows.append(index)
                require(rows, "accepted packet lacks a source")
                origins[key] = sorted(set(rows))
            if all(good):
                assembled[coord] = b"".join(packets[(*coord,q)][1:-2] for q in range(4))
        units = {(c,p): du for c,p,du in checked_units(out / "data_units.npz")}
        require(assembled == units, "received packet bodies differ from the checked DU archive")
        assigned = {tuple(map(int, key.split(",")))[:2] for key in provenance}
        quarantined = assigned - {divmod(int(t), 3) for t in ticks}
        conflicts = set(map(tuple, report["conflicting_data_units"]))
        require(conflicts <= quarantined and len(quarantined - conflicts) == report["reassembly_crc_failures"],
                "unexpected excluded coordinate")
    summary = {key: report[key] for key in ("assigned_record_observations", "conflicting_data_units", "reassembly_crc_failures")}
    summary.update(native_rows=len(wires), physical_good_packet_occurrences=sum(map(len,wires)),
                   accepted_packets=len(packets), accepted_dus=len(units), quarantined_phases=sorted(quarantined))
    return Capture(file_sha, packets, units, origins, {wire for row in wires for wire in row.values()}, quarantined, summary)


def decision_rows(before, after, kind):
    old = getattr(before, kind)
    new = getattr(after, kind)
    rows = []
    for key in sorted(old.keys() | new.keys()):
        lhs, rhs = old.get(key), new.get(key)
        if lhs is None:
            outcome = "added"
        elif rhs is None:
            outcome = "lost"
        else:
            outcome = "equal" if lhs == rhs else "conflicting"
        row = dict(coordinate=list(key), status=outcome,
                   mlc1_sha256=digest(lhs) if lhs is not None else None,
                   mlc4_sha256=digest(rhs) if rhs is not None else None)
        if rhs is not None:
            row["mlc4_transmitted_crc"] = rhs[-2:].hex()
        if kind == "packets" and outcome == "added":
            row["mlc4_native_rows"] = after.rows[key]
            row["same_valid_wire_anywhere_in_mlc1"] = rhs in before.native_wires
        rows.append(row)
    return rows


def decision(before, after):
    result = dict(format="edogawa-mlc4-transport-decisions-v1", coordinate_order="counter, phase [, packet ordinal]",
                  mlc1_sha256=before.file_sha256, mlc4_sha256=after.file_sha256, mlc1=before.report, mlc4=after.report)
    for kind in ("packets", "units"):
        rows = decision_rows(before, after, kind)
        counts = Counter({status: 0 for status in ("added","lost","equal","conflicting")})
        counts.update(r["status"] for r in rows)
        result[kind] = dict(counts=counts, rows=rows)
    return result


def serialize(result):
    return (json.dumps(result, separators=(",",":"), sort_keys=True) + "\n").encode()


def score(decisions, before, after, peer):
    result = dict(format="edogawa-mlc4-independent-peer-v1", peer_msc_sha256=peer.file_sha256, peer=peer.report)
    for kind in ("packets", "units"):
        candidates = getattr(after,kind)
        baseline = getattr(before,kind)
        reference = getattr(peer,kind)
        counts = Counter({status: 0 for status in ("exact","disagreement","no_peer_receipt","peer_phase_quarantined")})
        rows = []
        for item in decisions[kind]["rows"]:
            if item["status"] != "added":
                continue
            key = tuple(item["coordinate"])
            value = candidates[key]
            require(key not in baseline, "non-gain in peer comparison")
            actual = reference.get(key)
            if actual is None:
                status = "peer_phase_quarantined" if key[:2] in peer.quarantined else "no_peer_receipt"
            else:
                status = "exact" if value == actual else "disagreement"
            counts[status] += 1
            row = dict(coordinate=list(key), outcome=status, mlc4_sha256=digest(value),
                       peer_sha256=digest(actual) if actual is not None else None)
            if kind == "packets":
                row["same_valid_wire_anywhere_in_mlc1"] = item["same_valid_wire_anywhere_in_mlc1"]
            rows.append(row)
        result[kind] = dict(counts=counts, rows=rows)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("seal", "score"))
    parser.add_argument("mlc4_msc", type=Path)
    parser.add_argument("seal", type=Path, help="deterministic gzip of every Edogawa coordinate decision")
    parser.add_argument("--out", type=Path, help="score JSON for the independent peer stage")
    args = parser.parse_args()
    before = capture(CASE / "edogawa-msc.bin", "edogawa")
    after = capture(args.mlc4_msc)
    decisions = decision(before, after)
    encoded = serialize(decisions)
    if args.operation == "seal":
        if args.out:
            parser.error("--out applies to score")
        with args.seal.open("xb") as f:
            with gzip.GzipFile(filename="", mode="wb", fileobj=f, mtime=0) as writer:
                writer.write(encoded)
        print("Edogawa decisions SHA-256 (uncompressed)",digest(encoded))
        print({k:decisions[k]["counts"] for k in ("packets","units")})
        return
    if args.out is None:
        parser.error("score requires --out")
    require(gzip.decompress(args.seal.read_bytes()) == encoded, "Edogawa decisions differ from the seal")
    peer = capture(CASE / "yokohama-msc.bin", "yokohama")
    result = score(decisions, before, after, peer)
    result.update(decisions_sha256=digest(encoded), decisions_gzip_sha256=digest(args.seal.read_bytes()))
    with args.out.open("x") as f:
        f.write(json.dumps(result, indent=2) + "\n")
    print({k:result[k]["counts"] for k in ("packets","units")})


if __name__ == "__main__":
    main()
