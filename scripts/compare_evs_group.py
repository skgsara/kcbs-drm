"""Compare 60 EVS word slots of one KCBS counter in G.192 or mono EVS storage files."""
import argparse
from contextlib import ExitStack
import gzip
import json
from numbers import Integral
from pathlib import Path
import struct
import sys
import zlib

import numpy as np


def _storage_words(stream, path, first):
    """Read mono frame-blocks per 3GPP TS 26.445 Annex A.2.6 and Table A.4."""
    magic = b"#!EVS_MC1.0\n"
    if first + stream.read(len(magic) - len(first)) != magic:
        raise ValueError(f"{path}: invalid or unsupported EVS storage header")
    descriptor = stream.read(4)
    if len(descriptor) != 4:
        raise ValueError(f"{path}: truncated EVS channel descriptor")
    channels = int.from_bytes(descriptor, "big")
    if channels != 1:
        raise ValueError(f"{path}: expected one EVS storage channel, found {channels}")

    slot = 0
    while toc := stream.read(1):
        if toc == b"\x04":  # Primary 13.2 kbit/s, octet-aligned and MSB first.
            word = stream.read(33)
            if len(word) != 33:
                raise ValueError(f"{path}: truncated EVS storage payload at slot {slot}")
            yield word
        elif toc in (b"\x0e", b"\x0f"):  # SPEECH_LOST and NO_DATA both occupy one slot.
            yield b""
        else:
            raise ValueError(f"{path}: unsupported EVS storage ToC 0x{toc[0]:02x} at slot {slot}")
        slot += 1


def read_words(path):
    """Yield 264-bit words or empty slots from G.192 or EVS storage, optionally gzipped."""
    path = Path(path)
    try:
        with ExitStack() as stack:
            stream = stack.enter_context(path.open("rb"))
            if stream.peek(2).startswith(b"\x1f\x8b"):
                stream = stack.enter_context(gzip.GzipFile(fileobj=stream))
            header = stream.read(4)
            if header.startswith(b"#!"):
                yield from _storage_words(stream, path, header)
                return
            slot = 0
            while header:
                if len(header) != 4:
                    raise ValueError(f"{path}: truncated header at slot {slot}")
                sync, length = struct.unpack("<HH", header)
                if (sync, length) == (0x6b20, 0):
                    yield b""
                elif (sync, length) == (0x6b21, 264):
                    payload = stream.read(2 * length)
                    if len(payload) != 2 * length:
                        raise ValueError(f"{path}: truncated payload at slot {slot}")
                    bits = np.frombuffer(payload, dtype="<u2")
                    if ((bits != 0x7f) & (bits != 0x81)).any():
                        raise ValueError(f"{path}: invalid bit symbol at slot {slot}")
                    yield np.packbits(bits == 0x81).tobytes()
                else:
                    raise ValueError(f"{path}: unexpected sync 0x{sync:04x} or length {length} at slot {slot}")
                slot += 1
                header = stream.read(4)
    except (gzip.BadGzipFile, EOFError, zlib.error) as error:
        raise ValueError(f"{path}: invalid gzip stream ({error})") from error


def valid_integer(value, lower, upper):
    return isinstance(value, Integral) and not isinstance(value, bool) and lower <= value <= upper


def group_words(path, start, counter):
    if (not isinstance(start, (list, tuple)) or len(start) != 4
            or not all(valid_integer(v, lo, hi) for v, (lo, hi) in
                       zip(start, ((0, 0xffffffff), (0, 2), (0, 4), (1, 4))))):
        raise ValueError("origin must give a uint32 counter, phase 0–2, cycle 0–4 and position 1–4")
    first_counter, phase, cycle, position = map(int, start)
    start_in_group = 20 * phase + 4 * cycle + position - 1
    group_start = ((int(counter) - first_counter) % (1 << 32)) * 60 - start_in_group
    result = [None] * 60
    # Validate both complete streams, including data beyond the selected group.
    for index, word in enumerate(read_words(path)):
        slot = index - group_start
        if 0 <= slot < 60:
            result[slot] = word
    return result


def compare_group(candidate, reference, *, counter, candidate_start, reference_start):
    if not valid_integer(counter, 0, 0xffffffff):
        raise ValueError("counter must be an unsigned 32-bit integer")
    left = group_words(candidate, candidate_start, counter)
    right = group_words(reference, reference_start, counter)
    outcomes = ("match", "mismatch", "candidate_only", "reference_only", "both_erased", "outside_extent")
    counts = {str(pos): dict.fromkeys(outcomes, 0) for pos in range(1, 5)}
    mismatches = []
    for slot, (candidate_word, reference_word) in enumerate(zip(left, right, strict=True)):
        position = slot % 4 + 1
        if candidate_word is None or reference_word is None:
            outcome = "outside_extent"
        elif candidate_word and reference_word:
            outcome = "match" if candidate_word == reference_word else "mismatch"
            if outcome == "mismatch":
                diff = sum((a ^ b).bit_count() for a, b in zip(candidate_word, reference_word, strict=True))
                mismatches.append(dict(phase=slot // 20, cycle=(slot % 20) // 4,
                                       position=position, differing_bits=diff))
        elif candidate_word:
            outcome = "candidate_only"
        elif reference_word:
            outcome = "reference_only"
        else:
            outcome = "both_erased"
        counts[str(position)][outcome] += 1
    return dict(counter=int(counter), candidate=str(candidate), reference=str(reference),
                candidate_start=list(map(int, candidate_start)), reference_start=list(map(int, reference_start)),
                group_exact=all(row["match"] == 15 for row in counts.values()),
                by_position=counts, mismatches=mismatches,
                provenance_note="Exact matches establish equality of supplied bits at the stated origins. "
                                "Independent reference provenance requires separate evidence.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("reference", type=Path)
    parser.add_argument("--counter", required=True, type=int)
    for role in ("candidate", "reference"):
        parser.add_argument(f"--{role}-start", type=int, nargs=4, required=True,
                            metavar=("COUNTER", "PHASE", "CYCLE", "POSITION"),
                            help=f"coordinates of the first slot in the {role} file")
    args = parser.parse_args()
    try:
        report = compare_group(args.candidate, args.reference, counter=args.counter,
                               candidate_start=args.candidate_start, reference_start=args.reference_start)
    except (OSError, ValueError) as error:
        print(json.dumps({"error": str(error)}), file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2))
    return 0 if report["group_exact"] else 1


if __name__ == "__main__":
    sys.exit(main())
