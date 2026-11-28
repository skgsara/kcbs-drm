"""Measure trailer differences at boundaries with unchanged transmitted EVS modes."""
from collections import defaultdict
import json

from check import CASE, SLICES, blocks, digest
from fingerprint import MEMBER_HASH
from project_evs_group import checked_units
from render_continuous import MODE_POSITIONS


def compare(modes, trailers):
    names = ("all_consecutive", "same_mode_at_boundary", "same_60_slot_sequence",
             "one_constant_mode_across_120_slots")
    stats = {name: dict(pairs=0, different_trailers=0, different_bytes=0, first_example=None)
             for name in names}
    by_sequence = defaultdict(set)
    n_occurrences = defaultdict(int)
    for c in sorted(modes):
        by_sequence[modes[c]].add(trailers[c])
        n_occurrences[modes[c]] += 1
        if c + 1 not in modes:
            continue
        left, right = modes[c], modes[c + 1]
        same_sequence = left == right
        tests = (True, left[-1] == right[0], same_sequence, same_sequence and len(set(left)) == 1)
        changes = sum(a != b for a, b in zip(trailers[c], trailers[c + 1], strict=True))
        for name, applies in zip(names, tests, strict=True):
            if not applies:
                continue
            row = stats[name]
            row["pairs"] += 1
            row["different_trailers"] += int(changes > 0)
            row["different_bytes"] += changes
            if row["first_example"] is None:
                row["first_example"] = dict(counters=[c, c + 1], boundary_modes_hex=[left[-1:].hex(), right[:1].hex()],
                                            different_mode_slots=sum(a != b for a, b in zip(left, right, strict=True)),
                                            changed_trailer_bytes=changes)
    return dict(complete_groups=len(modes), unique_mode_sequences=len(by_sequence),
                repeated_mode_sequences=sum(n > 1 for n in n_occurrences.values()),
                repeated_sequences_with_distinct_trailers=sum(len(values) > 1 for values in by_sequence.values()),
                transitions=stats)


def run():
    archive = CASE.parent / "member-3205-20min/member-dus.npz"
    if digest(archive) != MEMBER_HASH:
        raise ValueError("member data-unit archive differs from the published input")
    modes, trailers = {}, {}
    for counter, phase, unit in checked_units(archive):
        modes[counter, phase] = bytes(unit[i] for i in MODE_POSITIONS)
        start, end = SLICES[phase]
        trailers[counter, phase] = unit[start:end]
    return dict(source_sha256=MEMBER_HASH, crc_checked_dus=len(modes),
                result=compare(blocks(modes), blocks(trailers)))


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
