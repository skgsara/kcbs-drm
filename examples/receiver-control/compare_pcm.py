"""Compare decoded audio from received and uninterrupted timelines, keeping word equality separate."""
import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import sys

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "scripts"))
from compare_evs_group import read_words


def compare(received_words, received_pcm, reference_pcm):
    sender = json.loads((HERE / "fixture/sender.json").read_bytes())
    original = list(read_words(HERE / "fixture/sender.192.gz"))
    emitted = list(read_words(received_words))
    ref, got = reference_pcm.read_bytes(), received_pcm.read_bytes()
    if sha256(ref).hexdigest() != sender["direct_decoder"]["pcm_sha256"]:
        raise ValueError("uninterrupted PCM differs from the pinned 16 kHz sender decode")
    if len(original) != len(emitted) or len(got) != len(ref) or len(ref) != 640 * len(original):
        raise ValueError("word and 16 kHz PCM timelines differ in length")
    a = np.frombuffer(ref, dtype="<i2").reshape(-1, 320)
    b = np.frombuffer(got, dtype="<i2").reshape(-1, 320)
    counts, samples, first = {}, {}, {}
    last_loss = None
    for slot, (expected, received) in enumerate(zip(original, emitted, strict=True)):
        if not received:
            state = "erasure"
            last_loss = slot
        elif received != expected:
            state = "wrong_word"
        elif last_loss is None:
            state = "exact_word_before_first_erasure"
        else:
            state = "exact_word_after_erasure"
        wrong = int(np.count_nonzero(a[slot] != b[slot]))
        counts.setdefault(state, Counter())["some_samples_differ" if wrong else "all_samples_match"] += 1
        samples[state] = samples.get(state, 0) + wrong
        if wrong and state not in first:
            first[state] = dict(zero_based_slot=slot, samples_different=wrong,
                                slots_since_last_erasure=None if last_loss is None else slot - last_loss)
    return dict(sample_rate_hz=16000, samples_per_slot=320, slots=len(original),
                reference_pcm_sha256=sha256(ref).hexdigest(), received_pcm_sha256=sha256(got).hexdigest(),
                frames_by_word_and_audio_result=counts, unequal_pcm_samples=samples, first_example=first)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for arg in ("received_words", "received_pcm", "reference_pcm"):
        parser.add_argument(arg, type=Path)
    args = parser.parse_args()
    print(json.dumps(compare(args.received_words, args.received_pcm, args.reference_pcm), indent=2))
