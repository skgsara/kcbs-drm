"""Try a single RF hard-bit correction in a 728-byte DRM callback row."""
from argparse import ArgumentParser
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import struct
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))
from drm_row_alignment import PACKET_BYTES, ROW_BYTES, parse_msc
from salvage_msc_packets import PACKET_HEADERS, crc


def syndrome(wire):
    return crc(wire[:-2]) ^ int.from_bytes(wire[-2:], "big")


def flipped(data, bit):
    changed = bytearray(data)
    changed[bit // 8] ^= 0x80 >> (bit % 8)
    return bytes(changed)


def single_bit_positions():
    # The affine CRC offset cancels when the all-zero and flipped words are XORed.
    zero = bytes(PACKET_BYTES)
    baseline = syndrome(zero)
    table = {}
    for bit in range(8 * PACKET_BYTES):
        difference = syndrome(flipped(zero, bit)) ^ baseline
        if not difference or difference in table:
            raise ValueError("CRC does not distinguish every single bit at this packet length")
        table[difference] = bit
    return table


def repair_row(row, positions):
    if len(row) != ROW_BYTES:
        return row, "other_row_length", None
    wires = [row[start:start + PACKET_BYTES] for start in range(0, ROW_BYTES, PACKET_BYTES)]
    checks = [syndrome(wire) for wire in wires]
    failed = [q for q, value in enumerate(checks) if value]
    if not failed:
        return row, "all_packet_crcs_pass", None
    if len(failed) != 1:
        return row, "multiple_failed_packet_crcs", None
    q = failed[0]
    bit = positions.get(checks[q])
    if bit is None:
        return row, "no_single_bit_candidate", None
    wires[q] = flipped(wires[q], bit)
    if tuple(w[0] for w in wires) != PACKET_HEADERS:
        return row, "unexpected_header", None
    if syndrome(wires[q]):
        raise ValueError("single-bit correction did not clear the packet syndrome")
    unit = b"".join(w[1:-2] for w in wires)
    if syndrome(unit):
        return row, "data_unit_crc_failed", None
    changed_byte = bit // 8
    data_offset = None if changed_byte in (0, 180, 181) else q * 179 + changed_byte - 1
    change = dict(packet_ordinal=q, wire_bit_msb0=bit, data_unit_byte=data_offset,
                  original_packet_sha256=sha256(row[q * PACKET_BYTES:(q + 1) * PACKET_BYTES]).hexdigest(),
                  proposed_packet_sha256=sha256(wires[q]).hexdigest())
    return b"".join(wires), "single_bit_proposed", change


def repair(raw):
    positions = single_bit_positions()
    output = bytearray()
    counts = Counter()
    changes = []
    for index, row in enumerate(parse_msc(raw)):
        result, reason, change = repair_row(row, positions)
        counts[reason] += 1
        if change is not None:
            changes.append(dict(native_row=index, **change))
        output.extend(struct.pack("<I", len(result)))
        output.extend(result)
    return bytes(output), dict(original_msc_sha256=sha256(raw).hexdigest(),
                               proposed_msc_sha256=sha256(output).hexdigest(), rows=sum(counts.values()),
                               row_outcomes=counts, changes=changes)


if __name__ == "__main__":
    parser = ArgumentParser(description=__doc__)
    for name in ("original", "proposed", "report"):
        parser.add_argument(name, type=Path)
    args = parser.parse_args()
    paths = {p.resolve() for p in (args.original, args.proposed, args.report)}
    if len(paths) != 3 or args.proposed.exists() or args.report.exists():
        parser.error("use two distinct, new output files")
    transformed, report = repair(args.original.read_bytes())
    with args.proposed.open("xb") as stream:
        stream.write(transformed)
    with args.report.open("x") as stream:
        print(json.dumps(report, indent=2), file=stream)
