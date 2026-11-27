"""Interpolate impulsive 48 kHz stereo PCM16 IQ samples for the fixed RF validation control."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import wave

import numpy as np
from scipy import ndimage, signal


RATE = 48_000
BLOCK = 4_800
CHUNK = BLOCK * 32
SHIFT = 24_001
FRAME_BYTES = 4


def file_digest(path):
    digest = sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def read_frames(source, count):
    data = source.readframes(count)
    if len(data) != count * FRAME_BYTES:
        raise ValueError("Truncated PCM16 IQ samples in input WAV")
    return data


def detect(source):
    """Use globally aligned 0.1 s medians and actual neighbouring samples for each FIR window."""
    frames = source.getnframes()
    flagged = np.zeros(frames, dtype=bool)
    taps = signal.firwin(65, 7000, fs=RATE).astype("f4")
    radius = len(taps) // 2
    for start in range(0, frames, CHUNK):
        stop = min(start + CHUNK, frames)
        left, right = max(0, start - radius), min(frames, stop + radius)
        source.setpos(left)
        pcm = np.frombuffer(read_frames(source, right - left), dtype="<i2").reshape(-1, 2)
        iq = (pcm[:, 0].astype("f4") + 1j * pcm[:, 1].astype("f4")) / 32768
        filtered = signal.fftconvolve(iq, taps, mode="same")
        magnitude = np.abs((iq - filtered)[start - left:stop - left])
        for offset in range(0, len(magnitude), BLOCK):
            window = magnitude[offset:offset + BLOCK]
            rms = np.sqrt(np.median(window ** 2) / np.log(2))
            flagged[start + offset:start + offset + len(window)] = window > 8 * rms
    # Protect source endpoints before dilation, as in the original control.
    flagged[:50] = False
    flagged[-50:] = False
    count = int(flagged.sum())
    if count:
        return ndimage.binary_dilation(flagged, structure=np.ones(5, dtype=bool)), count
    return flagged, 0


def runs(mask):
    """Yield half-open runs, allowing a run to cross any processing chunk boundary."""
    start = None
    for offset in range(0, len(mask), CHUNK):
        window = mask[offset:offset + CHUNK]
        edges = np.flatnonzero(np.diff(window, prepend=start is not None))
        for edge in edges:
            index = offset + int(edge)
            if start is None:
                start = index
            else:
                yield start, index
                start = None
    if start is not None:
        raise ValueError("Interpolation needs an unmarked final sample")


def write_treatment(source, writer, mask):
    frames = source.getnframes()
    writer.setparams((2, 2, RATE, frames, "NONE", "not compressed"))
    original, treated = sha256(), sha256()
    changed = run_count = max_delta = 0
    component_counts = np.zeros(2, dtype=np.int64)
    source.rewind()

    def write(original_bytes, result_bytes):
        original.update(original_bytes)
        treated.update(result_bytes)
        writer.writeframesraw(result_bytes)

    def copy_to(stop):
        while source.tell() < stop:
            data = read_frames(source, min(CHUNK, stop - source.tell()))
            write(data, data)

    for start, stop in runs(mask):
        copy_to(start)
        source.setpos(start - 1)
        left = np.frombuffer(read_frames(source, 1), dtype="<i2").astype("f8")
        source.setpos(stop)
        right = np.frombuffer(read_frames(source, 1), dtype="<i2").astype("f8")
        source.setpos(start)
        # Same interior points and nearest-even rounding as linspace(left, right, run_length+2).
        step = (right - left) / (stop - start + 1)
        run_count += 1
        for pos in range(start, stop, CHUNK):
            size = min(CHUNK, stop - pos)
            raw = read_frames(source, size)
            before = np.frombuffer(raw, dtype="<i2").reshape(-1, 2)
            distance = np.arange(pos - start + 1, pos - start + 1 + size, dtype="f8")
            after = np.rint(left + distance[:, None] * step).astype("<i2")
            delta = after.astype("i4") - before
            changed += int(np.any(delta, axis=1).sum())
            component_counts += np.count_nonzero(delta, axis=0)
            max_delta = max(max_delta, int(np.abs(delta).max()))
            write(raw, after.tobytes())
    copy_to(frames)
    return dict(input_pcm_sha256=original.hexdigest(), output_pcm_sha256=treated.hexdigest(),
                changed_iq_samples=changed, changed_components_i_q=component_counts.tolist(),
                largest_component_change_pcm16=max_delta, affected_contiguous_runs=run_count)


def process(input_path, output_path, shifted_control):
    if output_path.exists():
        raise FileExistsError(f"Output already exists: {output_path}")
    with wave.open(str(input_path), "rb") as source:
        if (source.getnchannels(), source.getsampwidth(), source.getframerate(), source.getcomptype()) != (2, 2, RATE, "NONE"):
            raise ValueError("Input must be uncompressed 48 kHz stereo PCM16 IQ WAV")
        frames = source.getnframes()
        mask, triggered = detect(source)
        marked = int(mask.sum())
        if shifted_control and frames:
            mask = np.roll(mask, SHIFT)
            mask[0] = mask[-1] = False
        with output_path.open("xb") as output:
            try:
                with wave.open(output, "wb") as writer:
                    effect = write_treatment(source, writer, mask)
            except BaseException:
                output.close()
                output_path.unlink()
                raise
    return dict(treatment="shifted-control" if shifted_control else "impulse-interpolation",
                source_sha256=file_digest(input_path), derived_sha256=file_digest(output_path),
                total_iq_samples=frames, triggered_iq_samples=triggered, marks_before_shift=marked,
                marked_after_2_sample_dilation=int(mask.sum()), circular_shift_samples=SHIFT if shifted_control else 0,
                **effect)


def main():
    parser = argparse.ArgumentParser(description=__doc__,
        epilog="The final partial 4,800-sample block uses its own median. The detector processes "
               "the 65-tap FIR in chunks with 32 samples of context on each side. FFT roundoff can "
               "affect a sample at the detection threshold.")
    parser.add_argument("input", type=Path, help="source IQ WAV, I in the left channel and Q in the right")
    parser.add_argument("output", type=Path, help="new 48 kHz PCM16 IQ WAV")
    parser.add_argument("--shifted-control", action="store_true",
                        help="shift the expanded detection mask forward by 24,001 samples, wrapping at the end")
    args = parser.parse_args()
    try:
        result = process(args.input, args.output, args.shifted_control)
    except (OSError, ValueError, EOFError, wave.Error) as error:
        parser.exit(1, f"{parser.prog}: {error}\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
