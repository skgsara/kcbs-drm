"""Reproduce genuine 13.2 kbit/s EVS word pairs from fixed, synthetic PCM inputs."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
import tempfile

import numpy as np

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "scripts"))
from compare_evs_group import read_words

OPTIONS = ["-q", "-no_delay_cmp", "-max_band", "SWB", "13200", "32"]
HIDDEN = (15, 18, 21, 24, 27, 30)
VISIBLE = [i for i in range(33) if i == 0 or i - 1 not in HIDDEN]
RATE = 32000


def voiced(pitch, seed, divisor, start, width, level):
    """Three frames of glottal excitation and formants, with one tapered harmonic burst."""
    t = np.arange(3 * 640)
    phase = np.cumsum(pitch * (1 + .028 * np.sin(t * (2 * np.pi * 3.2 / RATE) + seed)) / RATE)
    pulses = np.flatnonzero(np.diff(phase.astype("int64"), prepend=-1))
    excitation = np.zeros(len(t))
    excitation[pulses] = .78 + .2 * np.cos(pulses * 2 * np.pi * 5 / RATE + .1 * seed)
    s = np.arange(1024, dtype="float64")
    resonances = [(510 + 18 * seed, 90, 1), (1130 + 92 * seed, 125, .47),
                  (2440 + 120 * seed, 180, .27), (3190 + 119 * seed, 200, .17),
                  (8100 + 180 * seed, 1000, .14)]
    kernel = sum(weight * np.sin(s * (2 * np.pi * f / RATE)) * np.exp(-s * np.pi * bw / RATE)
                 for f, bw, weight in resonances)
    envelope = .78 + .17 * np.sin(t * 2 * np.pi * 3.2 / RATE + seed) + .05 * np.sin(t * 2 * np.pi * 10 / RATE)
    signal = np.rint(5000 * np.convolve(excitation, kernel, "full")[:len(t)] * envelope).astype("<i2")
    pcm = np.rint(signal / divisor).astype("<i2")
    k = np.arange(width)
    upper = np.sin(2 * np.pi * (k + .5) * pitch * (2 + seed % 5) / RATE + .39 * seed)
    upper *= np.sin(np.pi * (k + .5) / width) ** 2
    pcm[start:start + width] += np.rint(upper * level).astype("<i2")
    return pcm


def chord(extra_sample):
    """An 84-frame chord. Both inputs include the first unit impulse at sample 506."""
    t = np.arange(84 * 640, dtype=np.float64) / RATE
    ratios = (1, 2.007, 2.990, 4.3, 5.05, 7.12, 11.05, 16.0, 22.8)
    phases = (np.arange(len(ratios)) ** 2 * .37 + .39 * 5) % (2 * np.pi)
    signal = np.zeros_like(t)
    for k, (ratio, phase) in enumerate(zip(ratios, phases)):
        amplitude = 1 / ratio ** (.44 + .13)
        envelope = 1 + .12 * np.sin(2 * np.pi * (.96 + .13 * k) * t + phase)
        signal += amplitude * envelope * np.sin(2 * np.pi * (ratio * 117.35) * t + phase)
    pcm = np.rint(signal * (8500 / np.max(np.abs(signal)))).astype("<i2")
    pcm[506] += 1
    if extra_sample:
        pcm[8 * 640 + 506] += 1
    return pcm


def encode(encoder, pcm, tmp):
    source = tmp / "input.s16le"
    data = pcm.tobytes()
    source.write_bytes(data)
    answer = {}
    words = None
    for label, options in (("g192", []), ("mime", ["-mime"])):
        path = tmp / label
        subprocess.run([encoder, *options, *OPTIONS, source, path], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        coded = list(read_words(path))
        if len(coded) * 640 != len(pcm) or any(len(w) != 33 for w in coded):
            raise ValueError(f"unexpected frame lengths in {label}")
        if words is not None and coded != words:
            raise ValueError("independent G.192 and MIME encodes disagree")
        words = coded
        answer[label + "_sha256"] = sha256(path.read_bytes()).hexdigest()
    answer["input_pcm_sha256"] = sha256(data).hexdigest()
    return words, answer


def compare(encoder, tmp, inputs, slot, expected_bit, expected_mode, expected_following):
    (left, hashes_a), (right, hashes_b) = [encode(encoder, pcm, tmp) for pcm in inputs]
    x, y = left[slot], right[slot]
    differences = [bit for bit in range(264) if (x[bit // 8] ^ y[bit // 8]) & (128 >> (bit % 8))]
    projected = bytes(x[i] for i in VISIBLE)
    if differences != [expected_bit] or projected != bytes(y[i] for i in VISIBLE):
        raise ValueError("fixed stock sender pair did not reproduce its single-bit difference")
    if x[0] != expected_mode or slot % 4 != 1:
        raise ValueError("unexpected mode or position")
    equal = [a == b for a, b in zip(left, right, strict=True)]
    after = equal[slot + 1:]
    following = after.index(False) if False in after else len(after)
    if not all(equal[:slot]) or following != expected_following:
        raise ValueError("fixed encoder history or succeeding words changed")
    offset = expected_bit // 8 - 1
    differences_pcm = np.flatnonzero(inputs[0] != inputs[1])
    return dict(
        slot_zero_based=slot, position=2, total_words_per_input=len(left), mode_hex=f"{x[0]:02X}",
        payload_offset=offset, differing_word_bit_msb_first=expected_bit,
        differing_octets_hex=[f"{w[offset + 1]:02X}" for w in (x, y)],
        full_words_hex=[x.hex(), y.hex()], matching_projection_hex=projected.hex(),
        input_stream_hashes=[hashes_a, hashes_b], changed_pcm_samples=len(differences_pcm),
        first_changed_pcm_sample=int(differences_pcm[0]), last_changed_pcm_sample=int(differences_pcm[-1]),
        identical_preceding_run=slot, identical_following_run=following,
        adjacent_word_sha256={f"slot_{i}": [sha256(left[i]).hexdigest(), sha256(right[i]).hexdigest()]
                              for i in (slot - 1, slot + 1)},
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--encoder", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    encoder = args.encoder.resolve()
    if args.out.resolve() == encoder:
        parser.error("use a separate report path")
    with tempfile.TemporaryDirectory() as td:
        directory = Path(td)
        cases = {
            "acelp_p24": ([voiced(181, 3, 16, start, 48, level)
                           for start, level in ((920, -24), (800, -12))], 1, 207, 0x61, 0),
            "acelp_p27": ([voiced(124, 5, 64, 880, 96, level) for level in (-6, -8)], 1, 231, 0x5a, 0),
            "tcx20_p27": ([chord(False), chord(True)], 9, 229, 0xfe, 2),
        }
        results = {name: compare(encoder, directory, *case) for name, case in cases.items()}
    report = dict(encoder_sha256=sha256(encoder.read_bytes()).hexdigest(),
                  source="synthetic PCM at 32000 Hz, mono signed little-endian 16 bit",
                  stock_options=OPTIONS, omitted_payload_offsets=HIDDEN,
                  matching_word_octets_per_projection=len(VISIBLE), cases=results)
    args.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
