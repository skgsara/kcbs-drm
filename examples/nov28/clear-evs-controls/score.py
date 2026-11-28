"""Score the existing public field checks on externally labelled, complete EVS words."""
import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2] / "scripts"))
from compare_evs_group import read_words
from evs_gsc_fields import gsc_fields
from evs_intra_word import intra_word
from evs_transition_tags import allowed_pairs


RULES = ("wb_gsc_audio", "swb_gsc_inactive", "audio_noisy", "inactive_nibble",
         "noisy_pitch_fill", "swb_transition_pair")
MEMBER_SHA = "e35b777d0ef1183bb0455a33f7c24fd54ea465a10d426847c645736a724e1647"


def observations(index, word):
    # The projector's ordinary checks share a slot API. Provide the supplied
    # word there without assigning artificial broadcast counters or positions.
    slot = dict(slot=index, counter=None, phase=None, cycle=None, position=None,
                receipt="received_du", octets=word.hex(" "))
    for r in intra_word([slot])["slots"]:
        if r["check"] in ("wb_gsc_audio", "swb_gsc_inactive"):
            lo, hi = r["allowed"]
            yield r["check"], r["observed"], list(range(lo, hi + 1)), False
    for r in gsc_fields([slot])["slots"]:
        yield r["check"], r["observed"], [r["predicted"]], False
    choices = allowed_pairs(word[0], word[-1])
    if choices is not None:
        yield "swb_transition_pair", word[1] >> 6, choices, len(choices) == 4


def score_file(path, expected_hash, *, radio_positions=False):
    raw_hash = sha256(path.read_bytes()).hexdigest()
    if raw_hash != expected_hash:
        raise ValueError(f"unexpected SHA-256 for {path.name}")
    rows = {name: dict(eligible=0, outside_allowed=0, informative_allowed=0,
                       unrestricted=0, observed=Counter(), first_outside=None) for name in RULES}
    modes = Counter()
    slots = usable = covered = informative = any_outside = 0
    positions = {p: dict(supplied=0, erased=0) for p in range(1, 5)} if radio_positions else None
    for index, word in enumerate(read_words(path)):
        slots += 1
        if positions is not None:
            positions[1 + index % 4]["supplied" if word else "erased"] += 1
        if not word:
            continue
        usable += 1
        modes[word[0] >> 3] += 1
        events = list(observations(index, word))
        covered += bool(events)
        informative += any(not unrestricted for _, _, _, unrestricted in events)
        any_outside += any(value not in allowed for _, value, allowed, _ in events)
        for name, value, allowed, unrestricted in events:
            r = rows[name]
            r["eligible"] += 1
            r["observed"][value] += 1
            if unrestricted:
                r["unrestricted"] += 1
            elif value in allowed:
                r["informative_allowed"] += 1
            else:
                r["outside_allowed"] += 1
                if r["first_outside"] is None:
                    r["first_outside"] = dict(slot_zero_based=index, mode_hex=f"{word[0]:02X}",
                                              allowed=allowed, observed=value,
                                              word_sha256=sha256(word).hexdigest())
    result = dict(sha256=raw_hash, slots=slots, clear_words=usable, erasures=slots - usable,
                  words_with_applicable_checks=covered, words_with_restrictive_checks=informative,
                  words_outside_any_check=any_outside, mode_index_counts=dict(sorted(modes.items())), checks=rows)
    if positions is not None:
        result["by_broadcast_position"] = positions
    return result


def totals(reports):
    counts = {}
    for name in RULES:
        counts[name] = {metric: sum(r["checks"][name][metric] for r in reports)
                        for metric in ("eligible", "outside_allowed", "informative_allowed", "unrestricted")}
    return dict(clear_words=sum(r["clear_words"] for r in reports),
                words_with_applicable_checks=sum(r["words_with_applicable_checks"] for r in reports),
                words_with_restrictive_checks=sum(r["words_with_restrictive_checks"] for r in reports),
                words_outside_any_check=sum(r["words_outside_any_check"] for r in reports), checks=counts)


def official(root):
    manifest = json.loads((HERE / "reference-members.json").read_text())
    entries = {item["name"]: item["member_sha256"] for item in manifest["members"] if item["name"].endswith(".COD")}
    groups = {}
    for cohort in ("primary", "replication"):
        members = {name: score_file(root / name, entries[name]) for name in manifest[cohort]}
        groups[cohort] = dict(totals=totals(members.values()), files=members)
    return groups


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--official", type=Path, help="directory containing the official testvec tree")
    inputs.add_argument("--handoff", type=Path, help="original 11:05 known-first-position.192.gz")
    args = parser.parse_args()
    output = official(args.official) if args.official else score_file(args.handoff, MEMBER_SHA, radio_positions=True)
    print(json.dumps(output, indent=2))
