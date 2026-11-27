"""Check a declared EVS group origin against the capture's directly transmitted octets."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import re
import sys

from compare_evs_group import group_words, valid_integer


RECEIPT_FORMAT = "kcbs-evs-origin-v1"
TARGET_FORMAT = "opaque-drm-transport-target-v1"
# Physical octet zero carries the mode. The 32 payload offsets start after it.
PROJECTED_OCTETS = (0,) + tuple(1 + offset for offset in range(32) if offset % 3 != 0)


def unique_fields(pairs):
    fields = {}
    for key, value in pairs:
        if key in fields:
            raise ValueError(f"duplicate JSON field: {key}")
        fields[key] = value
    return fields


def valid_digest(value):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-fA-F]{64}", value) is not None


def check_origin(receipt_path, export, *, target, start):
    receipt = json.loads(Path(receipt_path).read_bytes(), object_pairs_hook=unique_fields)
    fields = {"format", "counter", "target_sha256", "position_sha256"}
    if not isinstance(receipt, dict) or set(receipt) != fields or receipt["format"] != RECEIPT_FORMAT:
        raise ValueError("expected a kcbs-evs-origin-v1 receipt with exactly four named fields")
    counter = receipt["counter"]
    if not valid_integer(counter, 0, 0xffffffff):
        raise ValueError("receipt counter must be an unsigned 32-bit integer")
    expected = receipt["position_sha256"]
    if (not valid_digest(receipt["target_sha256"]) or not isinstance(expected, list)
            or len(expected) != 4 or not all(valid_digest(item) for item in expected)):
        raise ValueError("expected one SHA-256 for the target and four position SHA-256 digests")

    target_bytes = Path(target).read_bytes()
    target_sha = sha256(target_bytes).hexdigest()
    if target_sha != receipt["target_sha256"].lower():
        raise ValueError("receipt SHA-256 does not match the supplied target file")
    document = json.loads(target_bytes, object_pairs_hook=unique_fields)
    if (not isinstance(document, dict) or document.get("format") != TARGET_FORMAT
            or not isinstance(document.get("target"), dict)):
        raise ValueError("expected an opaque-drm-transport-target-v1 target")
    target_counter = document["target"].get("counter")
    if not valid_integer(target_counter, 0, 0xffffffff) or counter != target_counter:
        raise ValueError("target counter and receipt counter must be the same uint32")

    slots = group_words(export, start, counter)
    positions = {}
    for position, expected_sha in enumerate(expected, start=1):
        words = slots[position-1::4]
        erased, outside = words.count(b""), words.count(None)
        actual_sha = None
        if erased == 0 and outside == 0:
            projection = bytes(word[index] for word in words for index in PROJECTED_OCTETS)
            actual_sha = sha256(projection).hexdigest()
        positions[str(position)] = dict(supplied=len(words) - erased - outside, erased=erased,
                                        outside_extent=outside, projected_sha256=actual_sha,
                                        match=actual_sha == expected_sha.lower())
    return dict(counter=counter, target_sha256=target_sha, export_start=list(start),
                origin_match=all(row["match"] for row in positions.values()), by_position=positions,
                scope="Each digest covers 15 words in phase/cycle order, 22 directly transmitted octets per word. "
                      "Full-word equality and independent export provenance require separate evidence.")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("receipt", type=Path)
    parser.add_argument("export", type=Path)
    parser.add_argument("--target", required=True, type=Path, help="published transport target JSON")
    parser.add_argument("--start", required=True, nargs=4, type=int, metavar=("COUNTER", "PHASE", "CYCLE", "POSITION"),
                        help="coordinates of the first slot of the EVS export")
    args = parser.parse_args(argv)
    try:
        result = check_origin(args.receipt, args.export, target=args.target, start=args.start)
    except (ValueError, OSError) as error:
        print(json.dumps({"error": str(error)}), file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2))
    return 0 if result["origin_match"] else 1


if __name__ == "__main__":
    sys.exit(main())
