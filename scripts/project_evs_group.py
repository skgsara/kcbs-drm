"""Project the directly transmitted EVS octets from received data units or packet receipts."""
import argparse
import csv
import json
from pathlib import Path
import sys
from zipfile import BadZipFile

import numpy as np

from check_evs_origin import PROJECTED_OCTETS
from compare_evs_group import valid_integer
from received_evs_packets import read_packet_snapshot
from render_continuous import MODE_POSITIONS, PACKET_STARTS
from tail_fill_audit import crc


FIELDS = ("slot", "counter", "phase", "cycle", "position", "receipt", "direct_bits", "octets")


def checked_units(path):
    """Yield unique (counter, phase, bytes) rows after validating the DU and its coordinates."""
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
        yield count, phase, unit


def read_phases(path, counter):
    return {phase: unit for count, phase, unit in checked_units(path) if count == counter}


def project_group(path, counter, *, packets=False):
    if not valid_integer(counter, 0, 0xffffffff):
        raise ValueError("counter must be an unsigned 32-bit integer")
    if packets:
        ticks, units, flags = read_packet_snapshot(path)
        phases = {int(ticks[i] % 3): (units[i], flags[i]) for i in np.flatnonzero(ticks // 3 == counter)}
    else:
        phases = {phase: (unit, (True,) * 4) for phase, unit in read_phases(path, counter).items()}
    complete_phases = sorted(phase for phase, (_, flags) in phases.items() if all(flags))
    slots = []
    physical_octets = []
    for phase in range(3):
        source = phases.get(phase)
        for i, (mode, payload) in enumerate(zip(MODE_POSITIONS, PACKET_STARTS, strict=True)):
            cycle, role = divmod(i, 4)
            octets = ["--"] * 33
            receipt = "missing_du"
            observed = bits = 0
            if source is not None:
                unit, flags = source
                for j, offset in enumerate((mode, *range(payload, payload + 32))):
                    if flags[offset // 179]:
                        observed += 1
                        if j in PROJECTED_OCTETS:
                            octets[j] = f"{unit[offset]:02x}"
                            bits += 8
                        else:
                            octets[j] = "??"
                if phase in complete_phases:
                    receipt = "received_du"
                elif observed:
                    receipt = "received_packets"
            if packets and not observed:
                receipt = "missing_packets"
            physical_octets.append(observed)
            slots.append(dict(slot=len(slots), counter=int(counter), phase=phase, cycle=cycle, position=role + 1,
                              receipt=receipt, direct_bits=bits, octets=" ".join(octets)))
    complete = physical_octets.count(33)
    full_words = sum(row["direct_bits"] == 264 for row in slots)
    result = dict(format="kcbs-evs-projection-v1", counter=int(counter), received_du_phases=complete_phases,
                layout="Each row starts with the mode octet followed by 32 payload octets.",
                word_erasure_basis="The projection cannot supply a full word if any octet is unknown or unavailable.",
                markers={"??": "received octet with unknown clear value",
                         "--": "no CRC-checked data unit for this phase in the supplied archive"},
                direct_word_octet_indices=list(PROJECTED_OCTETS),
                total_slots=len(slots), physically_complete_slots=complete, missing_du_slots=20 * (3 - len(complete_phases)),
                confirmed_direct_bits=sum(row["direct_bits"] for row in slots),
                full_clear_words=full_words, word_erasures=len(slots) - full_words, slots=slots)
    if packets:
        result.update(format="kcbs-evs-packet-projection-v1",
                      received_packet_ordinals={str(p): [q for q, ok in enumerate(flags) if ok]
                                                for p, (_, flags) in sorted(phases.items()) if any(flags)},
                      physically_partial_slots=sum(0 < n < 33 for n in physical_octets),
                      physically_missing_slots=physical_octets.count(0))
        result["markers"]["--"] = "no packet receipt for this octet"
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("data_units", nargs="?", type=Path, help="CRC-checked data_units.npz")
    source.add_argument("--packets", type=Path, help="packets.npz from salvage_msc_packets.py --save-packets")
    parser.add_argument("--counter", type=int, required=True)
    parser.add_argument("--format", choices=("json", "tsv"), default="json",
                        help="JSON with group totals or TSV with one line per slot")
    parser.add_argument("--field-checks", action="store_true",
                        help="add within-word and adjacent-mode EVS field checks to JSON")
    args = parser.parse_args()
    if args.field_checks and args.format != "json":
        parser.error("--field-checks requires JSON output")
    try:
        result = project_group(args.packets or args.data_units, args.counter, packets=args.packets is not None)
        if args.field_checks:
            from evs_core_history import core_history
            from evs_gsc_fields import gsc_fields
            from evs_hq_neighbors import hq_neighbors
            from evs_intra_word import intra_word
            from evs_transition_tags import transition_tags
            result["transition_tags"] = transition_tags(result["slots"])
            result["core_history"] = core_history(result["slots"])
            result["intra_word"] = intra_word(result["slots"])
            result["gsc_fields"] = gsc_fields(result["slots"])
            result["hq_neighbors"] = hq_neighbors(result["slots"])
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
