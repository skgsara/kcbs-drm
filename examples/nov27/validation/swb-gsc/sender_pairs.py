"""Compare two pairs of genuine SWB AUDIO GSC words from fixed synthetic PCM."""
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
RATE = 32000
FRAME = 640
FRAMES = 240
SLOT = 205
OMITTED = [15, 18, 21, 24, 27, 30]
VISIBLE = [i for i in range(33) if i - 1 not in OMITTED]


def synthetic_source():
    """First five seconds of the fixed synthetic SWB receiver control (32 kHz)."""
    rng = np.random.default_rng(13200)
    t = np.arange(RATE) / RATE
    envelope = (.5 + .5 * np.sin(2 * np.pi * 3.2 * t)) ** 2
    seconds = []
    for i, f in enumerate((128, 165, 230, 320, 115)):
        harmonic = sum(np.cos(2 * np.pi * j * (f * t + .5 * (5 + i) * t * t)) / j ** .8
                       for j in range(1, 80))
        noise = rng.normal(size=RATE)
        material = (harmonic * envelope, .4 * noise * envelope, harmonic * .05 + .1 * noise,
                    np.zeros(RATE))[i % 4]
        seconds.append(np.clip(3500 * material, -32000, 32000).astype("<i2"))
    return np.concatenate(seconds)


def encode(encoder, pcm, directory):
    source = directory / "input.s16le"
    source.write_bytes(pcm.tobytes())
    hashes = {"input_pcm_sha256": sha256(pcm.tobytes()).hexdigest()}
    streams = []
    for name, options in (("g192", []), ("mime", ["-mime"])):
        dest = directory / name
        subprocess.run([encoder, *options, *OPTIONS, source, dest], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        hashes[name + "_sha256"] = sha256(dest.read_bytes()).hexdigest()
        streams.append(list(read_words(dest)))
    if streams[0] != streams[1] or len(streams[0]) != FRAMES or any(len(w) != 33 for w in streams[0]):
        raise ValueError("expected independently matching G.192 and mono EVS storage encodes")
    return streams[0], hashes


def compare(encoder, directory, source, origin, start, width, hz, levels, mode, expected_bit):
    base = source[origin * FRAME:(origin + FRAMES) * FRAME]
    if len(base) != FRAMES * FRAME:
        raise ValueError("source does not cover encoder interval")
    k = np.arange(width)
    burst = np.sin(2 * np.pi * (k + .5) * hz / RATE) * np.sin(np.pi * (k + .5) / width) ** 2
    waves = []
    first = SLOT * FRAME + start
    for level in levels:
        pcm = base.copy()
        pcm[first:first + width] += np.rint(burst * level).astype("<i2")
        waves.append(pcm)
    (left, hashes_a), (right, hashes_b) = [encode(encoder, pcm, directory) for pcm in waves]
    x, y = left[SLOT], right[SLOT]
    bits = [i for i in range(264) if (x[i // 8] ^ y[i // 8]) & (128 >> (i % 8))]
    if bits != [expected_bit] or x[0] != mode or y[0] != mode:
        raise ValueError("stock encoder did not reproduce the registered bit and SWB GSC mode")
    visible = bytes(x[i] for i in VISIBLE)
    if visible != bytes(y[i] for i in VISIBLE):
        raise ValueError("visible projection differs")
    different_slots = [i for i, (a, b) in enumerate(zip(left, right, strict=True)) if a != b]
    if different_slots[0] != SLOT:
        raise ValueError("encoder history differs before the selected slot")
    following = next((i for i in different_slots if i > SLOT), FRAMES) - SLOT - 1
    changed = np.flatnonzero(waves[0] != waves[1])
    return dict(
        source_start_frame=origin, slot_zero_based=SLOT, position=1 + SLOT % 4,
        signalling_octet_hex=f"{mode:02X}", family="SWB GSC AUDIO / SWB_BWE",
        payload_offset=expected_bit // 8 - 1, differing_physical_bit_msb_first=expected_bit,
        differing_octets_hex=[f"{w[expected_bit // 8]:02X}" for w in (x, y)],
        complete_words_hex=[x.hex(), y.hex()], matching_visible_octets_hex=visible.hex(),
        differing_encoded_slots=different_slots, consecutive_matching_predecessors=SLOT,
        consecutive_matching_successors=following,
        neighboring_word_sha256={f"slot_{i}": [sha256(left[i]).hexdigest(), sha256(right[i]).hexdigest()]
                                 for i in (SLOT - 1, SLOT + 1)},
        pcm_burst=dict(offset_in_frame=start, length_samples=width, frequency_hz=hz, levels=levels),
        changed_pcm_samples=len(changed), first_changed_sample=int(changed[0]), last_changed_sample=int(changed[-1]),
        sender_streams=[hashes_a, hashes_b],
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--encoder", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    encoder = args.encoder.resolve()
    if args.out.resolve() == encoder:
        parser.error("use a separate report path")
    source = synthetic_source()
    with tempfile.TemporaryDirectory() as td:
        directory = Path(td)
        p24 = compare(encoder, directory, source, 3, 80, 288, 5150, (-84, 104), 0x6c, 203)
        p27 = compare(encoder, directory, source, 1, 0, 256, 1830, (120, 140), 0x6f, 225)
    report = dict(encoder_sha256=sha256(encoder.read_bytes()).hexdigest(), stock_options=OPTIONS,
                  synthetic_source_sha256=sha256(source.tobytes()).hexdigest(),
                  frame_count_per_encode=FRAMES, input_format="32 kHz mono signed little-endian 16-bit PCM",
                  omitted_payload_offsets=OMITTED, matching_projection_octets=len(VISIBLE), p24=p24, p27=p27)
    args.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
