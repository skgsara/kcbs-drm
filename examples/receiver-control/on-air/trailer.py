"""Count observed group trailers using only complete consecutive native groups in this IQ replay."""
from hashlib import sha256
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
NOV = HERE.parents[1] / "nov28"
sys.path[:0] = [str(NOV / "group-boundary/trailer"), str(NOV / "same-6140-1232")]
from native_groups import native_groups
from check import SLICES, ZERO_BYTES, adjacent_observations


def summarize():
    raw = (HERE / "native.msc.bin").read_bytes()
    recorded = json.loads((HERE / "receipt.json").read_bytes())
    if sha256(raw).hexdigest() != recorded["native_msc_sha256"]:
        raise ValueError("native receiver digest differs")
    _, _, _, groups = native_groups(raw)
    blocks = {}
    nonzero = 0
    for counter, units in groups.items():
        blocks[counter] = b"".join(u[a:b] for u, (a, b) in zip(units, SLICES, strict=True))
        nonzero += sum(u[i] != 0 for u, offsets in zip(units, ZERO_BYTES, strict=True) for i in offsets)
    return dict(native_msc_sha256=recorded["native_msc_sha256"], counters=list(groups),
                complete_groups=len(groups), distinct_trailers=len(set(blocks.values())),
                padding_bytes_checked=len(groups) * sum(map(len, ZERO_BYTES)), nonzero_padding=nonzero,
                consecutive_pairs=adjacent_observations(blocks))


if __name__ == "__main__":
    print(json.dumps(summarize(), indent=2))
