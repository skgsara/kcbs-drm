"""Exercise phase anchoring on generated DRM packet wires and parser barriers."""

from argparse import ArgumentParser
from collections import Counter
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import struct
import sys
from tempfile import TemporaryDirectory

SCRIPTS = Path(__file__).resolve().parents[3] / "scripts"
sys.path.insert(0, str(SCRIPTS))
from salvage_msc_packets import PACKET_HEADERS, crc, records, salvage
from phase_anchors import merge_extra, tagged_assignments


def with_crc(data):
    return data + crc(data).to_bytes(2, "big")


def row(counter, phase, *, nonce=None, bad_packet=None, bad_du=False, unexpected_header=False,
        alter_body_packet=None):
    """Build one native row with unrelated synthetic bytes in all other fields."""
    payload = bytearray(714)
    payload[1] = phase << 4
    payload[20:24] = (counter if nonce is None else nonce).to_bytes(4, "big")
    payload[664:668] = counter.to_bytes(4, "big")
    unit = bytearray(with_crc(bytes(payload)))
    if bad_du:
        unit[-1] ^= 1  # The packet CRCs are computed over this altered byte.

    packets = []
    for q, header in enumerate(PACKET_HEADERS):
        if unexpected_header and q == 2:
            header ^= 0x08
        body = bytearray(unit[179 * q:179 * (q + 1)])
        if q == alter_body_packet:
            body[30] ^= 1
        packet = bytearray(with_crc(bytes([header]) + body))
        if q == bad_packet:
            packet[-1] ^= 1  # Simulate loss of this packet's CRC-qualified observation.
        packets.append(bytes(packet))
    return b"".join(packets)


def write_wires(path, wires):
    path.write_bytes(b"".join(struct.pack("<I", len(wire)) + wire for wire in wires))


def overlay_controls(directory):
    counter = 201
    coordinate = (counter, 0)
    old = row(counter, 0, bad_packet=1)
    added = row(counter, 0, bad_packet=3)
    stock_ordinals = [0, 2, 3]
    cases = {
        "stock_quarantine_stays_absent": (
            [old, row(counter, 0, nonce=99, bad_packet=1)], added,
            [], [], "quarantined_by_stock",
        ),
        "conflict_preserves_old_partial": (
            [old], row(counter, 0, nonce=99, bad_packet=3),
            stock_ordinals, stock_ordinals, "conflicting_packet",
        ),
        "bad_recombined_du_crc_preserves_old_partial": (
            [old], row(counter, 0, bad_packet=3, alter_body_packet=1),
            stock_ordinals, stock_ordinals, "reassembled_du_crc",
        ),
        "valid_recombined_du_completes_old_partial": (
            [old], added, stock_ordinals, [0, 1, 2, 3], None,
        ),
    }
    results = {}
    for name, (original, extension, kept, final, reason) in cases.items():
        stock_wire = directory / "stock.msc.bin"
        write_wires(stock_wire, original)
        stock_dir = directory / name
        with redirect_stdout(io.StringIO()):
            salvage([stock_wire], stock_dir, transport_only=True, save_packets=True)
        stock = {}
        provenance = json.loads((stock_dir / "provenance.json").read_text())
        for key, receipts in provenance.items():
            c, phase, _ = map(int, key.split(","))
            stock.update({i: (c, phase) for _, i in receipts})
        if stock != dict.fromkeys(range(len(original)), coordinate):
            raise ValueError(f"{name}: stock did not assign all expected native rows")

        full_wire = directory / "combined.msc.bin"
        write_wires(full_wire, [*original, extension])
        rows = list(records(full_wire))
        extended, rejected = merge_extra(rows, stock, {len(original): coordinate},
                                         stock_dir / "packets.npz")
        expected = {q: rows[0 if q in kept else -1]["payload"][q] for q in final}
        actual = extended.get(coordinate, {})
        if actual != expected or bool(extended) != bool(expected):
            raise ValueError(f"{name}: output did not preserve the expected packet bytes")
        rejection = [dict(counter=counter, phase=0, extra_rows=[len(original)],
                          reason=reason, preserved_stock_ordinals=kept)] if reason else []
        if rejected != rejection:
            raise ValueError(f"{name}: incorrect overlay rejection {rejected!r}")
        results[name] = dict(stock_ordinals=kept, extended_ordinals=sorted(actual),
                             rejections=rejected)
    return results


def run():
    c = 100
    left, right = row(c, 0), row(c + 1, 0)
    phase1, phase2 = row(0, 1), row(0, 2)
    next_phase1, next_phase2 = row(0, 1, nonce=1), row(0, 2, nonce=1)
    opaque = row(c + 9, 9, bad_packet=0)
    wrap = (1 << 32) - 1
    cases = {
        "counter_packet_missing": (
            [left, phase1, phase2, row(c + 7, 0, bad_packet=3),
             next_phase1, next_phase2, row(c + 2, 0)],
            {1: (c, 1), 2: (c, 2), 3: (c + 1, 0), 4: (c + 1, 1), 5: (c + 1, 2)},
            {},
        ),
        "explicit_phase_2_after_dropped_phase_1": ([left, phase2, right], {1: (c, 2)}, {}),
        "two_counters_leave_a_lone_phase_ambiguous": (
            [left, phase1, row(c + 2, 0)], {}, {},
        ),
        "phase_tag_invalid_inside_bracket": ([left, row(0, 3), right], {}, {}),
        "phase_tag_out_of_order_after_opaque_prefix": (
            [left, opaque, phase2, phase1, right], {}, {},
        ),
        "duplicated_tag_for_one_counter": ([left, phase1, phase1, right], {}, {}),
        "duplicated_packet_after_dropped_callbacks": (
            [left, phase1, phase1, row(c + 2, 0)], {}, {},
        ),
        "opaque_callback_after_dropped_phase": ([left, opaque, right], {}, {}),
        "bad_q0_does_not_assign_even_if_geometry_fits": (
            [left, row(0, 1, bad_packet=0), phase2, right], {2: (c, 2)}, {},
        ),
        "non_728_callback_barrier": ([left, b"other stream", phase2, right], {}, {}),
        "bad_du_crc_barrier": (
            [left, row(0, 1, bad_du=True), phase2, right], {}, {"complete_du_crc": 1},
        ),
        "valid_crc_wrong_header_barrier": (
            [left, row(0, 1, unexpected_header=True), phase2, right], {},
            {"unexpected_packet_header": 1},
        ),
        "modular_wrap": ([row(wrap, 0), phase1, phase2, row(0, 0)],
                         {1: (wrap, 1), 2: (wrap, 2)}, {}),
        "modular_wrap_missing_inner_counter": (
            [row(wrap, 0), phase1, phase2, row(c, 0, bad_packet=3),
             next_phase1, next_phase2, row(1, 0)],
            {1: (wrap, 1), 2: (wrap, 2), 3: (0, 0), 4: (0, 1), 5: (0, 2)},
            {},
        ),
    }

    results = {}
    with TemporaryDirectory(prefix="phase-anchors-controls-") as temp:
        wire_path = Path(temp) / "test.msc.bin"
        for name, (wires, expected, expected_rejections) in cases.items():
            write_wires(wire_path, wires)
            rejected = Counter()
            parsed = list(records(wire_path, rejected_records=rejected))
            if len(parsed) != len(wires) or rejected != expected_rejections:
                raise ValueError(f"{name}: stock parser disagrees with fixture: {rejected}")
            actual = tagged_assignments(parsed)
            if actual != expected:
                raise ValueError(f"{name}: expected {expected!r}, got {actual!r}")
            if any(not parsed[i]["packet_ok"][0] for i in actual):
                raise ValueError(f"{name}: assignment without a CRC-good phase tag")
            results[name] = dict(assignments=actual, stock_parser_rejections=dict(rejected))
        results.update(overlay_controls(Path(temp)))
    return dict(passed=len(results), cases=results)


if __name__ == "__main__":
    cli = ArgumentParser(description=__doc__)
    cli.parse_args()
    print(json.dumps(run(), indent=2))
