#!/usr/bin/env python3
"""Check the three direct position-two class labels in the 17:44 handoff.

Run "python check_supplement.py PATH" with the original receiver supplement ZIP,
its extracted directory, or its 1744 subdirectory. Requires Python 3.10+ and
NumPy. The member hashes are from the supplied archive. Packet CRCs were
stripped before archiving; this checks the contributor's packet flags, native
DU CRCs, and the transmitted CRC/UTF-16LE body of each supporting text record.
"""
import argparse
import binascii
import csv
import hashlib
import io
import json
from pathlib import Path
from zipfile import ZipFile

import numpy as np


MEMBERS = {
    "packets.npz": "4403df9fca927b9d9df25e009145d7a2504b1123bd4f3897544c252b8e505bd8",
    "keys.npz": "a45b72851583334cd6ecbd24aebbe4844744a3559a912e3d95b903e7670f2168",
    "text-crc-records.json": "0421fec859cfe9224b9bdf822367a69a4e2eafe9634e49024b03a6338fcafbcc",
}


def check(condition, message):
    if not condition:
        raise ValueError(message)


def crc(data):
    return binascii.crc_hqx(data, 0xffff) ^ 0xffff


def members(path):
    if path.is_dir():
        capture = path if path.name == "1744" else path / "1744"
        data = {name: (capture / name).read_bytes() for name in MEMBERS}
    else:
        data = {}
        with ZipFile(path) as archive:
            for name in MEMBERS:
                hits = [p for p in archive.namelist() if Path(p).parts[-2:] == ("1744", name)]
                check(len(hits) == 1, f"expected one 1744/{name}")
                data[name] = archive.read(hits[0])
    for name, expected in MEMBERS.items():
        check(hashlib.sha256(data[name]).hexdigest() == expected, f"{name} hash mismatch")
    return data


def accepted_units(contents):
    result = {}
    with np.load(io.BytesIO(contents), allow_pickle=False) as archive:
        for tick, packets, flags in zip(archive["ticks"], archive["packets"], archive["packet_ok"], strict=True):
            tick = int(tick)
            counter, phase = divmod(tick, 3)
            du = packets.tobytes()
            check(tick not in result and flags.all() and len(du) == 716 and du[1] >> 4 == phase,
                  f"invalid complete DU at {tick}")
            check(crc(du[:714]) == int.from_bytes(du[714:], "big"), f"DU CRC mismatch at {tick}")
            if phase == 0:
                check(int.from_bytes(du[664:668], "big") == counter, f"counter mismatch at {tick}")
            result[tick] = du
    return result


def verify_record(units, supplied, entry):
    start = 3 * entry["counter"] + entry["phase"]
    blocks = []
    for tick in range(start, start + entry["block_count"]):
        prefix, flags = supplied[tick // 3]
        check(flags.all(), f"unsupported record block at {tick}")
        blocks.append(bytes(a ^ b for a, b in zip(units[tick][698:714], prefix, strict=True)))
    wire = b"".join(blocks)
    length = 16 * (wire[0] & 7) + (wire[1] & 15)
    end = 2 + length
    check(length == entry["byte_count"] and wire[2:end].decode("utf-16le") == entry["text"],
          f"text mismatch at {start}")
    checksum = wire[end:end+2].hex()
    check(checksum == entry["crc16"] and crc(wire[:end]) == int(checksum, 16),
          f"text CRC mismatch at {start}")
    return end, checksum, hashlib.sha256(wire).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("supplement", type=Path)
    args = parser.parse_args()
    sources = members(args.supplement)
    units = accepted_units(sources["packets.npz"])
    with np.load(io.BytesIO(sources["keys.npz"]), allow_pickle=False) as archive:
        supplied = {int(c): (bytes(k), f) for c, k, f in
                    zip(archive["counters"], archive["ks"], archive["crc_supported"], strict=True)}
    records = json.loads(sources["text-crc-records.json"])
    with Path(__file__).with_name("p2-labels.csv").open(newline="") as stream:
        expected = {(int(r["counter"]), int(r["phase"]), int(r["cycle"])): r
                    for r in csv.DictReader(stream) if r["capture"] == "1744"}
    relevant = 0
    observed = set()
    for tick, du in units.items():
        counter, phase = divmod(tick, 3)
        for cycle in range(5):
            mode_offset = 39 + 131 * cycle
            mode = du[mode_offset]
            if mode not in (0xf9, 0xfa, 0xfb):
                continue
            relevant += 1
            if counter not in supplied or not supplied[counter][1][11]:
                continue
            witnesses = []
            for entry in records:
                start = 3 * entry["counter"] + entry["phase"]
                for text_phase in range(3):
                    index = 16 * (3 * counter + text_phase - start) + 11
                    if not 0 <= index < 2 + entry["byte_count"]:
                        continue
                    end, checksum, digest = verify_record(units, supplied, entry)
                    check(index < end, "column 11 is outside the CRC-covered header/body")
                    witnesses.append(f"{entry['counter']}/{entry['phase']}/{index}/{checksum}/{digest}")
                    break  # One witness per distinct text record suffices.
            if not witnesses:
                continue
            coord = counter, phase, cycle
            row = expected.get(coord)
            check(row is not None, f"unexpected eligible coordinate {coord}")
            first = du[mode_offset + 1] ^ supplied[counter][0][11]
            label = str(first >> 7) if mode == 0xf9 else f"{first >> 6:02b}"
            slot = 20 * phase + 4 * cycle + 1
            check(int(row["slot_in_group"]) == slot and row["position"] == "2" and row["mode"] == f"{mode:02X}"
                  and row["observed"] == label and row["record_witnesses"] == "|".join(witnesses),
                  f"CSV disagreement at {coord}")
            check(label == "0" if mode == 0xf9 else label != "11", f"class rule failed at {coord}")
            observed.add(coord)
            print(f"{counter} phase={phase} cycle={cycle} P2 slot={slot} mode={mode:02X} class bits={label}")
    check(observed == set(expected) and len(observed) == 3, "supplement coverage mismatch")
    print(f"{len(observed)} text-CRC-covered labels among {relevant} applicable received P2 modes")


if __name__ == "__main__":
    main()
