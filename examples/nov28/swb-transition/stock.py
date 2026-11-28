"""Check original 13.2 kb/s stock sender words at the slot addresses selected by their mode."""
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import sys

SCRIPTS = Path(__file__).resolve().parents[3] / "scripts"
sys.path.insert(0, str(SCRIPTS))
from compare_evs_group import read_words
from evs_transition_tags import field


def check(path):
    totals = Counter()
    examples = {}
    for slot, word in enumerate(read_words(path)):
        totals["slots"] += 1
        if not word:
            continue
        prediction = field(word[0], word[32])
        if prediction is None:
            continue
        totals["transition"] += 1
        actual = word[1] >> 6
        if actual not in prediction["allowed_high_pairs"]:
            raise ValueError(f"stock source contradicts prediction at slot {slot}")
        totals[prediction["outcome"]] += 1
        totals["individual_bits"] += len(prediction["fixed_word_bits"])
        if prediction["outcome"] == "restricted":
            size = len(prediction["allowed_high_pairs"])
            examples.setdefault(size, dict(slot=slot, sender_word=word.hex(), actual=actual, **prediction))
    return dict(g192_sha256=sha256(path.read_bytes()).hexdigest(), counts=totals, examples=examples)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stream", type=Path)
    print(json.dumps(check(parser.parse_args().stream), indent=2))
