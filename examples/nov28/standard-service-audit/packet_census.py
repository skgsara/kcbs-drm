"""Count every CRC pass at the four physical 182-byte offsets in each 728-byte callback row."""
import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2] / "scripts"))
from drm_row_alignment import parse_msc
from salvage_msc_packets import PACKET_HEADERS
from tail_fill_audit import crc


def fields(wire):
    h = wire[0]
    return dict(header=f"{h:02X}", first=h >> 7, last=(h >> 6) & 1, packet_id=(h >> 4) & 3,
                ppi=(h >> 3) & 1, ci=h & 7)


def padding(wire, header):
    if not header["ppi"]:
        return "unpadded"
    useful = wire[1]
    if useful > len(wire) - 4:
        return "useful_length_out_of_range"
    if any(wire[2 + useful:-2]):
        return "nonzero_padding"
    if useful:
        return "valid_padded_data"
    if header["first"] and header["last"]:
        return "valid_empty_packet"
    return "empty_without_both_boundary_flags"


def census(rows):
    ids = [0] * 4
    row_sizes, headers, pad, useful = Counter(), Counter(), Counter(), Counter()
    physical = [Counter() for _ in range(4)]
    transitions = {"inside_row": Counter(), "across_rows": Counter()}
    unexpected = []
    wire_ids = {}
    checked = 0
    previous = None
    for row_number, row in enumerate(rows):
        row_sizes[len(row)] += 1
        if len(row) != 728:
            previous = None
            continue
        for ordinal in range(4):
            wire = row[182 * ordinal:182 * (ordinal + 1)]
            checked += 1
            if crc(wire[:-2]) != int.from_bytes(wire[-2:], "big"):
                previous = None
                continue
            header = fields(wire)
            pid, ci = header["packet_id"], header["ci"]
            ids[pid] += 1
            headers[header["header"]] += 1
            physical[ordinal][header["header"]] += 1
            state = padding(wire, header)
            pad[state] += 1
            if header["ppi"]:
                useful[wire[1]] += 1
            if previous is not None and previous["packet_id"] == pid:
                where = "across_rows" if ordinal == 0 else "inside_row"
                transitions[where][f"{previous['ci']}->{ci}"] += 1
            previous = header
            wire_id = sha256(wire).hexdigest()
            wire_ids[wire_id] = pid
            # The historical KCBS header sequence annotates exceptions only after CRC acceptance.
            if wire[0] != PACKET_HEADERS[ordinal]:
                unexpected.append(dict(row=row_number, ordinal=ordinal, **header, padding=state,
                                       declared_useful_bytes=wire[1] if header["ppi"] else None,
                                       transmitted_crc16=wire[-2:].hex(), wire_sha256=wire_id))
    return dict(rows=len(rows), row_sizes=dict(sorted(row_sizes.items())), checked=checked, crc_good=sum(ids),
                crc_failed=checked - sum(ids), by_packet_id=ids, headers=dict(sorted(headers.items())),
                by_ordinal=[dict(sorted(x.items())) for x in physical], padding=dict(sorted(pad.items())),
                padded_declared_length=dict(sorted(useful.items())), neighboring_same_id_ci=transitions,
                unexpected=unexpected), wire_ids


def test_wire(header, data):
    # Independent bitwise encoder of the Annex D G16 CRC, MSB first and complemented on transmission.
    if len(data) != 179:
        raise ValueError("synthetic data field must contain 179 bytes")
    raw = bytes([header]) + data
    reg = 0xFFFF
    for byte in raw:
        reg ^= byte << 8
        for _ in range(8):
            reg = ((reg << 1) ^ (0x1021 if reg & 0x8000 else 0)) & 0xFFFF
    return raw + (reg ^ 0xFFFF).to_bytes(2, "big")


def controls():
    zero = bytes(179)
    rows = [
        [test_wire(0x86, zero), test_wire(0x95, zero), test_wire(0xEF, b"\x02AB" + bytes(176)), test_wire(0xB0, zero)],
        [test_wire(0x47, zero), test_wire(0x56, zero), test_wire(0xF9, zero), test_wire(0xE8, b"\xB3" + bytes(178))],
        [test_wire(0xD8, bytes(178) + b"\x01"), test_wire(0x18, zero), test_wire(0x11, zero), test_wire(0x72, zero)],
    ]
    corrupted = bytearray(rows[1][1])
    corrupted[12] ^= 1
    rows[1][1] = bytes(corrupted)
    result, _ = census([b"".join(r) for r in rows] + [bytes(11)])
    expected_padding = dict(unpadded=6, valid_padded_data=1, valid_empty_packet=1,
                            useful_length_out_of_range=1, nonzero_padding=1, empty_without_both_boundary_flags=1)
    if (result["checked"] != 12 or result["crc_good"] != 11 or result["by_packet_id"] != [2, 4, 2, 3]
            or result["padding"] != expected_padding or result["row_sizes"] != {11: 1, 728: 3}):
        raise ValueError("mixed-ID, corruption, row-size or padding controls failed")
    return result


def run(paths):
    plan = json.loads((HERE / "protocol.json").read_bytes())
    digests = {entry["msc_sha256"]: entry["id"] for entry in plan["cases"]}
    reports = {}
    wires = {}
    for path in paths:
        raw = path.read_bytes()
        digest = sha256(raw).hexdigest()
        name = digests.get(digest)
        if name is None or name in reports:
            raise ValueError(f"unexpected or repeated MSC digest for {path}")
        result, wires[name] = census(parse_msc(raw))
        reports[name] = dict(msc_sha256=digest, **result)
    if set(reports) != set(digests.values()):
        raise ValueError("the five named native MSC inputs are required")
    a, b = (wires['1232-' + station] for station in ('edogawa', 'yokohama'))
    common = a.keys() & b.keys()
    return dict(schema=1, scope="Every CRC-valid physical wire in each selected data-stream callback. "
                "No packet ID, boundary, continuity, padding, data-unit or application checks gate acceptance. "
                "Missing histogram keys have count zero. IDs use ordered bins 0, 1, 2, 3. "
                "Continuity transitions require adjacent good wires of the same ID. Files are counted separately.",
                cases={case["id"]: reports[case["id"]] for case in plan["cases"]},
                same_frequency_1232_distinct_wire_intersection_by_id=[sum(a[h] == i for h in common) for i in range(4)],
                controls=controls())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("msc", nargs="*", type=Path, help="five native MSC files, in any order")
    parser.add_argument("--controls", action="store_true", help="run only the synthetic controls")
    args = parser.parse_args()
    if args.controls and args.msc:
        parser.error("--controls takes no input files")
    try:
        print(json.dumps(controls() if args.controls else run(args.msc), indent=2))
    except (OSError, ValueError) as error:
        parser.exit(2, str(error) + "\n")
