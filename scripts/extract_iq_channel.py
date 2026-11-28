"""Extract a centered 12 kHz complex baseband channel from a stereo I,Q WAV."""

import argparse
from datetime import datetime, timezone
from math import ceil, gcd, isfinite
import json
import os
from pathlib import Path
import tempfile

import numpy as np
from scipy.signal import firwin, kaiserord, upfirdn
import soundfile as sf


OUTPUT_RATE = 12_000
PASSBAND_HZ = 5_050
STOPBAND_HZ = 5_950
ATTENUATION_DB = 85
BLOCK_FRAMES = 262_144


def channel_filter(rate, up, down):
    """Make the linear-phase FIR delay a whole number of output samples."""
    design_rate = rate * up
    transition = (STOPBAND_HZ - PASSBAND_HZ) / (design_rate / 2)
    size, beta = kaiserord(ATTENUATION_DB, transition)
    delay = ceil((size - 1) / (2 * down)) * down
    kernel = firwin(2 * delay + 1, (PASSBAND_HZ + STOPBAND_HZ) / 2,
                    fs=design_rate, window=('kaiser', beta))
    return up * kernel, delay


def extract(source, output, offset_hz, *, source_start_utc=None):
    source, output = Path(source), Path(output)
    if os.path.lexists(output):
        raise FileExistsError(f'output already exists: {output}')
    if not isfinite(offset_hz):
        raise ValueError('channel offset must be finite')
    if source_start_utc is not None:
        start = datetime.fromisoformat(source_start_utc)
        if start.utcoffset() != timezone.utc.utcoffset(None):
            raise ValueError('source start time must include an explicit UTC offset of zero')
    before = source.stat()
    with sf.SoundFile(source) as src:
        if src.format not in ('WAV', 'WAVEX', 'RF64') or src.channels != 2:
            raise ValueError('expected a stereo WAV with I on the left and Q on the right')
        if src.subtype not in ('PCM_U8', 'PCM_16', 'PCM_24', 'PCM_32', 'FLOAT', 'DOUBLE'):
            raise ValueError(f'expected uncompressed PCM or floating-point IQ, found {src.subtype}')
        rate, total = src.samplerate, len(src)
        if not total or abs(offset_hz) + STOPBAND_HZ > rate / 2:
            raise ValueError('input must be nonempty and the entire ±5950 Hz channel filter must fit in its Nyquist band')

        divisor = gcd(rate, OUTPUT_RATE)
        up, down = OUTPUT_RATE // divisor, rate // divisor
        kernel, delay = channel_filter(rate, up, down)
        block = max(1, BLOCK_FRAMES // down) * down
        # Every read starts on the same rational time grid. Include the full FIR
        # support on both ends; only the physical file edges use zero extension.
        guard = ceil(delay / (up * down)) * down
        count = (total * up + down - 1) // down
        # Evaluating absolute phase with integer residues avoids drift on long captures.
        numerator, denominator = float(offset_hz).as_integer_ratio()
        period = denominator * rate
        wav_format = 'RF64' if 8 * count >= 0xffffffff - 128 else 'WAV'

        with tempfile.TemporaryDirectory(dir=output.parent) as directory:
            staged = Path(directory) / 'channel.wav'
            with sf.SoundFile(staged, mode='w', format=wav_format, subtype='FLOAT',
                              channels=2, samplerate=OUTPUT_RATE) as dst:
                for first in range(0, total, block):
                    end = min(total, first + block)
                    left, right = max(0, first - guard), min(total, end + guard)
                    src.seek(left)
                    data = src.read(right - left, dtype='float64', always_2d=True)
                    if len(data) != right - left or not np.isfinite(data).all():
                        raise ValueError('short read or non-finite sample in source IQ')
                    iq = data[:, 0] + 1j * data[:, 1]
                    if offset_hz:
                        phase0 = ((left * numerator) % period) / period
                        turns = phase0 + np.arange(len(iq)) * (offset_hz / rate)
                        iq *= np.exp(-2j * np.pi * turns)
                    filtered = upfirdn(kernel, iq, up=up, down=down)
                    first_output = ((first - left) * up + delay) // down
                    n = ((end - first) * up + down - 1) // down
                    samples = filtered[first_output:first_output + n]
                    if len(samples) != n:
                        raise ValueError('incomplete filter output')
                    pairs = np.column_stack((samples.real, samples.imag))
                    if not np.isfinite(pairs).all() or np.abs(pairs).max() > np.finfo(np.float32).max:
                        raise ValueError('filtered samples exceed the float32 WAV range')
                    dst.write(pairs)
                if dst.tell() != count:
                    raise ValueError('incorrect output duration')

            after = source.stat()
            if (before.st_size, before.st_mtime_ns, before.st_dev, before.st_ino) != (
                    after.st_size, after.st_mtime_ns, after.st_dev, after.st_ino):
                raise ValueError('source changed during extraction')
            # Publish a finished, closed WAV. An existing or concurrently created
            # destination makes link() fail without modifying that destination.
            os.link(staged, output)

        return dict(source=str(source), output=str(output), offset_hz=offset_hz,
                    offset_convention='selected channel frequency minus source center frequency',
                    channels=['I', 'Q'], source_format=src.format, source_subtype=src.subtype,
                    source_sample_rate_hz=rate, source_frames=total, source_sample_range=[0, total],
                    source_start_utc=source_start_utc, output_sample_zero_source_frame=0,
                    output_start_utc=source_start_utc, output_sample_rate_hz=OUTPUT_RATE,
                    output_frames=count, output_format=wav_format, output_subtype='FLOAT',
                    source_frames_per_output_frame=dict(numerator=down, denominator=up),
                    source_duration_seconds=total / rate, output_duration_seconds=count / OUTPUT_RATE,
                    fir_passband_hz=PASSBAND_HZ, fir_stopband_hz=STOPBAND_HZ,
                    kaiser_design_attenuation_db=ATTENUATION_DB, fir_taps=len(kernel),
                    fir_design_rate_hz=rate * up, compensated_delay_output_frames=delay // down,
                    boundary='Zero extension only at file ends. Output frame k is centered at source time k/12000 seconds.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path, help='uncompressed stereo WAV, left I and right Q')
    parser.add_argument('output', type=Path, help='new stereo float32 WAV (RF64 for large outputs)')
    parser.add_argument('--offset-hz', required=True, type=float,
                        help='requested RF channel minus recording center in hertz; may be negative')
    parser.add_argument('--source-start-utc', help='optional UTC timestamp of the first IQ pair, e.g. 2026-11-28T00:42:00Z')
    args = parser.parse_args()
    try:
        receipt = extract(args.source, args.output, args.offset_hz, source_start_utc=args.source_start_utc)
    except (ValueError, OSError, sf.LibsndfileError) as exc:
        parser.exit(1, f'{parser.prog}: {exc}\n')
    print(json.dumps(receipt, indent=2))


if __name__ == '__main__':
    main()
