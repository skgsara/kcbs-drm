"""Check every changed Edogawa physical packet against the independent, original 12:32 Yokohama wire."""
import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2] / "scripts"))
from drm_row_alignment import parse_msc, valid_packets, witnessed_pairs
from project_evs_group import MODE_POSITIONS, PACKET_STARTS, PROJECTED_OCTETS
from salvage_msc_packets import crc

CASE = HERE.parent / "same-6140-1232"
ROW_MAP = CASE / "diversity/alignment/row-pairs.json"
SOURCE_SHA = "ffd62e982e8dbd4d415d0c1d51a81b10bb380244bc2fcab8248ce48a5ec86172"
PEER_SHA = "267261e04afc6f48ef05a547f7784feb4cc9cf39401bf518697992153bdb0c64"
MAP_SHA = "31605d50dea3f9a89ef9fef1b351eedfbb882a234b93038473e23331d8e30207"
MATCH = "exact_182_bytes"
WRONG = "different_182_bytes"
NO_PACKET = "no_peer_valid_packet"
NO_ROW = "no_witnessed_peer_row"


def digest(raw):
    return sha256(raw).hexdigest()


def physical_field(ordinal, wire_byte, coordinate):
    if wire_byte == 0:
        return {"field": "packet_header"}
    if wire_byte >= 180:
        return {"field": "packet_crc"}
    du_byte = 179 * ordinal + wire_byte - 1
    location = {"du_byte": du_byte}
    for local_slot, (mode, start) in enumerate(zip(MODE_POSITIONS, PACKET_STARTS, strict=True)):
        if du_byte == mode:
            octet = 0
        elif start <= du_byte < start + 32:
            octet = 1 + du_byte - start
        else:
            continue
        cycle, role = divmod(local_slot, 4)
        return dict(location, field="evs_direct" if octet in PROJECTED_OCTETS else "evs_non_direct",
                    cycle=cycle, position=role + 1, word_octet=octet,
                    slot=20 * coordinate[1] + local_slot if coordinate is not None else None)
    return dict(location, field="du_crc" if du_byte >= 714 else "du_other")


def changed_bits(original, fixed, peer, ordinal, coordinate):
    bits = []
    for byte_index, (before, after) in enumerate(zip(original, fixed, strict=True)):
        for bit_index in range(8):
            mask = 0x80 >> bit_index
            if (before ^ after) & mask:
                detail = physical_field(ordinal, byte_index, coordinate)
                detail["wire_bit"] = 8 * byte_index + bit_index
                detail["peer_bit_agrees"] = None if peer is None else (peer[byte_index] ^ after) & mask == 0
                if detail["field"] != "evs_non_direct":
                    detail.update(before=int(bool(before & mask)), after=int(bool(after & mask)))
                bits.append(detail)
    return bits


def bit_distance(wire, reference):
    if reference is None:
        return None
    return sum((a ^ b).bit_count() for a, b in zip(wire, reference, strict=True))


def complete_du(row, valid):
    if len(valid) == 4:
        unit = b"".join(row[182 * q + 1:182 * q + 180] for q in range(4))
        if crc(unit[:-2]) == int.from_bytes(unit[-2:], "big"):
            return unit
    return None


def score(source, corrected, peer, anchors):
    if len(source) != len(corrected):
        raise ValueError("corrected dump changed the native row count")
    counts = Counter(dict.fromkeys((MATCH, WRONG, NO_PACKET, NO_ROW), 0))
    fields = {}
    accepted = Counter()
    changes = []
    for index, (original_row, fixed_row) in enumerate(zip(source, corrected, strict=True)):
        if len(original_row) != len(fixed_row):
            raise ValueError(f"corrected dump changed row {index} length")
        if original_row == fixed_row:
            continue
        if len(fixed_row) != 728:
            raise ValueError(f"change in non-728-byte row {index}")
        anchor = anchors.get(index)
        coordinate = anchor["known_coordinate"] if anchor is not None else None
        peer_row = anchor["yokohama_row"] if anchor is not None else None
        received = valid_packets(peer[peer_row]) if peer_row is not None else {}
        source_ok = valid_packets(original_row)
        corrected_ok = valid_packets(fixed_row)
        candidate_du = complete_du(fixed_row, corrected_ok)
        reference_du = complete_du(peer[peer_row], received) if peer_row is not None else None
        for ordinal in range(4):
            start = ordinal * 182
            original = original_row[start:start + 182]
            fixed = fixed_row[start:start + 182]
            if original == fixed:
                continue
            if ordinal in source_ok:
                raise ValueError(f"corrected dump changed an originally valid packet at row {index}, q{ordinal}")
            reference = received.get(ordinal)
            if peer_row is None:
                outcome = NO_ROW
            elif reference is None:
                outcome = NO_PACKET
            else:
                outcome = MATCH if reference == fixed else WRONG
            counts[outcome] += 1
            bits = changed_bits(original, fixed, reference, ordinal, coordinate)
            for bit in bits:
                bucket = fields.setdefault(bit["field"], Counter(changed=0, peer_checked=0, peer_agrees=0))
                bucket["changed"] += 1
                if bit["peer_bit_agrees"] is not None:
                    bucket["peer_checked"] += 1
                    bucket["peer_agrees"] += int(bit["peer_bit_agrees"])
            accepted["corrected_header_crc_valid"] += int(ordinal in corrected_ok)
            accepted["matched_packets_in_jointly_valid_equal_dus"] += int(
                outcome == MATCH and candidate_du is not None and reference_du == candidate_du)
            changes.append(dict(edogawa_row=index, yokohama_row=peer_row, ordinal=ordinal,
                                coordinate=coordinate, witness_ordinals=anchor["witness_ordinals"] if anchor else [],
                                result=outcome, corrected_header_crc_valid=ordinal in corrected_ok,
                                corrected_du_crc_valid=candidate_du is not None, peer_du_crc_valid=reference_du is not None,
                                original_wire_sha256=digest(original), corrected_wire_sha256=digest(fixed),
                                peer_wire_sha256=digest(reference) if reference is not None else None,
                                original_distance_to_peer_bits=bit_distance(original, reference),
                                corrected_distance_to_peer_bits=bit_distance(fixed, reference), changed_bits=bits))
    return dict(changed_packets=len(changes), checked_packets=counts[MATCH] + counts[WRONG],
                outcomes=dict(counts), corrected_header_crc_valid=accepted["corrected_header_crc_valid"],
                matched_packets_in_jointly_valid_equal_dus=accepted["matched_packets_in_jointly_valid_equal_dus"],
                changed_bits_by_field=fields, packets=changes)


def verify(source_path, corrected_path, peer_path):
    source_raw = source_path.read_bytes()
    peer_raw = peer_path.read_bytes()
    map_raw = ROW_MAP.read_bytes()
    if (digest(source_raw), digest(peer_raw), digest(map_raw)) != (SOURCE_SHA, PEER_SHA, MAP_SHA):
        raise ValueError("source, peer or alignment map differs from the public 12:32 case")
    source, peer = parse_msc(source_raw), parse_msc(peer_raw)
    paired, alignment = witnessed_pairs(source, peer)
    saved = json.loads(map_raw)
    if paired != [(row["edogawa_row"], row["yokohama_row"]) for row in saved]:
        raise ValueError("original native packets disagree with the sealed row map")
    corrected_raw = corrected_path.read_bytes()
    result = score(source, parse_msc(corrected_raw), peer, {row["edogawa_row"]: row for row in saved})
    return dict(format="packet-repair-peer-v1", original_sha256=SOURCE_SHA, corrected_sha256=digest(corrected_raw),
                peer_sha256=PEER_SHA, row_map_sha256=MAP_SHA, paired_rows=len(paired),
                unique_full_wire_witnesses=alignment["accepted_witnesses"], rejected_pairs=alignment["rejections"],
                convention="Zero-based row, ordinal and MSB-first wire bit. Coordinate is [counter, phase] "
                           "when present in the pre-repair map. EVS word octet zero is the mode. "
                           "Non-direct octets report physical bit locations only.", **result)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for argument in ("original", "corrected", "peer"):
        parser.add_argument(argument, type=Path)
    parser.add_argument("--out", type=Path, help="write the full verification ledger as JSON (default stdout)")
    args = parser.parse_args()
    try:
        result = verify(args.original, args.corrected, args.peer)
        serialized = json.dumps(result, indent=2) + "\n"
        if args.out is None:
            sys.stdout.write(serialized)
        else:
            args.out.write_text(serialized)
            print(json.dumps({key: result[key] for key in ("changed_packets", "checked_packets", "outcomes")}))
    except (OSError, ValueError) as error:
        parser.exit(2, f"{error}\n")
