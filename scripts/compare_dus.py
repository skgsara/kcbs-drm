"""Compare complete CRC-checked 716-byte DRM data units by (counter, phase).

Generate each data_units.npz independently with salvage_msc_packets.py --transport-only.
The receipt lists every exact match, disagreement and one-sided coordinate. Phase zero
carries a counter. Phases one and two use the assignments of each input archive.
"""
import argparse
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
from zipfile import BadZipFile

from project_evs_group import checked_units


def read_archive(path):
    raw = path.read_bytes()
    with BytesIO(raw) as stream:
        units = {(c, p): unit for c, p, unit in checked_units(stream)}
    return units, {"archive_sha256": sha256(raw).hexdigest(), "complete_dus": len(units)}


def compare(left_path, right_path):
    left, left_source = read_archive(left_path)
    right, right_source = read_archive(right_path)
    shared = sorted(left.keys() & right.keys())
    matches = []
    disagreements = []
    unequal_bytes = 0
    for counter, phase in shared:
        coord = (counter, phase)
        a, b = left[coord], right[coord]
        if a == b:
            matches.append(coord)
        else:
            offsets = [i for i, (x, y) in enumerate(zip(a, b, strict=True)) if x != y]
            unequal_bytes += len(offsets)
            disagreements.append({
                "coordinate": coord, "left_du_sha256": sha256(a).hexdigest(),
                "right_du_sha256": sha256(b).hexdigest(), "differing_byte_offsets": offsets,
            })
    compared_bytes = 716 * len(shared)
    return {
        "format": "drm-du-comparison-v1",
        "coordinate_order": ["counter", "phase"],
        "left": left_source, "right": right_source,
        "same_archive_bytes": left_source["archive_sha256"] == right_source["archive_sha256"],
        "shared_coordinates": len(shared),
        "matching_dus": len(matches), "differing_dus": len(disagreements),
        "left_only_dus": len(left) - len(shared), "right_only_dus": len(right) - len(shared),
        "compared_du_bytes": compared_bytes, "bytes_in_matching_dus": 716 * len(matches),
        "equal_bytes_at_shared_coordinates": compared_bytes - unequal_bytes,
        "differing_bytes_at_shared_coordinates": unequal_bytes,
        "matching_coordinates": matches,
        "disagreements": disagreements,
        "left_only_coordinates": sorted(left.keys() - right.keys()),
        "right_only_coordinates": sorted(right.keys() - left.keys()),
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
                                 epilog="Exits 0 for nonempty overlap with all shared DUs equal, "
                                        "1 for disagreements or empty overlap, and 2 for an input error.")
    ap.add_argument("left", type=Path, help="first receiver's data_units.npz")
    ap.add_argument("right", type=Path, help="second receiver's data_units.npz")
    ap.add_argument("--out", type=Path, help="save the JSON receipt to a new file (default: stdout)")
    args = ap.parse_args()
    try:
        result = compare(args.left, args.right)
        text = json.dumps(result, indent=2) + "\n"
        if args.out is None:
            print(text, end="")
        else:
            with args.out.open("x", encoding="utf-8") as out:
                out.write(text)
    except (ValueError, OSError, EOFError, BadZipFile) as error:
        ap.exit(2, f"{ap.prog}: {error}\n")
    return int(result["shared_coordinates"] == 0 or result["differing_dus"] != 0)


if __name__ == "__main__":
    raise SystemExit(main())
