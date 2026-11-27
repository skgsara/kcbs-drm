"""Rebuild the November 15 EVS origin fingerprints from three received data units."""
import argparse
from binascii import crc_hqx
from hashlib import sha256
import json
from pathlib import Path


TARGET = Path(__file__).with_name("target-43004924.json")
DIRECT_PAYLOAD = tuple(offset for offset in range(32) if offset % 3 != 0)


def build_receipt(data):
    if len(data) != 3 * 716:
        raise ValueError("supply three 716-byte data units in phase order, including their CRCs")
    target_bytes = TARGET.read_bytes()
    target = json.loads(target_bytes)
    counter = target["target"]["counter"]
    hashes = [sha256() for _ in range(4)]
    for phase, expected in enumerate(target["du_phases"]):
        unit = data[phase * 716:(phase + 1) * 716]
        if expected["phase"] != phase or sha256(unit).hexdigest() != expected["du_sha256"]:
            raise ValueError(f"data unit at phase {phase} differs from the published target")
        if unit[1] >> 4 != phase or (phase == 0 and int.from_bytes(unit[664:668], "big") != counter):
            raise ValueError(f"unexpected on-air coordinate at phase {phase}")
        if (crc_hqx(unit[:-2], 0xffff) ^ 0xffff) != int.from_bytes(unit[-2:], "big"):
            raise ValueError(f"data-unit CRC failed at phase {phase}")
        for cycle in range(5):
            for role, digest in enumerate(hashes):
                payload = 7 + 131 * cycle + 33 * role
                mode = 2 + cycle if role == 0 else payload - 1
                digest.update(unit[mode:mode + 1])
                digest.update(bytes(unit[payload + offset] for offset in DIRECT_PAYLOAD))
    return dict(format="kcbs-evs-origin-v1", counter=counter, target_sha256=sha256(target_bytes).hexdigest(),
                position_sha256=[digest.hexdigest() for digest in hashes])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data_units", type=Path, help="three concatenated DUs, 2,148 bytes total")
    args = parser.parse_args()
    try:
        print(json.dumps(build_receipt(args.data_units.read_bytes()), indent=2))
    except (OSError, ValueError) as error:
        parser.exit(2, f"{parser.prog}: {error}\n")
