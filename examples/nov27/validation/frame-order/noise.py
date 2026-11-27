"""Enumerate TCX20 noise-fill histories, or score uninterrupted ordinary 13.2 kb/s clear words."""
import argparse
import json
from pathlib import Path
import sys


def update(memory, raw):
    """TS 26.443 lib_enc/cod_tcx.c:843–863. Return sender memory and emitted index."""
    if raw == 1:
        return 1 + abs(memory), 1
    if raw == 2 and abs(memory) > 5:
        return (5 if memory < 0 else -1 - memory), 1
    return 0, raw


def grammar():
    # All memories with the same sign and magnitude >= 6 have equivalent future outputs.
    possible = {0}
    rows = []
    while True:
        choices = [update(m, raw) for m in possible for raw in range(8)]
        rows.append({"ones_after_non1_anchor": len(rows),
                     "possible_next_indices": sorted({emitted for _, emitted in choices})})
        after_one = {max(-6, min(6, m)) for m, emitted in choices if emitted == 1}
        if after_one == possible:
            break
        possible = after_one

    witnesses = []
    for nibble in range(16):
        # b9 selects one of the overlapping three-bit intervals within b48..51.
        fields = (nibble >> 1, nibble & 7)
        raw = next(v for v in fields if v != 1)
        if update(0, raw) != (0, raw):
            raise ValueError("The proposed sparse-input witness failed")
        witnesses.append({"p5_high_nibble": f"{nibble:x}", "possible_fields": fields,
                          "index_preserving_zero_memory": raw})
    return {"anchored_history": rows, "stable_from_ones": rows[-1]["ones_after_non1_anchor"],
            "sparse_nibble_witnesses": witnesses,
            "scope": "For the noise rule alone, each nibble has a choice that emits its index and keeps memory zero."}


def score(words):
    # Full-word controls must be in transmission order. Bit zero is the mode MSB.
    prior_band = None
    run = None
    trials = []
    total = tcx = 0
    for slot, word in enumerate(words):
        total += 1
        if not word or word[0] >> 3 < 29 or not word[0] & 4:
            prior_band = run = None
            continue
        band = word[0] >> 3
        if band != prior_band:
            run = None
        tcx += 1
        # A non-1 transmitted index resets memory. Test before using the current index.
        restrict = run in (6, 7)
        # One or two overlap bits, 31 LPC bits and seven gain bits precede this field.
        start = 49 if word[1] & 0x40 else 48
        current = (word[6] >> (53 - start)) & 7
        if restrict:
            trials.append({"slot": slot, "non1_anchor_slot": slot - run - 1, "preceding_ones": run,
                           "noise_start_bit": start, "excluded": 2, "observed": current})
        if current != 1:
            run = 0
        elif run is not None:
            run += 1
        prior_band = band
    return {"slots": total, "tcx20_slots": tcx, "tested": len(trials),
            "contradictions": sum(row["observed"] == 2 for row in trials), "trials": trials}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--words", type=Path, help="chronological clear G.192 or mono EVS storage at 13.2 kb/s")
    args = parser.parse_args()
    if args.words is None:
        result = grammar()
    else:
        sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "scripts"))
        from compare_evs_group import read_words
        result = score(read_words(args.words))
    print(json.dumps(result, indent=2))
