"""Check the six EVS examples and three clear text records in the contributor's November 28 note."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import re
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2] / "scripts"))
from check_evs_origin import PROJECTED_OCTETS
from locate_evs_slots import build_index
from parse_text_records import parse_record
from project_evs_group import checked_units
from render_continuous import MODE_POSITIONS


def check(note_path):
    raw = note_path.read_bytes()
    if sha256(raw).hexdigest() != "1d543f74d426513bd3640a76b0041035479e389ff76e3d4ad40cd7740a285319":
        raise ValueError("expected the original skgsara-crosscheck-20261128.md")
    note = raw.decode("utf-8")
    corpus = HERE / "member-dus.npz"
    units = {3 * c + ph: u for c, ph, u in checked_units(corpus)}
    counter = 43907925
    unit = units[3 * counter]
    index = build_index(corpus, HERE / "partial-packets.npz")
    rows = [json.loads(line) for line in note.splitlines() if line.startswith('{"counter":')]
    words = [bytes([int(row["mode_octet"], 16)]) + bytes.fromhex(row["payload_hex"]) for row in rows]
    examples = b"".join(words)
    tests = [
        dict(slot=row["slot"], width=len(word), du_offset=unit.find(word),
             direct_coordinate_matches=len(index.get(bytes(word[j] for j in PROJECTED_OCTETS), [])))
        for row, word in zip(rows, words, strict=True)
    ]

    records = []
    submitted_blocks = {}
    for start, literal in re.findall(r"### Block (\d+).*?plaintext_hex: `([0-9a-f]+)`", note, re.S):
        tick = int(start)
        record = bytes.fromhex(literal)
        parsed = parse_record(record)
        if parsed.size != len(record):
            raise ValueError(f"trailing bytes in submitted record {tick}")
        crc_offset = 2 + parsed.body_length
        records.append(dict(start=tick, counter=tick // 3, phase=tick % 3,
                            crc=record[crc_offset:crc_offset + 2].hex().upper(),
                            body_bytes=parsed.body_length, record_bytes=parsed.size))
        for offset in range(0, len(record), 16):
            t = tick + offset // 16
            if t in submitted_blocks:
                raise ValueError(f"duplicate submitted block {t}")
            submitted_blocks[t] = record[offset:offset + 16]

    # Each comparison uses only the submitted plaintext pair and its two received text tails.
    pairs = [(t, t + 1) for t in submitted_blocks if t + 1 in submitted_blocks and t % 3 != 2]
    shifts = []
    for groups in (0, -1, 1):
        checked = matched = equal_bytes = 0
        for a, b in pairs:
            first = units.get(a + 3 * groups)
            second = units.get(b + 3 * groups)
            if first is None or second is None:
                continue
            agreement = sum((p ^ q) == (u ^ v) for p, q, u, v in zip(
                submitted_blocks[a], submitted_blocks[b], first[698:714], second[698:714], strict=True))
            checked += 1
            matched += agreement == 16
            equal_bytes += agreement
        shifts.append(dict(counter_shift=groups, pairs_tested=checked, equal_pairs=matched, equal_bytes=equal_bytes))

    supplied = bytes.fromhex(re.search(r"Candidate key .*?: `([0-9a-f]+)`", note).group(1))
    first_tick = 3 * counter + 2
    anchored = bytes(a ^ b for a, b in zip(units[first_tick][698:714], supplied, strict=True))
    return dict(counter=counter, phase0_du_crc=unit[-2:].hex().upper(),
                first_five_p1_modes=[f"{unit[j]:02X}" for j in MODE_POSITIONS[::4]],
                evs_rows=tests, exactly_matches_du_prefix=(examples == unit[:len(examples)]),
                submitted_evs_rows_sha256=sha256(examples).hexdigest(), records=records,
                record_blocks_received=sum(t in units for t in submitted_blocks),
                first_supplied_text_pair_matches=(anchored == submitted_blocks[first_tick]),
                within_counter_text_checks=shifts)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("note", type=Path)
    print(json.dumps(check(parser.parse_args().note), indent=2))
