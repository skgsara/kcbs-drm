"""Audit the sealed development proposals against the original two-station row map and wire packets."""
import json
from collections import Counter
from pathlib import Path
from tempfile import TemporaryDirectory

from materialize import export
from native_groups import native_groups
from peer import verify
from solve import ROOT, PACKET_BYTES, parse_msc

HERE = Path(__file__).resolve().parent
CASE = ROOT / "examples/nov28/same-6140-1232"
DECISION_SHA256 = "3896a7a5e6be7cd660fcb8c7a79612b6d4a1fb3adf83bfd64d18596d01ec4f7b"


def check():
    source = CASE / "edogawa-msc.bin"
    peer = CASE / "yokohama-msc.bin"
    alternate = HERE / "dev/edogawa-linear4-msc.bin"
    with TemporaryDirectory() as directory:
        out = Path(directory) / "assembled"
        material = export(source.read_bytes(), alternate.read_bytes(), HERE / "dev/linear-proposals.json",
                          DECISION_SHA256, out)
        overlay = out / "proposed.msc.bin"
        station = verify(source, overlay, peer)
        before = parse_msc(source.read_bytes())
        after = parse_msc(overlay.read_bytes())
        reference = parse_msc(peer.read_bytes())
        original_stats, _, original_groups, _ = native_groups(source.read_bytes())
        overlay_stats, _, overlay_groups, _ = native_groups(overlay.read_bytes())
        _, _, peer_groups, _ = native_groups(peer.read_bytes())
        targets = {(p["primary_row"], p["repaired_ordinal"]) for p in material["rows"]}
        counts = {}
        packets = []
        for p in station["packets"]:
            i, j, q = p["edogawa_row"], p["yokohama_row"], p["ordinal"]
            kind = "solved" if (i, q) in targets else "observed_alternate_sibling"
            totals = counts.setdefault(kind, Counter())
            totals["checked_packets"] += 1
            if p["result"] == "exact_182_bytes":
                totals["exact_packets"] += 1
            changed = {}
            for b in p["changed_bits"]:
                octet = b["wire_bit"] // 8
                if octet not in changed:
                    field = {k: b[k] for k in ("du_byte", "field", "slot", "position", "word_octet") if k in b}
                    if field.get("field") == "evs_direct":
                        field["payload_offset_excluding_mode"] = b["word_octet"] - 1 if b["word_octet"] else None
                        wire_offset = q * PACKET_BYTES + octet
                        field.update(primary_byte=before[i][wire_offset], proposed_byte=after[i][wire_offset],
                                     peer_byte=reference[j][wire_offset])
                    changed[octet] = dict(wire_octet=octet, changed_bits_msb0=[], **field)
                    totals[b["field"] + "_octets"] += 1
                changed[octet]["changed_bits_msb0"].append(b["wire_bit"] % 8)
                totals[b["field"] + "_bits"] += 1
            packets.append(dict(kind=kind, coordinate=p["coordinate"], primary_row=i, peer_row=j,
                                ordinal=q, independent_full_wire=p["result"],
                                peer_du_crc_valid=p["peer_du_crc_valid"], changes=list(changed.values())))
        independent_dus = {}
        for p in material["rows"]:
            row = p["primary_row"]
            peer_row = next(x["peer_row"] for x in packets if x["primary_row"] == row)
            peer_unit = b"".join(reference[peer_row][q * PACKET_BYTES + 1:q * PACKET_BYTES + 180] for q in range(4))
            independent_dus[row] = (out / p["file"]).read_bytes() == peer_unit
        return dict(decision_sha256=DECISION_SHA256, original_primary_sha256=station["original_sha256"],
                    independent_station_sha256=station["peer_sha256"], sealed_row_map_sha256=station["row_map_sha256"],
                    checked_by_origin=counts, complete_du_bytes_equal_at_peer=independent_dus, packets=packets,
                    primary_unmodified=original_stats, primary_proposed_overlay=overlay_stats,
                    unmodified_complete_groups=len(original_groups), proposed_overlay_complete_groups=len(overlay_groups),
                    additional_local_complete_groups=sorted(overlay_groups.keys() - original_groups.keys()),
                    additional_groups_beyond_union=sorted(overlay_groups.keys() - original_groups.keys() - peer_groups.keys()))


if __name__ == "__main__":
    print(json.dumps(check(), indent=2))
