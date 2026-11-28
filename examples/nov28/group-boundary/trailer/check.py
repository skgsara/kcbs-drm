"""Compare the three physical trailer slices in the published two-receiver packet archives."""
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
from statistics import median
import sys

HERE = Path(__file__).resolve().parent
CASE = HERE.parent
ROOT = CASE.parents[2]
sys.path.insert(0, str(CASE))
from check_dual_rf import digest, packets

# Each half-open range is relative to the complete 716-byte data unit.
SLICES = ((668, 698), (665, 698), (664, 697))
ZERO_BYTES = ((662, 663), (662, 663, 664), (662, 663, 697))
Q3_START = 3 * 179
PINS = {
    "3205": "7824c1146312aef97628da57d97e947036ce3b5312691c5376bbcff7e223293f",
    "6140": "05a4cc876e3f20c89d01e80eaa3fd3e4fb027f3d5ff920db34e1a9c6d008a90c",
}


def blocks(pieces):
    counters = {counter for counter, phase in pieces}
    return {counter: b"".join(pieces[counter, phase] for phase in range(3))
            for counter in counters if all((counter, phase) in pieces for phase in range(3))}


def site(station, units_path, ids):
    archive = CASE / f"dual-{station}.npz"
    if digest(archive) != PINS[station]:
        raise ValueError(f"unexpected {station} packet archive")
    # Verifies the full 182-byte wire header and CRC, location from q0/q3 if carried,
    # and agrees with the separate validated DU archive on every complete data unit.
    wire, units = packets(archive, units_path, ids, None, None)
    pieces, complete = {}, {}
    zeros = [{"du_offsets": list(offsets), "checked_bytes": 0, "nonzero_bytes": 0}
             for offsets in ZERO_BYTES]
    n_counter = 0
    bad_counter = 0
    for (tick, ordinal), (body, _) in wire.items():
        if ordinal != 3:
            continue
        counter, phase = divmod(tick, 3)
        a, b = SLICES[phase]
        piece = body[a - Q3_START:b - Q3_START]
        pieces[counter, phase] = piece
        if tick in units:
            if piece != units[tick][a:b]:
                raise ValueError("packet and independently validated complete DU slice disagree")
            complete[counter, phase] = piece
        for offset in ZERO_BYTES[phase]:
            zeros[phase]["checked_bytes"] += 1
            zeros[phase]["nonzero_bytes"] += int(body[offset - Q3_START] != 0)
        if phase == 0:
            announced = int.from_bytes(body[664 - Q3_START:668 - Q3_START], "big")
            n_counter += 1
            bad_counter += int(announced != counter)
    whole = blocks(pieces)
    sealed = sha256()
    for counter, block in sorted(whole.items()):
        sealed.update(counter.to_bytes(4, "big"))
        sealed.update(block)
    report = dict(
        accepted_q3_by_phase=[sum(phase == p for _, phase in pieces) for p in range(3)],
        complete_dus=len(complete), all_three_q3=len(whole), all_three_complete_dus=len(blocks(complete)),
        distinct_complete_96_byte_blocks=len(set(whole.values())),
        counter_then_96_bytes_sha256=sealed.hexdigest(),
        phase0_counter=dict(checked=n_counter, mismatched=bad_counter), zero_fields_by_phase=zeros,
    )
    return pieces, complete, report


def compare(keys, left, right):
    """Keys pair input coordinates; both readable values are required to count a comparison."""
    nleft = nright = neither = matched = different = byte_count = mismatched_bytes = 0
    for lkey, rkey in keys:
        x, y = left.get(lkey), right.get(rkey)
        if x is None and y is None:
            neither += 1
        elif y is None:
            nleft += 1
        elif x is None:
            nright += 1
        else:
            matched += int(x == y)
            different += int(x != y)
            byte_count += len(x)
            mismatched_bytes += sum(a != b for a, b in zip(x, y, strict=True))
    return dict(possible=matched + different + nleft + nright + neither, compared=matched + different,
                matched=matched, disagreed=different, only_3205=nleft, only_6140=nright, neither=neither,
                compared_bytes=byte_count, disagreeing_bytes=mismatched_bytes)


def cohort(ids, left, right, shift):
    pairs = [(c, c + shift) for c in sorted(ids) if c + shift in ids]
    joint = Counter(sum((c, p) in left and (d, p) in right for p in range(3)) for c, d in pairs)
    return dict(
        by_phase=[compare([((c, p), (d, p)) for c, d in pairs], left, right) for p in range(3)],
        block=compare(pairs, blocks(left), blocks(right)),
        counters_by_number_of_jointly_observed_phases={str(n): joint[n] for n in range(4)},
    )


def adjacent_observations(blocks_by_counter):
    """Compare fully observed blocks at c and c+1, never across a missing counter."""
    pairs = [(block, blocks_by_counter[c + 1]) for c, block in blocks_by_counter.items()
             if c + 1 in blocks_by_counter]
    changes = [sum(a != b for a, b in zip(x, y, strict=True)) for x, y in pairs]
    phase_changes = []
    start = 0
    for a, b in SLICES:
        stop = start + b - a
        phase_changes.append(sum(x[start:stop] != y[start:stop] for x, y in pairs))
        start = stop
    return dict(
        consecutive_counter_pairs=len(pairs), whole_blocks_different=sum(n > 0 for n in changes),
        different_whole_fragments_by_phase=phase_changes,
        octet_comparisons=96 * len(pairs), equal_octets=96 * len(pairs) - sum(changes),
        different_octets=sum(changes),
        changed_octets_per_pair_histogram=dict(sorted(Counter(changes).items())),
        changed_octets_per_pair_min_median_max=[min(changes), median(changes), max(changes)] if changes else None,
    )


def run():
    member = CASE.parent / "member-3205-20min"
    prior = json.loads((member / "cross-frequency.json").read_bytes())
    ids = set(prior["historical_exposure"]["member_historical_counter_ids"])
    left, full_left, s3205 = site("3205", member / "member-dus.npz", ids)
    right, full_right, s6140 = site("6140", ROOT / prior["sources"]["edogawa_6140_du_archive"], ids)
    left_blocks, right_blocks = blocks(left), blocks(right)
    matched_ids = left_blocks.keys() & right_blocks.keys()
    equal_blocks = {c: left_blocks[c] for c in matched_ids if left_blocks[c] == right_blocks[c]}
    return dict(
        format="paired-physical-trailer-v1", shared_assigned_counters=len(ids),
        du_slices_half_open=SLICES, block_length=96, q3_du_start=Q3_START,
        inputs_sha256=PINS, site_3205=s3205, site_6140=s6140,
        same_counter=dict(accepted_q3=cohort(ids, left, right, 0),
                          complete_dus=cohort(ids, full_left, full_right, 0),
                          distinct_equal_96_byte_blocks=len(set(equal_blocks.values()))),
        within_station_adjacent=dict(
            site_3205=adjacent_observations(left_blocks), site_6140=adjacent_observations(right_blocks),
            both_sites_at_both_counters_equal=adjacent_observations(equal_blocks),
        ),
        adjacent_counter_control=dict(direction="3205 at c versus 6140 at c+1, both counter IDs in the shared archive",
                                      accepted_q3=cohort(ids, left, right, 1),
                                      complete_dus=cohort(ids, full_left, full_right, 1)),
        scope="Previously published 119 mutually assigned counters. CRCs validate received packets. "
              "Coordinates for partial DUs rely on the original receiver assignments. "
              "The digest at each site concatenates four-byte big-endian counter then the 96 observed bytes, "
              "in ascending counter order. One EVS word spans 20 ms, one phase DU spans 400 ms, "
              "and its three-phase group spans 1.2 s. Successive blocks can differ without every octet "
              "changing or their components being refreshed simultaneously.",
    )


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
