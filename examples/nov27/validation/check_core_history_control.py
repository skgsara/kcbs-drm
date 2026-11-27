"""Test the core-history predictions on a newly encoded, deterministic 48-second signal."""
import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import tempfile

import numpy as np

from check_p2_codec_bits import ROOT, synthetic_pcm
from build_evs_gcc_independent import linux_command
from compare_evs_group import read_words
from evs_core_history import core_history


GROUP_SIZE = 60
FIELDS = {6: "hq_bit6", 8: "tcx_bit8"}


def transformed_pcm():
    samples = np.frombuffer(synthetic_pcm(), dtype="<i2")
    inverted = -samples[::-1].astype(np.int32)
    return np.clip(inverted, -32768, 32767).astype("<i2").tobytes()


def target_bit(mode):
    if mode >> 3 not in (29, 30, 31):
        return None
    return 8 if mode & 0x04 else 6


def predictions(modes, counter, hq_fill):
    slots = []
    for slot, mode in enumerate(modes):
        # HQ word bit 6 is in its mode octet. Replace it everywhere, including
        # when this octet will become the previous mode for the following slot.
        if target_bit(mode) == 6:
            mode = (mode & ~0x02) | (hq_fill << 1)
        slots.append(dict(slot=slot, counter=counter, phase=slot // 20, cycle=(slot % 20) // 4,
                          position=1 + slot % 4, receipt="received_du",
                          octets=" ".join([f"{mode:02x}"] + ["??"] * 32)))
    rows = core_history(slots)["slots"]
    if [row["slot"] for row in rows] != list(range(GROUP_SIZE)) or rows[0]["predicted"] is not None:
        raise ValueError("Expected ordered group slots and abstention at the first slot")
    # The public API can compare HQ's mode bit. Its observation and match
    # fields never participate in this test; only its predicted bit is kept.
    return [(r["target_word_bit"], r["predicted"]) for r in rows]


def score(group, counter, totals):
    modes = [w[0] for w in group]
    estimates = predictions(modes, counter, hq_fill=0)
    if estimates != predictions(modes, counter, hq_fill=1):
        raise ValueError("A prediction changed when only the hidden HQ target bits were toggled")
    for slot in range(1, GROUP_SIZE):
        bit = target_bit(modes[slot])
        proposed_bit, value = estimates[slot]
        if bit is None:
            if value is not None:
                raise ValueError("Prediction outside the selected MDCT mode indices")
            continue
        counts = totals[bit][1 + slot % 4]
        counts["eligible"] += 1
        if value is None:
            counts["abstained"] += 1
            continue
        if proposed_bit != bit or value not in (0, 1):
            raise ValueError("Unexpected target or predicted bit value")
        byte, bit_in_byte = divmod(bit, 8)
        mask = 1 << (7 - bit_in_byte)
        original = group[slot][byte]
        actual = int(bool(original & mask))
        inverted = int(bool((original ^ mask) & mask))
        counts["predicted_" + str(value)] += 1
        counts["predicted"] += 1
        counts["errors"] += value != actual
        counts["inverted_target_errors"] += value != inverted


def intra_rows(group, counter, variant):
    from evs_intra_word import intra_word

    slots = []
    for slot, word in enumerate(group):
        mode = word[0]
        octets = [f"{mode:02x}"] + ["??"] * 32
        if mode >> 3 in (8, 14):
            octet = word[5]
            if variant != "original":
                if mode >> 3 == 8:
                    octet = (octet & 0x7f) | (0x80 if variant == "outside" else 0)
                else:
                    octet = (octet & 0xf0) | (11 if variant == "outside" else 10)
            octets[5] = f"{octet:02x}"
        # Word octet 1, which contains the HQ target, stays unknown in every variant.
        slots.append(dict(slot=slot, counter=counter, phase=slot // 20, cycle=(slot % 20) // 4,
                          position=1 + slot % 4, receipt="received_du", octets=" ".join(octets)))
    return {r["slot"]: r for r in intra_word(slots)["slots"]}


def score_intra_words(words):
    totals = {name: Counter() for name in ("swb_hq_class", "wb_gsc_audio", "swb_gsc_inactive")}
    for start in range(0, len(words), GROUP_SIZE):
        group = words[start:start + GROUP_SIZE]
        cases = {v: intra_rows(group, start // GROUP_SIZE, v) for v in ("original", "inside", "outside")}
        expected_slots = {i for i, w in enumerate(group) if w[0] == 0xf9 or w[0] >> 3 in (8, 14)}
        if any(rows.keys() != expected_slots for rows in cases.values()):
            raise ValueError("Intra-word check did not return the expected applicable slots")
        for slot in expected_slots:
            word = group[slot]
            row = cases["original"][slot]
            counts = totals[row["check"]]
            counts["eligible"] += 1
            if word[0] == 0xf9:
                if (row["check"], row["outcome"], row["observed"], list(row["allowed"])) != (
                        "swb_hq_class", "conditional", None, [0, 0]):
                    raise ValueError("Expected an unobserved HQ bit with zero as the only allowed value")
                observed = word[1] >> 7
                counts["predicted_0"] += 1
                counts["errors"] += observed != 0
                counts["inverted_target_errors"] += (observed ^ 1) != 0
            else:
                if word[0] >> 3 == 8:
                    label, observed, upper = "wb_gsc_audio", word[5] >> 7, 0
                else:
                    label, observed, upper = "swb_gsc_inactive", word[5] & 15, 10
                if (row["check"], row["observed"], list(row["allowed"])) != (label, observed, [0, upper]):
                    raise ValueError("GSC field extraction or bounds disagree with the native word")
                counts["native_" + row["outcome"]] += 1
                counts["inside_" + cases["inside"][slot]["outcome"]] += 1
                counts["outside_" + cases["outside"][slot]["outcome"]] += 1
    return totals


def run(encoder, include_intra=False):
    pcm = transformed_pcm()
    with tempfile.TemporaryDirectory() as scratch:
        source, stream = Path(scratch) / "reversed.s16", Path(scratch) / "native.192"
        source.write_bytes(pcm)
        args = linux_command(encoder, "-q", "-no_delay_cmp", "-max_band", "SWB",
                             "13200", "32", source, stream)
        subprocess.run(args, check=True, stdout=subprocess.DEVNULL)
        stream_hash = sha256(stream.read_bytes()).hexdigest()
        words = list(read_words(stream))
    if len(words) != 2400 or any(len(w) != 33 for w in words):
        raise ValueError("Expected 2,400 uninterrupted native 13.2 kb/s words")
    labels = ("eligible", "abstained", "predicted", "predicted_0", "predicted_1",
              "errors", "inverted_target_errors")
    totals = {bit: {p: Counter(dict.fromkeys(labels, 0)) for p in range(1, 5)} for bit in FIELDS}
    for start in range(0, len(words), GROUP_SIZE):
        score(words[start:start + GROUP_SIZE], start // GROUP_SIZE, totals)
    result = {}
    for bit, name in FIELDS.items():
        positions = totals[bit]
        summary = {label: sum(row[label] for row in positions.values()) for label in labels}
        result[name] = {"total": summary, "by_position": positions}
    report = {"stimulus": "synthetic_pcm reversed in time, negated in int32, clipped to int16",
              "sample_rate_hz": 32000, "pcm_samples": len(pcm) // 2, "pcm_sha256": sha256(pcm).hexdigest(),
              "native_g192_sha256": stream_hash, "encoder_sha256": sha256(encoder.read_bytes()).hexdigest(),
              "words": len(words), "skipped_group_starts": len(words) // GROUP_SIZE,
              "post_boundary_slots": len(words) - len(words) // GROUP_SIZE, "fields": result}
    if include_intra:
        report["intra_word_all_slots"] = score_intra_words(words)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--encoder", type=Path, default=ROOT / "work/evs_gcc_independent/EVS_cod")
    parser.add_argument("--intra-word", action="store_true", help="also check the independent single-word fields")
    args = parser.parse_args()
    print(json.dumps(run(args.encoder.resolve(), args.intra_word), indent=2))
