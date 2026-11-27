"""Verify one repeated bulletin record against its two published, CRC-supported receipts."""
from hashlib import sha256
import json
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "scripts"))
from parse_text_records import crc
from salvage_msc_packets import records

SOURCE = ROOT / "contrib/kcbsdrm/reference"
DUMP = SOURCE / "sf_2026-11-25_0457KST_3205_hik.bin"
ITEMS = SOURCE / "items_2026-11-25.json"
PREFIXES = SOURCE / "keys_records_2026-11-25.npz"
# Each entry gives the zero-based item, record and counter of its phase-2 start.
COPIES = [(22, 1, 43679913), (50, 4, 43680559)]


def witnessed_tails():
    """Use only consecutive 0/1/2 triples with all twelve packet CRCs and all three DU CRCs."""
    wanted = {start + d for _, _, start in COPIES for d in range(3)}
    rows = list(records(DUMP))
    tails = {}
    for first, middle, last in zip(rows, rows[1:], rows[2:]):
        group = (first, middle, last)
        if not first or first["counter"] not in wanted:
            continue
        if not all(r and r["complete"] for r in group) or [r["phase"] for r in group] != [0, 1, 2]:
            continue
        for row in group:
            coord = (first["counter"], row["phase"])
            tail = row["du"][698:714]
            if tails.setdefault(coord, tail) != tail:
                raise ValueError(f"CRC-valid observations disagree at {coord}")
    return tails


def check_copy(record, counter, tails, labels):
    if not (record["ok"] and record["complete"] and record["counter"] == counter
            and record["pos"] % 24 == 16 and not record["last"]):
        raise ValueError("Expected a published complete non-final record starting in phase 2")
    body = record["text"].encode("utf-16le")
    if len(body) != 92:
        raise ValueError("Expected a 92-byte bulletin body")
    header = bytes([record["tog"] | (len(body) >> 4), (record["seq"] << 4) | (len(body) & 15)])
    wire = header + body + crc(header + body).to_bytes(2, "big")
    # The 96-byte header/body/CRC occupies six whole tails; the seventh is mandatory fill.
    padded = wire + b"\xbb" * 16
    for n in range(7):
        c, phase = divmod(3 * counter + 2 + n, 3)
        prefix, flags = labels[c]
        if not flags.all():
            raise ValueError(f"Prefix support incomplete at {c}")
        expected = bytes(a ^ int(b) for a, b in zip(padded[16*n:16*(n+1)], prefix, strict=True))
        if tails[c, phase] != expected:
            raise ValueError(f"Published record or CRC disagrees with received tail at {(c, phase)}")
    return wire, body


def main():
    items = json.loads(ITEMS.read_text(encoding="utf-8"))["items"]
    with np.load(PREFIXES, allow_pickle=False) as data:
        labels = {int(c): (k, f) for c, k, f in zip(data["counters"], data["ks"], data["verified"], strict=True)}
    tails = witnessed_tails()
    copies = [check_copy(items[i][j], c, tails, labels) for i, j, c in COPIES]
    if copies[0] != copies[1]:
        raise ValueError("Complete wire records differ")
    wire, body = copies[0]
    # Relative bytes [16,64) fall entirely in the body and span phases 0,1,2 of one counter.
    counters = [c + 1 for _, _, c in COPIES]
    changed = int(np.count_nonzero(labels[counters[0]][0] != labels[counters[1]][0]))
    tail_changes = [
        sum(a != b for a, b in zip(tails[counters[0], phase], tails[counters[1], phase], strict=True))
        for phase in range(3)
    ]
    # At relative byte 64 the counter advances while the same record body continues.
    within_record = [int(np.count_nonzero(labels[c][0] != labels[c + 1][0])) for c in counters]
    if changed != 16 or tail_changes != [16, 16, 16] or within_record != [16, 16]:
        raise ValueError("The across-copy or within-record differences did not reproduce")
    print(json.dumps({
        "record_starts_counter_phase": [[c, 2] for _, _, c in COPIES],
        "aligned_body_counters": counters, "aligned_body_positions_from_header": [16, 64],
        "different_supported_prefix_columns": changed, "compared_columns": 16,
        "different_received_tail_octets_by_phase": tail_changes,
        "different_prefix_columns_at_byte_64_in_each_copy": within_record,
        "body_bytes": len(body), "body_sha256": sha256(body).hexdigest(),
        "header_body_crc_sha256": sha256(wire).hexdigest(), "matched_transmitted_crc16": wire[-2:].hex(),
        "aligned_48_body_bytes_sha256": sha256(wire[16:64]).hexdigest(),
        "source_sha256": {p.name: sha256(p.read_bytes()).hexdigest() for p in (DUMP, ITEMS, PREFIXES)},
    }, indent=2))


if __name__ == "__main__":
    main()
