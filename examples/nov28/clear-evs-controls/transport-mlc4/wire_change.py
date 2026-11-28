"""Verify original native rows and count added direct observations for the gained group."""
import argparse
from collections import Counter
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from check import CASE, capture, digest, require
from drm_row_alignment import read_msc, valid_packets, witnessed_pairs
from project_evs_group import MODE_POSITIONS, PACKET_STARTS, PROJECTED_OCTETS, project_group
from salvage_msc_packets import crc, salvage


def projection(path, counter):
    with TemporaryDirectory() as directory:
        out = Path(directory) / "transport"
        salvage([path], out, transport_only=True, save_packets=True)
        slots = project_group(out / "packets.npz", counter, packets=True)["slots"]
    result = []
    for p in range(1, 5):
        rows = [r for r in slots if r["position"] == p]
        tokens = Counter(t for r in rows for t in r["octets"].split())
        result.append(dict(position=p, received_slots=sum(any(t != "--" for t in r["octets"].split()) for r in rows),
                           direct_bits=sum(r["direct_bits"] for r in rows), carried_unknown_bits=tokens["??"] * 8,
                           no_receipt_bits=tokens["--"] * 8,
                           complete_clear_words=sum(r["direct_bits"] == 264 for r in rows)))
    return result


def complete_groups(du):
    return {c for c, _ in du if all((c, phase) in du for phase in range(3))}


def group_witnesses(counter, old, new, peer):
    phases = []
    for p in range(3):
        keys = [(counter,p,q) for q in range(4)]
        common = [k for k in keys if k in new.packets and k in peer.packets]
        a, b = new.units.get((counter,p)), peer.units.get((counter,p))
        phases.append(dict(phase=p, mlc1_packets=sum(k in old.packets for k in keys),
                           mlc4_packets=sum(k in new.packets for k in keys), peer_packets=sum(k in peer.packets for k in keys),
                           exact_shared_wires=sum(new.packets[k] == peer.packets[k] for k in common),
                           conflicting_wires=sum(new.packets[k] != peer.packets[k] for k in common),
                           du_peer_equal=(a == b) if a is not None and b is not None else None,
                           du_crc=a[-2:].hex() if a else None, peer_du_crc=b[-2:].hex() if b else None))
    return phases


def field_location(phase, q, wire_offset, difference):
    if not 1 <= wire_offset <= 179:
        return {"field": "physical packet header or CRC"}
    offset = q * 179 + wire_offset - 1
    for i, (mode, payload) in enumerate(zip(MODE_POSITIONS, PACKET_STARTS, strict=True)):
        if offset == mode or payload <= offset < payload + 32:
            j = 0 if offset == mode else 1 + offset - payload
            cycle, role = divmod(i, 4)
            return dict(du_offset=offset, slot=phase * 20 + i, cycle=cycle, position=role + 1,
                        field="mode" if j == 0 else f"payload p{j-1}",
                        direct_field=j in PROJECTED_OCTETS,
                        changed_word_bits=[8*j+b for b in range(8) if difference & (128 >> b)])
    return {"du_offset": offset, "field": "outside projected word"}


def inspect(trial):
    base = CASE / "edogawa-msc.bin"
    old, new = capture(base, "edogawa"), capture(trial)
    peer = capture(CASE / "yokohama-msc.bin", "yokohama")
    old_rows, new_rows = read_msc(base), read_msc(trial)
    pairs, _ = witnessed_pairs(old_rows, new_rows)
    old_at = {j:i for i,j in pairs}
    gains = []
    for coord in sorted(new.packets.keys() - old.packets.keys()):
        q = coord[2]
        observations = []
        for j in new.rows[coord]:
            if j not in old_at:
                continue
            i = old_at[j]
            a, b = valid_packets(old_rows[i]), valid_packets(new_rows[j])
            witnesses = sorted(k for k in a.keys() & b.keys() if k != q and a[k] == b[k])
            require(witnesses, "this native comparison needs a witness outside the tested quarter")
            previous = old_rows[i][182*q:182*(q+1)]
            current = b[q]
            changed = [x for x in range(182) if previous[x] != current[x]]
            reference = peer.packets.get(coord)
            changes = [dict(wire_offset=x, mlc1=f"{previous[x]:02x}", mlc4=f"{current[x]:02x}",
                            peer=f"{reference[x]:02x}" if reference is not None else None,
                            **field_location(coord[1], q, x, previous[x] ^ current[x])) for x in changed]
            observations.append(dict(mlc1_row=i, mlc4_row=j, other_matching_ordinals=witnesses,
                                     peer_native_rows=peer.rows.get(coord, []),
                                     previous_wire_sha256=digest(previous), mlc4_wire_sha256=digest(current),
                                     previous_valid=q in a, previous_crc_computed=f"{crc(previous[:-2]):04x}",
                                     mlc4_crc_computed=f"{crc(current[:-2]):04x}",
                                     previous_crc_field=previous[-2:].hex(), mlc4_crc_field=current[-2:].hex(),
                                     changes=changes, changed_bits=sum((previous[x]^current[x]).bit_count() for x in changed)))
        gains.append(dict(coordinate=list(coord), native_comparisons=observations))
    initial, final = complete_groups(old.units), complete_groups(new.units)
    return dict(edogawa_mlc1_sha256=old.file_sha256, edogawa_mlc4_sha256=new.file_sha256,
                complete_groups_before=len(initial), complete_groups_after=len(final),
                groups_gained=sorted(final-initial), groups_lost=sorted(initial-final), packet_gains=gains,
                group_projections=[dict(counter=c, mlc1=projection(base,c), mlc4=projection(trial,c),
                                        peer_witnesses=group_witnesses(c,old,new,peer))
                                   for c in sorted(final-initial)])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mlc4_msc", type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    result = inspect(args.mlc4_msc)
    with args.out.open("x") as output:
        output.write(json.dumps(result, indent=2) + "\n")
