"""Count the Korean fragments displayed in the member's note and locate their first data units."""
import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import re

import numpy as np


HERE = Path(__file__).resolve().parent
HEADER = re.compile(r"^## ([0-9]+)｜韩文原文与中文译文$", re.MULTILINE)
FRAGMENT = re.compile(
    r"\n\n首次原记录：([0-9]+)；出现次数：([0-9]+)；counter：([0-9]+)；phase：([0-2])。"
    r"\n\n\*\*韩文原文\*\*\n\n```text\n(.*?)\n```\n\n\*\*中文译文\*\*",
    re.DOTALL,
)


def coordinate_set(path):
    with np.load(path, allow_pickle=False) as archive:
        counters = archive["counters"]
        phases = archive["phases"]
    if counters.ndim != 1 or counters.shape != phases.shape:
        raise ValueError(f"unaligned counter and phase arrays in {path}")
    if counters.dtype.kind not in "ui" or phases.dtype.kind not in "ui":
        raise ValueError(f"non-integer coordinates in {path}")
    if np.any(counters < 0) or np.any(counters > 0xffffffff) or np.any(phases < 0) or np.any(phases > 2):
        raise ValueError(f"coordinates outside the transport range in {path}")
    return set(zip(counters.tolist(), phases.tolist()))


def audit(note, member, peer):
    raw = note.read_bytes()
    parts = HEADER.split(raw.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n"))
    if len(parts) == 1 or any(re.search(r"^## ", part, re.MULTILINE) for part in parts[::2]):
        raise ValueError("missing or unrecognized section heading")
    archives = {"3205": coordinate_set(member), "6140": coordinate_set(peer)}
    frequencies = Counter()
    distinct = set()
    starts = []
    for number, section in zip(parts[1::2], parts[2::2]):
        match = FRAGMENT.match(section)
        if not match or int(number) != len(starts) + 1:
            raise ValueError(f"malformed or out-of-order section {number}")
        ordinal, count, counter, phase = map(int, match.groups()[:4])
        if not 1 <= ordinal or not 1 <= count or counter > 0xffffffff:
            raise ValueError(f"invalid occurrence metadata in section {number}")
        distinct.add(match.group(5))  # The newline before the closing fence is markup.
        frequencies[count] += 1
        starts.append(dict(section=int(number), first_record=ordinal, count=count,
                           counter=counter, phase=phase,
                           present={station: (counter, phase) in coords for station, coords in archives.items()}))
    pairs = list(zip(starts, starts[1:]))
    return {
        "note_sha256": sha256(raw).hexdigest(),
        "sections": len(starts), "distinct_displayed_korean": len(distinct),
        "reported_occurrences": sum(n * fragments for n, fragments in frequencies.items()),
        "occurrences_per_fragment_histogram": dict(sorted(frequencies.items())),
        "first_record_numbers_increasing": all(a["first_record"] < b["first_record"] for a, b in pairs),
        "start_coordinates_increasing": all((a["counter"], a["phase"]) < (b["counter"], b["phase"])
                                            for a, b in pairs),
        "start_matches": {station: sum(row["present"][station] for row in starts) for station in archives},
        "starts": starts,
        "scope": "Presence refers to the first counter and phase in the supplied DU coordinate arrays. "
                 "Occurrence counts are reported by the member. Korean display strings are compared "
                 "with their whitespace preserved.",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("note", type=Path, help="the member's deduplicated Korean/Chinese Markdown")
    parser.add_argument("--member", type=Path, default=HERE / "member-dus.npz")
    parser.add_argument("--peer", type=Path, default=HERE.parents[1] / "nov27/validation/swb-gsc/edogawa-data-units.npz")
    args = parser.parse_args()
    try:
        result = audit(args.note, args.member, args.peer)
    except (OSError, ValueError, KeyError) as error:
        parser.exit(2, f"{error}\n")
    print(json.dumps(result, indent=2))
