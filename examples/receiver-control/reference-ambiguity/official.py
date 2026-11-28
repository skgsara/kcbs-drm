"""Compare 22-octet projections of the official TS 26.444 fixed- and float-sender words.

Run: python official.py CACHE --fetch --check
Only the eighteen COD and eighteen input PCM members are needed. To use previously
extracted archives, place their testvec/ trees below CACHE/fixed and CACHE/float.
"""
from argparse import ArgumentParser
from collections import Counter, defaultdict
from hashlib import sha256
from itertools import combinations
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from zlib import crc32

HERE = Path(__file__).resolve().parent
CODEC = HERE.parents[1] / "nov28" / "clear-evs-controls"
sys.path[:0] = [str(HERE.parents[2] / "scripts"), str(CODEC), str(CODEC / "erasure-benchmark")]
from check_evs_origin import PROJECTED_OCTETS
from compare_evs_group import read_words
from fetch_corpus import verified_member
from fetch_reference_members import fetch_member

OCTETS = tuple(sorted(PROJECTED_OCTETS))
if OCTETS != (0, 2, 3, 5, 6, 8, 9, 11, 12, 14, 15, 17, 18, 20, 21, 23, 24, 26, 27, 29, 30, 32):
    raise ValueError("unexpected word projection")


def digest(data):
    return sha256(data).hexdigest()


def project(word):
    return bytes(word[i] for i in OCTETS)


def member_path(cache, tier, archive, member, fetch):
    path = cache / tier / member["name"]
    if fetch and not path.exists():
        if "member_sha256" in member:
            fetch_member(member, cache / tier)
        else:
            data = verified_member(archive, member)
            path.parent.mkdir(exist_ok=True, parents=True)
            with TemporaryDirectory(dir=path.parent) as tmp:
                stage = Path(tmp) / "verified"
                stage.write_bytes(data)
                stage.replace(path)
    raw = path.read_bytes()
    expected = member.get("sha256") or member["member_sha256"]
    checksum = member.get("crc32") or member["zip_crc32_hex"]
    if len(raw) != member["size"] or crc32(raw) != int(checksum, 16) or digest(raw) != expected:
        raise ValueError(f"member size, ZIP CRC or SHA-256 differs for {tier}/{member['name']}")
    return path


def load_vectors(cache, pcm_sources, fetch):
    fixed_manifest = json.loads((CODEC / "reference-members.json").read_bytes())
    float_manifest = json.loads((CODEC / "erasure-benchmark/corpus.json").read_bytes())
    archives = {"float": float_manifest, "fixed": fixed_manifest}
    fixed_cods = {m["name"]: m for m in fixed_manifest["members"]}
    inputs = {}
    for tier, archive in archives.items():
        if archive["archive"] != pcm_sources[tier]["archive"] or archive["archive_bytes"] != pcm_sources[tier]["archive_bytes"]:
            raise ValueError("PCM and COD archive identities disagree")
        inputs[tier] = {m["name"]: m for m in pcm_sources[tier]["members"]}

    streams, sources = {}, {}
    for item in float_manifest["members"]:
        if item["cohort"] != "float":
            continue
        name, case = item["name"], item["logical_name"]
        inp = name.replace("/bitstreams/", "/input/").split("_13200_")[0] + ".INP"
        pcm = {}
        source = {"cod": name, "input_pcm": inp}
        for tier, cod in (("float", item), ("fixed", fixed_cods[name])):
            archive = archives[tier]
            pcm[tier] = member_path(cache, tier, archive, inputs[tier][inp], fetch).read_bytes()
            path = member_path(cache, tier, archive, cod, fetch)
            words = list(read_words(path))
            rate = int(Path(name).stem.rsplit("_", 1)[1].removesuffix("kHz")) * 1000
            if len(words) != item["frames"] or not all(w is not None and len(w) == 33 for w in words):
                raise ValueError("unexpected EVS frame length or erasure")
            if len(pcm[tier]) != len(words) * (rate // 50) * 2:
                raise ValueError("input PCM duration differs from coded stream")
            streams[tier, case] = words
            source[tier + "_cod_sha256"] = digest(path.read_bytes())
        if pcm["fixed"] != pcm["float"]:
            raise ValueError(f"{case}: source PCM differs between official archives")
        source.update(frames=len(words), pcm_bytes=len(pcm["fixed"]), identical_input_pcm_sha256=digest(pcm["fixed"]))
        sources[case] = source
    if len(sources) != 9 or len({s["identical_input_pcm_sha256"] for s in sources.values()}) != 9:
        raise ValueError("expected nine distinct PCM inputs")
    return streams, sources


def frame_pair_context(a, b, raw, views):
    left, i = a
    right, j = b
    room = min(i, j, len(raw[left]) - 1 - i, len(raw[right]) - 1 - j)
    def same(d, seq):
        return seq[left][i + d] == seq[right][j + d]
    radius = 0
    while radius < room and same(-radius - 1, views) and same(radius + 1, views):
        radius += 1
    full_radius = 0
    while full_radius < room and same(-full_radius - 1, raw) and same(full_radius + 1, raw):
        full_radius += 1
    start_l, start_r = i - i % 60, j - j % 60
    group_eligible = i % 60 == j % 60 and start_l + 60 <= len(raw[left]) and start_r + 60 <= len(raw[right])
    same_group = group_eligible and views[left][start_l:start_l + 60] == views[right][start_r:start_r + 60]
    return dict(neighbours_available=room >= 1, both_neighbours_same_projection=radius >= 1,
                both_neighbours_same_whole_word=room >= 1 and same(-1, raw) and same(1, raw),
                symmetric_projection_radius=radius, symmetric_surrounding_whole_word_radius=full_radius,
                same_slot_in_complete_60_groups=group_eligible,
                same_projection_through_entire_60_group=same_group)


def example(a, b, streams, views, context):
    left, i = a
    right, j = b
    w, v = streams[left][i], streams[right][j]
    bits = [8 * k + bit for k, (x, y) in enumerate(zip(w, v, strict=True))
            for bit in range(8) if (x ^ y) & (128 >> bit)]
    return dict(left=[*left, i], right=[*right, j], mode=f"{w[0]:02X}",
                projected_sha256=digest(views[left][i]), word_sha256=[digest(w), digest(v)],
                differing_msb0_word_bits=bits, differing_word_octets=[
                    [k, f"{w[k]:02X}", f"{v[k]:02X}"] for k in sorted({bit // 8 for bit in bits})],
                context=context)


def analyze(streams):
    views = {name: list(map(project, words)) for name, words in streams.items()}
    buckets = defaultdict(list)
    scopes = ("within_one_member", "same_pcm_different_encoder", "different_pcm")
    keys = ("all_index_pairs", "equal_projection", "identical_whole_words", "different_whole_words")
    counts = {s: dict.fromkeys(keys, 0) for s in scopes}
    for name, seq in views.items():
        counts[scopes[0]]["all_index_pairs"] += len(seq) * (len(seq) - 1) // 2
        for i, p in enumerate(seq):
            buckets[p].append((name, i))
    for a, b in combinations(views, 2):
        scope = scopes[1] if a[1] == b[1] else scopes[2]
        counts[scope]["all_index_pairs"] += len(views[a]) * len(views[b])
    by_case = {}
    for tier, case in views:
        if tier == "float":
            pairs = zip(streams["float", case], streams["fixed", case], strict=True)
            same, amb = 0, 0
            for a, b in pairs:
                same += a == b
                amb += a != b and project(a) == project(b)
            by_case[case] = dict(aligned_slots=len(views[tier, case]), equal_complete=same,
                                 equal_projection_different_complete=amb)
    contexts, examples, longest, ambiguity = defaultdict(Counter), {}, {}, set()
    tiers = defaultdict(set)
    for p, observations in buckets.items():
        if len(observations) < 2:
            continue
        for a, b in combinations(observations, 2):
            left, i = a
            right, j = b
            scope = scopes[0] if left == right else scopes[1] if left[1] == right[1] else scopes[2]
            totals = counts[scope]
            totals["equal_projection"] += 1
            w, v = streams[left][i], streams[right][j]
            if w == v:
                totals["identical_whole_words"] += 1
                continue
            totals["different_whole_words"] += 1
            ambiguity.add(p)
            if left[0] == right[0]:
                tiers[left[0]].add(p)
            context = frame_pair_context(a, b, streams, views)
            stats = contexts[scope]
            for k, val in context.items():
                if isinstance(val, bool):
                    stats[k] += int(val)
            stats["largest_symmetric_projection_radius"] = max(stats["largest_symmetric_projection_radius"],
                                                                context["symmetric_projection_radius"])
            stats["largest_symmetric_surrounding_whole_word_radius"] = max(
                stats["largest_symmetric_surrounding_whole_word_radius"], context["symmetric_surrounding_whole_word_radius"])
            stats["aligned_frame_indices"] += int(i == j)
            bit_count = sum((x ^ y).bit_count() for x, y in zip(w, v, strict=True))
            stats["one_bit_pairs"] += int(bit_count == 1)
            stats["both_slots_index_1_mod_4"] += int(i % 4 == j % 4 == 1)
            if scope not in examples:
                examples[scope] = example(a, b, streams, views, context)
            if scope not in longest or context["symmetric_projection_radius"] > longest[scope]["context"]["symmetric_projection_radius"]:
                longest[scope] = example(a, b, streams, views, context)
    return dict(total_words=sum(map(len, streams.values())), distinct_words=len(set().union(*map(set, streams.values()))),
                distinct_projections=len(buckets), ambiguous_projection_values=len(ambiguity),
                ambiguous_projection_values_within_tier={t: len(tiers[t]) for t in ("fixed","float")},
                occurrence_pairs_by_scope=counts, same_sample_index_fixed_vs_float=by_case,
                context_of_equal_projection_different_complete_pairs=contexts, first_examples=examples,
                longest_matching_projected_neighbourhood=longest)


def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("cache", type=Path, help="directory containing fixed/testvec/ and float/testvec/")
    parser.add_argument("--fetch", action="store_true", help="retrieve just the missing official ZIP members")
    parser.add_argument("--check", action="store_true", help="check every result against official.json")
    args = parser.parse_args()
    expected = json.loads((HERE / "official.json").read_bytes())
    sources = expected["pcm_sources"]
    streams, identity = load_vectors(args.cache, sources, args.fetch)
    result = dict(projected_msb0_word_octets=list(OCTETS), sources=identity, **analyze(streams),
                  pcm_sources=sources)
    if args.check and result != expected:
        raise SystemExit("result differs from official.json")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
