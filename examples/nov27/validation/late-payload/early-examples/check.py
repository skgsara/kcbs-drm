"""Replay three fixed pairs of original synthetic EVS sender words using a stock encoder."""
import argparse
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from sender_pairs import RATE, VISIBLE, encode, voiced
from check_evs_origin import PROJECTED_OCTETS


def shape34(harmonic_level):
    """Generate 84 frames of the original 411.2 Hz polyphonic shape, with one optional harmonic."""
    time = np.arange(84 * 640, dtype=np.float64) / RATE
    pitch = 411.2
    ratios = np.array([1, 1.492, 2.489, 3.985, 6.006, 10.04, 13.935, 18.0, 25.0])
    phases = (np.arange(len(ratios)) ** 2 * 0.37 + 0.39 * 34) % (2 * np.pi)
    signal = np.zeros_like(time)
    for index, (ratio, phase) in enumerate(zip(ratios, phases, strict=True)):
        frequency = ratio * pitch
        amplitude = 1 / ratio ** (0.44 + 2 * 0.13)
        envelope = 1 + 0.04 * np.sin(2 * np.pi * (0.96 + index * 0.13) * time + phase)
        signal += amplitude * envelope * np.sin(2 * np.pi * frequency * time + phase)
    pcm = np.rint(signal * (8500 / np.max(np.abs(signal)))).astype("<i2")
    harmonic = np.sin(2 * np.pi * pitch * ratios[2] * time + phases[2])
    return pcm + np.rint(harmonic * harmonic_level).astype("<i2")


def check(case, encoder, directory):
    generator = {"shape34": shape34, "voiced": voiced}[case["generator"]]
    streams = []
    slot = case["slot_zero_based"]
    for source in case["inputs"]:
        pcm = generator(*source["arguments"])
        words, hashes = encode(encoder, pcm, directory)
        if (len(words) != case["frames_per_input"] or
                hashes["input_pcm_sha256"] != source["pcm_sha256"] or
                hashes["g192_sha256"] != source["g192_sha256"] or
                words[slot].hex() != source["word_hex"]):
            raise ValueError(f"source PCM, complete G.192 stream or target word differs for {source['arguments']}")
        streams.append(words)
    left, right = streams
    a, b = left[slot], right[slot]
    differences = [bit for bit in range(264) if (a[bit // 8] ^ b[bit // 8]) & (128 >> (bit % 8))]
    offset = case["payload_offset"]
    if (differences != case["differing_word_bits"] or {bit // 8 - 1 for bit in differences} != {offset}
            or any(a[index] != b[index] for index in VISIBLE)
            or f"{a[0]:02X}" != case["mode"] or slot % 4 + 1 != case["quartet_position"]
            or [left[i] == right[i] for i in (slot - 1, slot + 1)] != case["equal_adjacent_words"]):
        raise ValueError(f"word differences or adjacent frame equality differ for p{offset}")
    result = dict(payload_offset=offset, slot_zero_based=slot, differing_word_bits=differences,
                  target_octets=[f"{a[offset + 1]:02X}", f"{b[offset + 1]:02X}"],
                  equal_adjacent_words=case["equal_adjacent_words"])
    if len(left) >= 60:
        direct_equal = [all(x[j] == y[j] for j in PROJECTED_OCTETS)
                        for x, y in zip(left[:60], right[:60], strict=True)]
        target_position = direct_equal[slot % 4::4]
        context = dict(direct_word_octets=len(PROJECTED_OCTETS), matching_slots=sum(direct_equal),
                       group_slots=len(direct_equal), matching_target_position_slots=sum(target_position),
                       target_position_slots=len(target_position))
        if context != case["group0_direct_agreement"]:
            raise ValueError("first group's direct projection differs from its stock reference")
        result["group0_direct_agreement"] = context
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--encoder", type=Path, required=True)
    args = parser.parse_args()
    fixture = json.loads((HERE / "receipt.json").read_text(encoding="utf-8"))
    with TemporaryDirectory() as tmp:
        rows = [check(case, args.encoder.resolve(), Path(tmp)) for case in fixture["cases"]]
    print(json.dumps(rows, indent=2))
