"""Convert IQ to PCM16 WAV for Dream (48 kHz) or the Kiwi IQ pipeline (12 kHz).

Raw .cs8 is signed int8 I,Q in that order. Its rate is in complex samples/s.
"""
import argparse
from math import ceil, gcd, isfinite
from pathlib import Path
import tempfile

import numpy as np
from scipy.signal import resample_poly
import soundfile as sf


def cs8_frames(source):
    size = source.stat().st_size
    if not size or size % 2:
        raise ValueError('CS8 must contain complete signed I,Q pairs')
    return size // 2


def convert_cs8(source, output, rate, target, offset, start_sample=0, sample_count=None):
    available = cs8_frames(source)
    if sample_count is None:
        sample_count = available - start_sample
    if start_sample < 0 or not 0 < sample_count <= available - start_sample:
        raise ValueError('CS8 window is outside the input')
    if rate <= 0 or not isfinite(offset) or abs(offset) + 5000 > rate / 2:
        raise ValueError('the 10 kHz channel must fit inside the input sample rate')
    samples = np.memmap(source, mode='r', dtype=np.int8, offset=2*start_sample,
                        shape=(sample_count, 2))
    common = gcd(rate, target)
    up, down = target // common, rate // common
    block = max(1, 262144 // down) * down
    # scipy's default polyphase FIR spans 10*max(up,down) upsampled
    # samples on either side. Align every context window to the global grid.
    guard = ceil((10 * max(up, down) + down) / (up * down)) * down
    n = len(samples)
    n_out = (n * up + down - 1) // down
    with sf.SoundFile(output, 'w', samplerate=target, channels=2, subtype='PCM_16',
                      format='RF64' if 4 * n_out >= 0xffffffff - 64 else 'WAV') as wav:
        for start in range(0, n, block):
            end = min(start + block, n)
            left, right = max(0, start - guard), min(n, end + guard)
            data = samples[left:right].astype(np.float32) / 128
            if offset:
                iq = data[:, 0] + 1j * data[:, 1]
                phase = -2 * np.pi * (offset / rate) * np.arange(start_sample + left, start_sample + right)
                iq *= np.exp(1j * phase)
                data = np.column_stack((iq.real, iq.imag))
            filtered = resample_poly(data, up, down, axis=0)
            first = (start - left) * up // down
            count = ((end - start) * up + down - 1) // down
            wav.write(filtered[first:first + count])
    return n_out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--sample-rate', type=int, help='raw CS8 complex samples per second')
    parser.add_argument('--offset-hz', type=float, default=0.,
                        help='CS8 channel center minus recording center, in Hz')
    parser.add_argument('--target-rate', type=int, choices=(12000, 48000), default=48000)
    args = parser.parse_args()
    try:
        if args.input.suffix.lower() == '.cs8':
            if args.sample_rate is None:
                parser.error('raw CS8 requires --sample-rate (for 0.912 Msps use 912000)')
            if args.input.resolve() == args.output.resolve():
                parser.error('CS8 input and WAV output must have different paths')
            rate = args.sample_rate
            # Publish only complete WAVs, including when replacing an earlier output.
            with tempfile.TemporaryDirectory(dir=args.output.parent) as directory:
                wav = Path(directory) / 'iq.wav'
                count = convert_cs8(args.input, wav, rate, args.target_rate, args.offset_hz)
                wav.replace(args.output)
        else:
            if args.sample_rate is not None or args.offset_hz:
                parser.error('--sample-rate and --offset-hz apply to raw CS8')
            data, rate = sf.read(args.input, always_2d=True)
            common = gcd(rate, args.target_rate)
            result = resample_poly(data, args.target_rate // common, rate // common, axis=0)
            sf.write(args.output, result, args.target_rate, subtype='PCM_16')
            count = len(result)
    except (OSError, ValueError, sf.LibsndfileError) as exc:
        parser.exit(1, f'{parser.prog}: {exc}\n')
    print(f'{rate} Hz -> {args.target_rate} Hz, {count} samples, wrote {args.output}')


if __name__ == '__main__':
    main()
