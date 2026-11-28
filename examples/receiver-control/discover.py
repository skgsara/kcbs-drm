"""Catalog native complete EVS groups after verifying the authored clear EF0201 service."""
from collections import Counter, defaultdict
from hashlib import sha256
import json
from pathlib import Path
import sys

import numpy as np

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS))
from drm_row_alignment import PACKET_BYTES, ROW_BYTES, parse_msc, valid_packets
from render_continuous import MODE_POSITIONS, PACKET_STARTS
from salvage_msc_packets import PACKET_HEADERS, crc
from speech_presence_test import write_g192


def exact_guard_stamp(unit, phase):
    """Mirror transmitter/msc_to_iq.cpp guard(): all bytes, including the repeated stamp."""
    stamp = unit[668:672]
    expected = bytearray(714)
    expected[1] = phase << 4
    if phase == 0:
        expected[664:668] = stamp
    expected[668:672] = stamp
    return int.from_bytes(stamp, "big") if unit[:714] == expected else None


def inspect_row(index, wire):
    packets = valid_packets(wire)
    details = dict(native_row=index, accepted_ordinals=sorted(packets), received_phase=None,
                   phase0_counter=None, status="unsupported_length")
    if len(wire) != ROW_BYTES:
        return details, None
    for q, header in enumerate(PACKET_HEADERS):
        packet = wire[q * PACKET_BYTES:(q + 1) * PACKET_BYTES]
        if packet[0] != header and crc(packet[:-2]) == int.from_bytes(packet[-2:], "big"):
            details["status"] = "unexpected_crc_valid_header"
            return details, None
    unit = None
    if len(packets) == 4:
        unit = b"".join(packets[q][1:-2] for q in range(4))
        if crc(unit[:-2]) != int.from_bytes(unit[-2:], "big"):
            details["status"] = "failed_du_crc"
            return details, None
    if 0 in packets:
        phase = packets[0][2] >> 4
        if phase not in (0, 1, 2):
            details["status"] = "invalid_phase"
            return details, None
        details["received_phase"] = phase
        if phase == 0 and 3 in packets:
            details["phase0_counter"] = int.from_bytes(packets[3][128:132], "big")
    if unit is not None:
        details["status"] = "complete_du_outside_native_triple"
    else:
        details["status"] = "partial_packets" if packets else "no_accepted_packets"
    return details, unit


def write_words(path, units):
    frames = b"".join(unit[mode:mode + 1] + unit[payload:payload + 32] for unit in units
                      for mode, payload in zip(MODE_POSITIONS, PACKET_STARTS, strict=True))
    write_g192(path, np.frombuffer(frames, dtype=np.uint8).reshape(60, 33), [True] * 60)
    return sha256(path.read_bytes()).hexdigest()


def discover(msc: Path, out: Path) -> dict:
    """Write a sparse on-wire catalog to a fresh directory. Caller must verify the fixture service first."""
    raw = Path(msc).read_bytes()
    rows = [inspect_row(i, wire) for i, wire in enumerate(parse_msc(raw))]
    out = Path(out)
    out.mkdir(parents=True, exist_ok=False)
    covered_rows = set()
    groups = []
    occurrences = defaultdict(list)
    run = 0
    for i in range(len(rows) - 2):
        triple = rows[i:i + 3]
        if any(unit is None for _, unit in triple) or [r["received_phase"] for r, _ in triple] != [0, 1, 2]:
            continue
        units = [unit for _, unit in triple]
        counter = triple[0][0]["phase0_counter"]
        stamps = [exact_guard_stamp(unit, phase) for phase, unit in enumerate(units)]
        if stamps == [counter] * 3:
            kind = "guard"
        elif any(stamp is not None for stamp in stamps):
            kind = "mixed_guard_quarantined"
        else:
            kind = "declared_clear"
        previous = groups[-1] if groups else None
        row_gap = None if previous is None else i - previous["phase0_row"] - 3
        next_counter = None if previous is None else counter == (previous["counter"] + 1) % (1 << 32)
        if previous is not None and (row_gap != 0 or not next_counter or kind != previous["kind"]):
            run += 1
        group = dict(phase0_row=i, counter=counter, run=run, preceding_unselected_rows=row_gap,
                     counter_follows_mod_uint32=next_counter, kind=kind, guard_stamps=stamps,
                     du_sha256=[sha256(unit).hexdigest() for unit in units])
        if kind == "declared_clear":
            name = f"row-{i:06d}-counter-{counter:08x}.192"
            group.update(g192=name, g192_sha256=write_words(out / name, units))
        groups.append(group)
        occurrences[counter].append(group)
        covered_rows.update(range(i, i + 3))

    repeated = [dict(counter=c, native_starts=[g["phase0_row"] for g in hits],
                     identical_data_units=len({tuple(g["du_sha256"]) for g in hits}) == 1)
                for c, hits in occurrences.items() if len(hits) > 1]
    unselected = [r for r, _ in rows if r["native_row"] not in covered_rows]
    kinds = Counter(g["kind"] for g in groups)
    report = dict(format="ef0201-native-group-catalog-v1", native_msc_sha256=sha256(raw).hexdigest(),
                  native_rows=len(rows), complete_native_triples=len(groups),
                  declared_clear_groups=kinds["declared_clear"], guard_groups=kinds["guard"],
                  mixed_guard_groups=kinds["mixed_guard_quarantined"], supplied_words=60 * kinds["declared_clear"],
                  groups=groups, repeated_counters=repeated, unselected_rows=unselected,
                  unselected_by_status=dict(Counter(r["status"] for r in unselected)),
                  scope="Native row order, all four original canonical packet CRCs and the DU CRC in each phase. "
                        "Runs break on missing rows, a counter discontinuity, or a change of group kind. "
                        "Guard matching uses the authored transmitter's full DU pattern. "
                        "Partial and unplaced rows supply no EVS words here.")
    (out / "catalog.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report
