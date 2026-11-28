"""Encode two synthetic PCM histories with both reference implementations and score b40–43."""
import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import struct
import subprocess
import sys
from tempfile import TemporaryDirectory

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[3] / "scripts"))
from compare_evs_group import read_words

OPTIONS = ["-q", "-no_delay_cmp", "-max_band", "SWB", "13200", "32"]
FRAMES = 120
FRAME_SAMPLES = 640


def stimulus(name):
    quiet = bytes(FRAME_SAMPLES * 2)
    if name == "silence":
        return quiet * FRAMES
    # Exactly 1 kHz at 32 kHz. Fifty active frames precede seventy silent frames.
    period = struct.pack("<32h", *([4096] * 16 + [-4096] * 16))
    return period * (50 * FRAME_SAMPLES // 32) + quiet * 70


def run(encoder, source, output):
    subprocess.run([str(encoder), *OPTIONS, str(source), str(output)],
                   check=True, stdout=sys.stderr, stderr=sys.stderr)
    words = list(read_words(output))
    if len(words) != FRAMES or any(len(word) != 33 for word in words):
        raise ValueError("expected 120 complete 264-bit EVS Primary words")

    modes = Counter()
    nibbles = Counter()
    first = None
    for slot, word in enumerate(words):
        if 0x74 <= word[0] <= 0x77:
            if first is None:
                first = slot
            modes[f"{word[0]:02X}"] += 1
            nibbles[f"{word[5] >> 4:X}"] += 1
    summary = dict(g192_sha256=sha256(output.read_bytes()).hexdigest(), total=len(words),
                mode_histogram=dict(sorted(modes.items())), nibble_histogram=dict(sorted(nibbles.items())),
                first_eligible_slot=first, eligible=sum(nibbles.values()),
                inactive_tbe=sum(0x70 <= word[0] <= 0x73 for word in words))
    return summary, words


def compare_silent_suffix(silence, after_square):
    start = 50
    same_word = 0
    same_inactive_mode = 0
    inactive_differences = []
    first = None
    for slot in range(start, FRAMES):
        left, right = silence[slot], after_square[slot]
        same_word += left == right
        if left[0] == right[0] and 0x74 <= left[0] <= 0x77:
            same_inactive_mode += 1
            if left != right:
                inactive_differences.append(slot)
                if first is None:
                    first = dict(slot=slot, mode=f"{left[0]:02X}",
                                 differing_bits=sum((a ^ b).bit_count() for a, b in zip(left, right, strict=True)),
                                 silence_word_sha256=sha256(left).hexdigest(),
                                 after_square_word_sha256=sha256(right).hexdigest())
    return dict(first_slot=start, last_slot=FRAMES - 1, same_pcm_slots=FRAMES - start,
                identical_complete_words=same_word, different_complete_words=FRAMES - start - same_word,
                same_inactive_mode_slots=same_inactive_mode,
                identical_words_with_same_inactive_mode=same_inactive_mode - len(inactive_differences),
                different_words_with_same_inactive_mode=len(inactive_differences), first_inactive_difference=first)



def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixed", required=True, type=Path, help="TS 26.442 encoder")
    parser.add_argument("--float", required=True, type=Path, help="TS 26.443 encoder")
    args = parser.parse_args()
    encoders = {name: path.resolve(strict=True) for name, path in vars(args).items()}
    report = dict(options=OPTIONS, encoder_sha256={name: sha256(path.read_bytes()).hexdigest()
                                                   for name, path in encoders.items()}, cases={})
    histories = {name: {} for name in encoders}
    with TemporaryDirectory() as tmp:
        directory = Path(tmp)
        for case in ("silence", "square_then_silence"):
            source = directory / (case + ".s16")
            data = stimulus(case)
            source.write_bytes(data)
            outcomes = {}
            for name, path in encoders.items():
                outcomes[name], histories[name][case] = run(path, source, directory / f"{case}-{name}.192")
            report["cases"][case] = dict(pcm_sha256=sha256(data).hexdigest(), encoders=outcomes)
    start_byte = 50 * FRAME_SAMPLES * 2
    suffix = stimulus("silence")[start_byte:]
    if suffix != stimulus("square_then_silence")[start_byte:]:
        raise ValueError("suffix PCM differs between the two histories")
    report["same_pcm_suffix"] = dict(pcm_sha256=sha256(suffix).hexdigest(),
        encoders={name: compare_silent_suffix(cases["silence"], cases["square_then_silence"])
                  for name, cases in histories.items()})
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
