"""Compare only directly received EVS octets across all role pairs in the pinned daily and two-site captures."""
import argparse
from collections import Counter, defaultdict
from hashlib import sha256
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from locate_evs_slots import unit_locations
from salvage_msc_packets import records


class Reception:
    def __init__(self, sources):
        self.sources = sources
        self.words = {}
        self.index = defaultdict(list)
        self.joins = set()
        self.distinct = [set() for _ in range(4)]
        for source_id, source in enumerate(sources):
            path = ROOT / source["file"]
            if sha256(path.read_bytes()).hexdigest() != source["sha256"]:
                raise ValueError(f"Unexpected input hash for {path}")
            accepted = {}
            for row in records(path):
                if not row or not row["complete"] or row["phase"] not in (0, 1, 2):
                    continue
                index = row["index"]
                accepted[index] = (row["phase"], row["counter"] if row["phase"] == 0 else None)
                for (_, _, cycle, role), direct in unit_locations(None, row["phase"], row["du"]):
                    loc = (source_id, index, 4 * cycle + role - 1)
                    if len(direct) != 22:
                        raise ValueError(f"Unexpected projection length at {loc}")
                    self.words[loc] = direct
                    self.index[direct].append(loc)
                    self.distinct[role-1].add(direct)
            if len(accepted) != source["accepted_complete_dus"]:
                raise ValueError(f"Unexpected complete DU count for {path}")
            for index, (phase, counter) in accepted.items():
                if phase != 0:
                    continue
                # Both endpoint counters must be explicitly received, with two
                # intervening accepted DUs in native order, before crossing a boundary.
                following = [accepted.get(index + j) for j in (1, 2, 3)]
                if following == [(1, None), (2, None), (0, counter + 1)]:
                    self.joins.update((source_id, index + j) for j in range(3))

    def step(self, location, amount):
        source, row, slot = location
        next_slot = slot + amount
        if 0 <= next_slot < 20:
            return (source, row, next_slot)
        if next_slot < 0 and (source, row-1) in self.joins:
            return (source, row-1, 20 + next_slot)
        if next_slot >= 20 and (source, row) in self.joins:
            return (source, row+1, next_slot-20)
        return None


def sequence_summary(left, right, pairs, stride):
    """Count maximal equal strings, retaining every matching occurrence including repeated signatures."""
    lengths = Counter()
    longest = 0
    example = None
    for a, b in sorted(pairs):
        if (left.step(a, -stride), right.step(b, -stride)) in pairs:
            continue
        length = 1
        x, y = a, b
        while (left.step(x, stride), right.step(y, stride)) in pairs:
            x, y = left.step(x, stride), right.step(y, stride)
            length += 1
        lengths[length] += 1
        if length > longest:
            longest = length
            example = dict(left_start=a, left_end=x, right_start=b, right_end=y)
    if sum(n * count for n, count in lengths.items()) != len(pairs):
        raise ValueError("Chronological run accounting does not cover the matched pairs")
    return dict(stride_slots=stride, maximal_run_count=sum(lengths.values()), longest_words=longest,
                length_histogram={str(n): count for n, count in sorted(lengths.items())},
                first_longest_example=example)


def near_matches(left, right):
    """A pair differing in <=5 octets must agree on at least one of six disjoint blocks."""
    candidates = set()
    block_hits = 0
    for i in range(6):
        index = defaultdict(list)
        for b in right:
            index[b[i::6]].append(b)
        for a in left:
            matches = index.get(a[i::6], ())
            block_hits += len(matches)
            candidates.update((a, b) for b in matches)
    distances = Counter(sum(x != y for x, y in zip(a, b, strict=True)) for a, b in candidates)
    histogram = [distances[d] for d in range(6)]
    if histogram[0] != len(left & right):
        raise ValueError("Distance zero differs from exact signature intersection")
    return dict(distinct_pairs_total=len(left)*len(right), matching_block_pairs=block_hits,
                distinct_candidate_pairs=len(candidates), distinct_pairs_by_octet_distance_0_through_5=histogram,
                candidates_with_more_than_5_differences=len(candidates)-sum(histogram))


def test_near_matches():
    base = bytes(range(22))
    # The six changes in the last example all fall in two blocks, so it reaches
    # the full-distance comparison. Range(6) damages all six blocks and stays out.
    edits = [tuple(range(d)) for d in range(7)] + [(0, 6, 12, 1, 7, 13)]
    words = set()
    for positions in edits:
        word = bytearray(base)
        for j in positions:
            word[j] ^= 255
        words.add(bytes(word))
    result = near_matches({base}, words)
    if (result["distinct_pairs_by_octet_distance_0_through_5"] != [1]*6 or
            result["distinct_candidate_pairs"] != 7 or result["candidates_with_more_than_5_differences"] != 1):
        raise ValueError("Constructed pairs disagree with known octet distances")
    return result


def denominators(site):
    n = len(site.words)
    return dict(sources=site.sources, complete_dus=n // 20, observations=n,
                distinct_signatures=len(site.index), repeated_observations=n-len(site.index),
                observations_by_role=[n // 4] * 4, distinct_by_role=[len(x) for x in site.distinct],
                certified_interdu_joins=len(site.joins))


def compare(case):
    left, right = (Reception(case[key]) for key in ("left", "right"))
    shared = left.index.keys() & right.index.keys()
    cells = []
    all_pairs = set()
    for l in range(4):
        for r in range(4):
            keys = left.distinct[l] & right.distinct[r]
            pairs = {(a, b) for key in keys for a in left.index[key] if a[2] % 4 == l
                     for b in right.index[key] if b[2] % 4 == r}
            all_pairs.update(pairs)
            cells.append(dict(left_role=l+1, right_role=r+1, shared_distinct=len(keys),
                              matched_left_observations=len({a for a, _ in pairs}),
                              matched_right_observations=len({b for _, b in pairs}),
                              occurrence_pairs=len(pairs), same_role_sequence=sequence_summary(left, right, pairs, 4)))
    p1 = cells[0]
    prior = case["comparisons"][0]
    if (p1["shared_distinct"], len(left.distinct[0]), len(right.distinct[0])) != (
            prior["identical_distinct_strings"], prior["left_distinct"], prior["right_distinct"]):
        raise ValueError("P1 comparison differs from the previous published count")
    return dict(left=denominators(left), right=denominators(right), shared_distinct_all_roles=len(shared),
                all_matching_occurrence_pairs=len(all_pairs), role_pairs=cells,
                near_matches_all_roles=near_matches(left.index.keys(), right.index.keys()),
                consecutive_word_sequences=sequence_summary(left, right, all_pairs, 1))


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--check", action="store_true", help="verify against role-comparison.json")
    args = cli.parse_args()
    prior = (HERE / "daily-p1.json").read_bytes()
    sets = json.loads(prior)
    report = dict(
        source_selection_receipt_sha256=sha256(prior).hexdigest(), word_octets=22,
        near_match_method="Distinct left/right signatures only. Includes all position pairings. Compare all 22 octets "
                          "once per candidate pair, generated by agreement on any interleaved block signature[i::6] "
                          "for i=0..5. At most five different octets can affect at most five of these disjoint blocks.",
        synthetic_near_match_control=test_near_matches(),
        scope="Exact bytes from the mode plus the 21 direct zero-based payload offsets where i % 3 != 0. "
              "All accepted complete DUs are included. No clock or same-position restriction is imposed on lookup. "
              "A matched occurrence pair is counted for each left and right observation sharing the signature. "
              "Run coordinates are [source index in its side's list, native MSC row, slot within DU], all zero-based. "
              "Runs continue within a DU or across adjacent, complete 0/1/2/0 native rows with endpoint counters "
              "differing by one. Gaps and file boundaries end runs. Stride 1 counts 20 ms words; stride 4 follows "
              "each role in successive quartets. Both run endpoints in examples are inclusive.")
    for name in ("morning_captures", "same_transmission_control"):
        report[name] = compare(sets[name])
    content = json.dumps(report, indent=2) + "\n"
    if args.check and json.loads(content) != json.loads((HERE / "role-comparison.json").read_bytes()):
        raise SystemExit("Results differ from role-comparison.json")
    print(content, end="")


if __name__ == "__main__":
    main()
