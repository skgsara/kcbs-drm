"""Reproduce two standard EVS words differing in one withheld bit at the same slot."""
import argparse
from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
import tempfile

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))
from build_evs_gcc_independent import linux_command
from compare_evs_group import read_words


@dataclass(frozen=True)
class Case:
    description: str
    frequency_hz: int
    amplitude: int
    pulse_levels: tuple[int, int]
    slot: int
    mode: int
    differing_bit: int
    differing_octets: tuple[int, int]


CASES = {
    "gsc": Case("SWB GSC INACTIVE on digital silence with sparse pulses",
                0, 0, (+1, +2), 85, 0x74, 255, (0x16, 0x17)),
    "tcx": Case("TCX20 on a 1 kHz sine wave with sparse pulses",
                1000, 4096, (+8, -16), 25, 0xFE, 253, (0x59, 0x5D)),
}
OMITTED_PAYLOAD_OFFSETS = (15, 18, 21, 24, 27, 30)
VISIBLE = tuple(i for i in range(33) if i - 1 not in OMITTED_PAYLOAD_OFFSETS)


def encode(encoder, directory, case, level):
    # At 32 kHz an EVS frame lasts 640 samples. Add a pulse every fourth frame.
    times = np.arange(120 * 640) / 32000
    pcm = np.rint(case.amplitude * np.sin(2 * np.pi * case.frequency_hz * times)).astype("<i2")
    for frame in range(0, 120, 4):
        sample = frame * 640 + (137 * frame + 137) % 640
        pcm[sample] += level
    source = directory / f"level-{level}.s16"
    answer = directory / f"level-{level}.192"
    source.write_bytes(pcm.tobytes())
    subprocess.run(linux_command(encoder, "-q", "-no_delay_cmp", "-max_band", "SWB",
                                 "13200", "32", source, answer), check=True, stdout=subprocess.DEVNULL)
    words = list(read_words(answer))
    if len(words) != 120 or any(len(w) != 33 for w in words):
        raise ValueError("Expected 120 uninterrupted native EVS words")
    info = {"pulse_level_int16": level, "pcm_sha256": sha256(pcm.tobytes()).hexdigest(),
            "g192_sha256": sha256(answer.read_bytes()).hexdigest()}
    return words, info


def chronology(slot, different):
    before = [i for i in different if i < slot]
    after = [i for i in different if i > slot]
    group_start = slot // 60 * 60
    return {"first_difference_slot": min(different, default=None),
            "identical_from_start_before_target": min(before, default=slot),
            "consecutive_matches_immediately_before_target": slot - 1 - max(before, default=-1),
            "earlier_matching_slots": slot - len(before), "earlier_slots": slot,
            "other_matching_slots_in_group": 59 - sum(group_start <= i < group_start + 60
                                                       and i != slot for i in different),
            "other_slots_in_group": 59, "first_later_difference_slot": min(after, default=None),
            "later_differing_slots": len(after)}


def run(encoder, case_name="gsc"):
    case = CASES[case_name]
    slot = case.slot
    with tempfile.TemporaryDirectory() as tmp:
        left, first = encode(encoder, Path(tmp), case, case.pulse_levels[0])
        right, second = encode(encoder, Path(tmp), case, case.pulse_levels[1])
    pairs = list(zip(left, right, strict=True))
    a, b = pairs[slot]
    full_differences = [i for i, (u, v) in enumerate(pairs) if u != v]
    visible_differences = [i for i, (u, v) in enumerate(pairs) if any(u[j] != v[j] for j in VISIBLE)]
    changed_bits = [bit for bit in range(264) if (a[bit // 8] ^ b[bit // 8]) & (0x80 >> (bit % 8))]
    j = case.differing_bit // 8
    if (slot in visible_differences or changed_bits != [case.differing_bit] or
            a[0] != case.mode or (a[j], b[j]) != case.differing_octets):
        raise ValueError(f"The native {case_name} one-bit specimen did not reproduce")
    return {"case": case_name, "stimulus": case.description, "base_frequency_hz": case.frequency_hz,
            "base_amplitude_int16": case.amplitude,
            "sample_rate_hz": 32000, "samples_per_input": 76800, "words_per_input": len(pairs),
            "encoder_sha256": sha256(encoder.read_bytes()).hexdigest(), "inputs": [first, second],
            "global_slot_zero_based": slot, "group_zero_based": slot // 60,
            "slot_within_group_zero_based": slot % 60, "position_one_based": 1 + slot % 4,
            "native_words_hex": [a.hex(), b.hex()], "mode_octet_hex": f"{a[0]:02x}",
            "omitted_zero_based_payload_offsets": OMITTED_PAYLOAD_OFFSETS,
            "identical_27_byte_projection_hex": bytes(a[k] for k in VISIBLE).hex(),
            "differing_word_bits_msb_first": changed_bits, "differing_payload_offset": j - 1,
            "differing_octets_hex": [f"{a[j]:02x}", f"{b[j]:02x}"],
            "full_word_history": chronology(slot, full_differences),
            "visible_projection_history": chronology(slot, visible_differences)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--encoder", type=Path, default=ROOT / "work/evs_gcc_independent/EVS_cod")
    parser.add_argument("--case", choices=CASES, default="gsc",
                        help="gsc: silence with pulses (default); tcx: 1 kHz tone with pulses")
    args = parser.parse_args()
    print(json.dumps(run(args.encoder.resolve(), args.case), indent=2))
