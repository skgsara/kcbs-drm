"""Export the reconstructed DU for each sealed proposal, retaining its native-row provenance."""
import argparse
import json
from pathlib import Path
import struct
import sys

from solve import ROOT, PACKET_BYTES, digest, flip, parse_msc, sealed, syndrome, valid_packets

sys.path.insert(0, str(ROOT / "examples/nov28/packet-bit-repair"))
from peer import physical_field


def export(raw_a, raw_b, decisions, seal, out):
    proposal = sealed(raw_a, raw_b, decisions, seal)
    primary, alternate = parse_msc(raw_a), parse_msc(raw_b)
    material = {}
    rows = []
    for p in proposal["proposals"]:
        i, j, q = p["primary_row"], p["alternate_row"], p["ordinal"]
        source_row = primary[i]
        wire = source_row[q * PACKET_BYTES:(q + 1) * PACKET_BYTES]
        updated = flip(wire, p["primary_flips_msb0"])
        if digest(updated) != p["proposed_wire_sha256"]:
            raise ValueError("wire mismatch")
        sources = {"primary": valid_packets(source_row), "alternate": valid_packets(alternate[j])}
        quartet = {int(k): sources[name][int(k)] for k, name in p["sibling_sources"].items()}
        quartet[q] = updated
        row = b"".join(quartet[k] for k in range(4))
        unit = b"".join(quartet[k][1:-2] for k in range(4))
        if len(valid_packets(row)) != 4 or syndrome(unit) or digest(unit) != p["proposed_du_sha256"]:
            raise ValueError("assembled row mismatch")
        phase = unit[1] >> 4
        changed = []
        for bit in p["primary_flips_msb0"]:
            field = physical_field(q, bit // 8, (None, phase) if phase <= 2 else None)
            if "word_octet" in field:
                field["physical_word_bit_msb0"] = 8 * field["word_octet"] + bit % 8
                field["payload_offset_excluding_mode"] = field["word_octet"] - 1 if field["word_octet"] else None
            changed.append(dict(wire_bit_msb0=bit, **field))
        du_file = f"row-{i:06d}.du"
        if du_file in material:
            raise ValueError("unexpected multiple complete-DU proposals for one row")
        material[du_file] = unit
        rows.append(dict(primary_row=i, alternate_row=j, repaired_ordinal=q, phase_tag=phase,
                         counter_if_transmitted_here=int.from_bytes(unit[664:668], "big") if phase == 0 else None,
                         file=du_file, du_sha256=digest(unit), transmitted_du_crc=unit[-2:].hex(),
                         changed_physical_bits=changed, sibling_sources=p["sibling_sources"]))
        primary[i] = row
    overlay = b"".join(struct.pack("<I", len(row)) + row for row in primary)
    material["proposed.msc.bin"] = overlay
    report = dict(decision_sha256=seal.lower(), primary_msc_sha256=digest(raw_a), alternate_msc_sha256=digest(raw_b),
                  proposed_msc_sha256=digest(overlay), rows=rows,
                  scope="Diagnostic DU and native-stream overlays. Unlisted primary rows are unchanged. "
                        "Each listed row uses the proposed packet and its CRC-valid source siblings. "
                        "Absolute counters need separate transport assignment except where transmitted in phase 0.")
    out.mkdir(parents=True, exist_ok=False)
    for name, data in material.items():
        (out / name).write_bytes(data)
    (out / "material.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("primary", type=Path)
    cli.add_argument("alternate", type=Path)
    cli.add_argument("decisions", type=Path)
    cli.add_argument("--seal", required=True)
    cli.add_argument("--out", type=Path, required=True, help="new output directory")
    a = cli.parse_args()
    result = export(a.primary.read_bytes(), a.alternate.read_bytes(), a.decisions, a.seal, a.out)
    print(json.dumps(result, indent=2))
