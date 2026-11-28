"""Count repeated publicly readable first-position frame bytes in two dated KCBS-2 captures."""
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from render_continuous import MODE_POSITIONS, PACKET_STARTS
from salvage_msc_packets import records

DIRECT = tuple(j for j in range(32) if j % 3)
HISTORY = ROOT / "contrib/kcbsdrm/reference"
PAIR = ROOT / "examples/nov28/same-6140-1232"


def read(paths):
    counts = {n: Counter() for n in (1, 2, 5)}
    sources = []
    for path in paths:
        accepted = 0
        for row in records(path):
            if not row or not row["complete"] or row["phase"] not in (0, 1, 2):
                continue
            accepted += 1
            du = row["du"]
            frames = [bytes([du[MODE_POSITIONS[s]], *(du[PACKET_STARTS[s] + j] for j in DIRECT)])
                      for s in range(0, 20, 4)]
            for n, table in counts.items():
                table.update(b"".join(frames[i:i + n]) for i in range(len(frames) - n + 1))
        sources.append(dict(file=str(path.relative_to(ROOT)), sha256=sha256(path.read_bytes()).hexdigest(),
                            accepted_complete_dus=accepted))
    return counts, sources


def compare(left_paths, right_paths):
    left, ls = read(left_paths)
    right, rs = read(right_paths)
    results = []
    for n in (1, 2, 5):
        matches = left[n].keys() & right[n].keys()
        results.append(dict(first_position_frames=n, bytes_per_comparison=22 * n,
                            left_observations=left[n].total(), right_observations=right[n].total(),
                            left_distinct=len(left[n]), right_distinct=len(right[n]),
                            identical_distinct_strings=len(matches)))
    return dict(left=ls, right=rs, comparisons=results)


if __name__ == "__main__":
    daily = compare([HISTORY / f"sf_2026-11-25_{t}KST_3205_hik.bin" for t in ("0448", "0457")],
                    [HISTORY / "sf_2026-11-26_0500KST_3205_hl5ntr.bin"])
    simultaneous = compare([PAIR / "edogawa-msc.bin"], [PAIR / "yokohama-msc.bin"])
    print(json.dumps(dict(
        scope="All CRC-valid, complete DUs in these files, including portions outside the common time of day. "
              "Only first-position mode and the 21 directly readable payload octets are compared. "
              "Multi-frame strings use consecutive first positions within a single DU. "
              "Exact equality is tested without fixing a daily start offset. No concealed audio contributes.",
        morning_captures=daily, same_transmission_control=simultaneous), indent=2))
