"""Verify consecutive native groups and compare their full wire bytes across the two 6140 kHz dumps."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2] / "scripts"))
from received_evs_packets import read_packet_snapshot
from salvage_msc_packets import PACKET_HEADERS
from tail_fill_audit import crc


def require(ok, message):
    if not ok:
        raise ValueError(message)


def checked_bytes(path, expected):
    data = path.read_bytes()
    require(sha256(data).hexdigest() == expected, f"{path.name}: SHA-256 differs from published receipt")
    return data


def valid_crc(wire):
    return crc(wire[:-2]) == int.from_bytes(wire[-2:], "big")


def native_groups(dump):
    """Keep complete phase 0/1/2 triples in file order. Invalid intervening rows break a triple."""
    rows = []
    offset = good_dus = packet_checks = good_crc = good_headers_and_crc = 0
    while offset < len(dump):
        require(offset + 4 <= len(dump), "truncated MSC record length")
        size = int.from_bytes(dump[offset:offset + 4], "little")
        offset += 4
        require(0 < size <= 1024 * 1024 and offset + size <= len(dump), "invalid or truncated MSC record")
        wire = dump[offset:offset + size]
        offset += size
        rows.append(None)
        if size != 728:
            continue
        packets = [wire[i:i + 182] for i in range(0, size, 182)]
        crc_flags = [valid_crc(packet) for packet in packets]
        flags = [ok and packet[0] == header for packet, header, ok in zip(packets, PACKET_HEADERS, crc_flags, strict=True)]
        packet_checks += len(packets)
        good_crc += sum(crc_flags)
        good_headers_and_crc += sum(flags)
        if all(flags):
            du = b"".join(packet[1:-2] for packet in packets)
            if valid_crc(du):
                rows[-1] = (du[1] >> 4, du, wire)
                good_dus += 1

    receipts, wires, units = [], {}, {}
    for start in range(len(rows) - 2):
        triple = rows[start:start + 3]
        if any(row is None for row in triple) or [row[0] for row in triple] != [0, 1, 2]:
            continue
        counter = int.from_bytes(triple[0][1][664:668], "big")
        raw = tuple(row[2] for row in triple)
        require(wires.setdefault(counter, raw) == raw, f"conflicting native copies of {counter}")
        units[counter] = tuple(row[1] for row in triple)
        receipts.append(dict(counter=counter, phase0_row=start, du_sha256=[sha256(du).hexdigest() for du in units[counter]]))
    counts = dict(msc_rows=len(rows), packet_crc_checks=packet_checks, physical_packets_crc=good_crc,
                  physical_packets_crc_and_header=good_headers_and_crc, native_complete_dus=good_dus)
    return counts, receipts, wires, units


def replay(edogawa, yokohama, case=HERE):
    comparison = json.loads((case / "comparison.json").read_bytes())
    sites, groups = {}, {}
    for site, path in (("edogawa", edogawa), ("yokohama", yokohama)):
        receipt = json.loads(checked_bytes(case / f"{site}-native.json", comparison["stations"][site]))
        dump = checked_bytes(path, receipt["msc_sha256"])
        counts, receipts, groups[site], units = native_groups(dump)
        require(all(receipt[k] == value for k, value in counts.items()), f"{site}: native counts differ")
        require(receipts == receipt["direct_complete_groups"], f"{site}: chronological groups or DU digests differ")

        packets = case / f"{site}-packets.npz"
        checked_bytes(packets, receipt["archive_sha256"]["packets.npz"])
        ticks, bodies, flags = read_packet_snapshot(packets)
        complete = {int(tick): body.tobytes() for tick, body, present in zip(ticks, bodies, flags, strict=True) if present.all()}
        for counter, triple in units.items():
            for phase, du in enumerate(triple):
                require(complete.get(3 * counter + phase) == du, f"{site}: accepted archive differs at {counter}/{phase}")
        sites[site] = dict(msc_sha256=receipt["msc_sha256"], **counts, native_groups=len(groups[site]))
        if site == "edogawa":
            primary = receipts[0] if receipts else None

    require(primary == comparison["primary"], "earliest chronological Edogawa group differs")
    left, right = groups["edogawa"], groups["yokohama"]
    shared = left.keys() & right.keys()
    union = len(left.keys() | right.keys())
    require(sorted(shared) == comparison["direct_complete_group_ids_both"], "shared native counter list differs")
    require(union == comparison["union_direct_complete_group_count"], "native counter union differs")
    for counter in shared:
        require(left[counter] == right[counter], f"native wire bytes differ at counter {counter}")
    if primary is not None and primary["counter"] in shared:
        require(comparison["primary_peer_receipt"] == dict(packets=12, matching_packets=12, complete_dus=3,
                                                          equal_dus=3, full_native=True), "primary peer receipt differs")
    return dict(stations=sites, primary=primary, primary_native_at_both=bool(primary and primary["counter"] in shared),
                native_groups_union=union, identical_shared_groups=len(shared), identical_shared_dus=3 * len(shared),
                identical_shared_wire_packets=12 * len(shared))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("edogawa", type=Path, help="unmodified Edogawa MSC dump")
    parser.add_argument("yokohama", type=Path, help="unmodified Yokohama MSC dump")
    parser.add_argument("--case", type=Path, default=HERE, help="directory containing the published receipts and packets")
    args = parser.parse_args()
    try:
        print(json.dumps(replay(args.edogawa, args.yokohama, args.case), indent=2))
    except (ValueError, OSError) as error:
        parser.exit(1, f"{error}\n")
