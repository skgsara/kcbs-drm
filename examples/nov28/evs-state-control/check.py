"""Measure decoder history on the two published pairs of synthetic GSC streams."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
import tempfile

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
SENDER = ROOT / "examples/nov27/validation/swb-gsc"
sys.path.insert(0, str(SENDER))
import sender_pairs


def encode_originals(encoder, source, fixture, directory):
    start = fixture["source_start_frame"] * sender_pairs.FRAME
    length = sender_pairs.FRAMES * sender_pairs.FRAME
    burst = fixture["pcm_burst"]
    k = np.arange(burst["length_samples"]) + 0.5
    pulse = np.sin(2 * np.pi * k * burst["frequency_hz"] / sender_pairs.RATE)
    pulse *= np.sin(np.pi * k / len(k)) ** 2
    first = fixture["slot_zero_based"] * sender_pairs.FRAME + burst["offset_in_frame"]
    streams = []
    words = []
    for side, (level, expected) in enumerate(zip(burst["levels"], fixture["sender_streams"], strict=True)):
        scratch = directory / str(side)
        scratch.mkdir()
        pcm = source[start:start + length].copy()
        pcm[first:first + len(k)] += np.rint(pulse * level).astype("<i2")
        frames, hashes = sender_pairs.encode(encoder, pcm, scratch)
        if hashes != expected:
            raise ValueError(f"side {side} differs from the published synthetic PCM or encoder output")
        words.append(frames)
        streams.append(scratch / "g192")
    different = np.array([a != b for a, b in zip(*words, strict=True)])
    if np.flatnonzero(different).tolist() != fixture["differing_encoded_slots"]:
        raise ValueError("encoded slots differ from the published original comparison")
    return streams, different


def decode(decoder, stream, rate_khz, frame_count):
    output = stream.with_suffix(f".{rate_khz}.pcm")
    process = subprocess.run([decoder, "-q", "-no_delay_cmp", str(rate_khz), stream, output],
                             stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    if process.returncode:
        raise RuntimeError(process.stderr.decode(errors="replace"))
    pcm = np.frombuffer(output.read_bytes(), dtype="<i2")
    return pcm.reshape(frame_count, 20 * rate_khz)


def runs(mask):
    """Half-open runs of true values in a one-dimensional boolean array."""
    boundaries = np.flatnonzero(np.diff(np.r_[False, mask, False]))
    return boundaries.reshape(-1, 2).tolist()


def measure(decoder, streams, different_words, rate_khz):
    left, right = [decode(decoder, p, rate_khz, len(different_words)) for p in streams]
    delta = left != right
    changed_samples = np.flatnonzero(delta)
    changed_frames = delta.any(axis=1)
    changed_inputs = np.flatnonzero(different_words)
    first_word, tail = int(changed_inputs[0]), int(changed_inputs[-1] + 1)
    if changed_frames[:first_word].any():
        raise ValueError("identical inputs from reset yielded different prefix samples")

    # Each original has 240 supplied, 264-bit G.192 words. Preserve their
    # original headers and bit symbols when extracting the common suffix.
    word_bytes = 4 + 2 * 264
    suffixes = []
    for stream in streams:
        data = stream.read_bytes()
        if len(data) != len(different_words) * word_bytes:
            raise ValueError("unexpected G.192 stream length")
        suffix = stream.with_name("suffix.192")
        suffix.write_bytes(data[tail * word_bytes:])
        suffixes.append(suffix)
    if suffixes[0].read_bytes() != suffixes[1].read_bytes():
        raise ValueError("the encoder streams differ inside the declared common suffix")
    cold_a, cold_b = [decode(decoder, p, rate_khz, len(different_words) - tail) for p in suffixes]
    if not np.array_equal(cold_a, cold_b):
        raise ValueError("identical suffixes decoded differently from reset")
    return dict(
        pcm_sha256=[sha256(pcm.tobytes()).hexdigest() for pcm in (left, right)],
        samples_per_stream=left.size,
        changed_samples=int(changed_samples.size),
        first_changed_sample=int(changed_samples[0]) if changed_samples.size else None,
        last_changed_sample=int(changed_samples[-1]) if changed_samples.size else None,
        first_changed_pcm_frame=int(changed_samples[0] // left.shape[1]) if changed_samples.size else None,
        changed_pcm_frame_ranges=runs(changed_frames),
        common_suffix_first_slot=tail,
        common_suffix_words=len(different_words) - tail,
        differing_pcm_frames_in_common_suffix=int(changed_frames[tail:].sum()),
        reset_suffix_pcm_equal=True,
        reset_suffix_pcm_sha256=sha256(cold_a.tobytes()).hexdigest(),
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    build = ROOT / "work/evs_gcc_independent"
    parser.add_argument("--encoder", type=Path, default=build / "EVS_cod")
    parser.add_argument("--decoder", type=Path, default=build / "EVS_dec")
    args = parser.parse_args()
    encoder, decoder = args.encoder.resolve(), args.decoder.resolve()
    reference = (SENDER / "sender-pairs.json").read_bytes()
    published = json.loads(reference)
    source = sender_pairs.synthetic_source()
    if sha256(source.tobytes()).hexdigest() != published["synthetic_source_sha256"]:
        raise ValueError("waveform differs from the published source")
    result = dict(sender_receipt_sha256=sha256(reference).hexdigest(), frame_count=sender_pairs.FRAMES,
                  decoder_options=["-q", "-no_delay_cmp"], cases={})
    with tempfile.TemporaryDirectory() as td:
        for name in ("p24", "p27"):
            directory = Path(td) / name
            directory.mkdir()
            fixture = published[name]
            streams, different = encode_originals(encoder, source, fixture, directory)
            result["cases"][name] = dict(
                target_wire_bit=fixture["differing_physical_bit_msb_first"],
                changed_encoded_slots=np.flatnonzero(different).tolist(),
                decoder_by_khz={str(rate): measure(decoder, streams, different, rate) for rate in (16, 32)},
            )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
