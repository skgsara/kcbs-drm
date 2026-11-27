"""Project the directly transmitted EVS octets from the CRC-checked DUs of one counter."""
import argparse
import csv
import json
from pathlib import Path
import sys
from zipfile import BadZipFile

import numpy as np

from check_evs_origin import PROJECTED_OCTETS
from compare_evs_group import valid_integer
from render_continuous import MODE_POSITIONS, PACKET_STARTS
from tail_fill_audit import crc


FIELDS = ("slot", "counter", "phase", "cycle", "position", "receipt", "direct_bits", "octets")


def read_phases(path, counter):
    archive = np.load(path, allow_pickle=False)
    if not isinstance(archive, np.lib.npyio.NpzFile):
        raise ValueError("expected data_units.npz")
    with archive:
        if len(archive.files) != len(set(archive.files)):
            raise ValueError("duplicate array names in data_units.npz")
        if not {"counters", "phases", "du"}.issubset(archive.files):
            raise ValueError("data_units.npz requires counters, phases and du")
        counters, phases, units = (archive[name] for name in ("counters", "phases", "du"))
    if (counters.ndim != 1 or counters.dtype.kind not in "iu" or phases.shape != counters.shape
            or phases.dtype.kind not in "iu" or units.dtype != np.uint8 or units.shape != (len(counters), 716)):
        raise ValueError("expected one counter, phase, and 716-byte data unit per row")
    seen = set()
    selected = {}
    for count, phase, row in zip(counters, phases, units, strict=True):
        count, phase = int(count), int(phase)
        if not 0 <= count <= 0xffffffff or phase not in (0, 1, 2):
            raise ValueError(f"invalid data-unit coordinates {count}/{phase}")
        if (count, phase) in seen:
            raise ValueError(f"duplicate data-unit coordinates {count}/{phase}")
        seen.add((count, phase))
        unit = row.tobytes()
        if crc(unit[:-2]) != int.from_bytes(unit[-2:], "big"):
            raise ValueError(f"data-unit CRC failed at {count}/{phase}")
        if unit[1] >> 4 != phase or (phase == 0 and int.from_bytes(unit[664:668], "big") != count):
            raise ValueError(f"data-unit header disagrees with coordinates {count}/{phase}")
        if count == counter:
            selected[phase] = unit
    return selected


def project_group(path, counter):
    if not valid_integer(counter, 0, 0xffffffff):
        raise ValueError("counter must be an unsigned 32-bit integer")
    phases = read_phases(path, counter)
    slots = []
    for phase in range(3):
        unit = phases.get(phase)
        for i, (mode, payload) in enumerate(zip(MODE_POSITIONS, PACKET_STARTS, strict=True)):
            cycle, role = divmod(i, 4)
            if unit is None:
                octets = ["--"] * 33
                receipt = "missing_du"
                bits = 0
            else:
                octets = ["??"] * 33
                for j in PROJECTED_OCTETS:
                    offset = mode if j == 0 else payload + j - 1
                    octets[j] = f"{unit[offset]:02x}"
                receipt = "received_du"
                bits = 8 * len(PROJECTED_OCTETS)
            slots.append(dict(slot=len(slots), counter=int(counter), phase=phase, cycle=cycle, position=role + 1,
                              receipt=receipt, direct_bits=bits, octets=" ".join(octets)))
    complete = sum(row["receipt"] == "received_du" for row in slots)
    full_words = sum(row["direct_bits"] == 264 for row in slots)
    return dict(format="kcbs-evs-projection-v1", counter=int(counter), received_du_phases=sorted(phases),
                layout="Each row starts with the mode octet followed by 32 payload octets.",
                word_erasure_basis="The projection cannot supply a full word if any octet is unknown or unavailable.",
                markers={"??": "received octet with unknown clear value",
                         "--": "no CRC-checked data unit for this phase in the supplied archive"},
                direct_word_octet_indices=list(PROJECTED_OCTETS),
                total_slots=len(slots), physically_complete_slots=complete, missing_du_slots=len(slots) - complete,
                confirmed_direct_bits=sum(row["direct_bits"] for row in slots),
                full_clear_words=full_words, word_erasures=len(slots) - full_words, slots=slots)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data_units", type=Path, help="data_units.npz from salvage_msc_packets.py")
    parser.add_argument("--counter", type=int, required=True)
    parser.add_argument("--format", choices=("json", "tsv"), default="json",
                        help="JSON with group totals or TSV with one line per slot")
    args = parser.parse_args()
    try:
        result = project_group(args.data_units, args.counter)
    except (OSError, ValueError, EOFError, BadZipFile) as error:
        parser.exit(2, f"{parser.prog}: {error}\n")
    if args.format == "json":
        print(json.dumps(result, indent=2))
    else:
        writer = csv.DictWriter(sys.stdout, FIELDS, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(result["slots"])


if __name__ == "__main__":
    main()
