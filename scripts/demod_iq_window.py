"""Demodulate one bounded IQ window, preserving source sample provenance.

Does not join dumps or infer record timestamps. Dream may loop its input; the
raw dump is preserved for counter-based assembly. A timeout is expected and is
recorded explicitly, not treated as proof of successful DRM reception.
"""
import argparse
import json
import math
import os
from pathlib import Path
import shlex
import subprocess
import time

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly, upfirdn

from build_evs_gcc_independent import linux, linux_command
from extract_iq_channel import BLOCK_FRAMES, PASSBAND_HZ, STOPBAND_HZ, channel_filter
from resample_iq import cs8_frames, convert_cs8


WSL_LEGACY_DREAM = '/root/kcbs/dream-src/dream'

# Dream channel estimators for repeatable passes over the same IQ.
RECEPTION_PROFILES = {
    'wiener': dict(freqint=2, timeint=1, modmetric=0),
    'linear-time': dict(freqint=2, timeint=0, modmetric=0),
    'linear-time-modmetric': dict(freqint=2, timeint=0, modmetric=1),
}


def dream_binary():
    override = os.environ.get('KCBS_DREAM')
    if override:
        if os.name == 'nt' and override.startswith('/'):
            return override  # Already a WSL path.
        return linux(Path(override))
    root = Path(__file__).resolve().parents[1]
    for binary in (root/'work/dream-build/dream', root/'build/dream-src/dream'):
        if binary.is_file():
            return linux(binary)
    return WSL_LEGACY_DREAM if os.name == 'nt' else linux(root/'build/dream-src/dream')


def input_info(src, sample_rate, real_if_hz=None):
    if src.suffix.lower() == '.cs8':
        if real_if_hz is not None:
            raise ValueError('--real-if-hz requires a mono PCM WAV')
        if sample_rate is None or sample_rate <= 0:
            raise ValueError('raw CS8 requires a positive --sample-rate (complex samples/s)')
        return sample_rate, cs8_frames(src)
    info = sf.info(src)
    if real_if_hz is not None:
        if (info.channels != 1 or info.format not in ('WAV', 'WAVEX', 'RF64') or
                info.subtype not in ('PCM_U8', 'PCM_16', 'PCM_24', 'PCM_32', 'FLOAT', 'DOUBLE')):
            raise ValueError('--real-if-hz requires a mono uncompressed PCM WAV')
        if not math.isfinite(real_if_hz) or not STOPBAND_HZ <= real_if_hz <= info.samplerate / 2 - STOPBAND_HZ:
            raise ValueError(f'IF center ±{STOPBAND_HZ} Hz must fit between DC and Nyquist')
        return info.samplerate, info.frames
    if info.channels == 1:
        raise ValueError('mono audio requires --real-if-hz and a recorded real IF channel')
    if info.channels != 2 or (abs(info.samplerate - 12000) > 3 and info.samplerate != 48000):
        raise ValueError(f'expected two-channel IQ at approximately 12 kHz or at 48 kHz: {src}')
    return info.samplerate, info.frames


def convert_real_if(src, output, center, start, count):
    """Extract the positive-frequency IF band onto Dream's 48 kHz complex grid."""
    target_rate = 48000
    with sf.SoundFile(src) as source, sf.SoundFile(output, mode='w', samplerate=target_rate,
                                                  channels=2, subtype='PCM_16') as dst:
        divisor = math.gcd(source.samplerate, target_rate)
        up, down = target_rate // divisor, source.samplerate // divisor
        taps, delay = channel_filter(source.samplerate, up, down)
        # Align overlapping reads to the output grid, using samples only inside the selected window.
        guard = math.ceil(delay / (up * down)) * down
        block = max(1, BLOCK_FRAMES // down) * down
        numerator, denominator = float(center).as_integer_ratio()
        period = denominator * source.samplerate
        clipped = 0
        for first in range(0, count, block):
            end = min(count, first + block)
            left, right = max(0, first - guard), min(count, end + guard)
            source.seek(start + left)
            x = source.read(right - left, dtype='float64')
            if len(x) != right - left or not np.isfinite(x).all():
                raise ValueError('short read or non-finite sample in real IF')
            phase0 = ((start + left) * numerator % period) / period
            turns = phase0 + np.arange(len(x)) * (center / source.samplerate)
            # A cosine of peak A at IF+f gives A*exp(+j2πft) after rejection of its image.
            mixed = 2 * x * np.exp(-2j * np.pi * turns)
            filtered = upfirdn(taps, mixed, up=up, down=down)
            skip = ((first - left) * up + delay) // down
            n = ((end - first) * up + down - 1) // down
            samples = filtered[skip:skip + n]
            pairs = np.column_stack((samples.real, samples.imag))
            if len(pairs) != n or not np.isfinite(pairs).all():
                raise ValueError('invalid filtered real IF samples')
            clipped += int(np.count_nonzero((pairs < -1) | (pairs > 32767/32768)))
            dst.write(pairs)
        frames = dst.tell()
        if frames != (count * up + down - 1) // down:
            raise ValueError('incorrect real IF output duration')
    return dict(center_hz=center, fir_passband_hz=PASSBAND_HZ, fir_stopband_hz=STOPBAND_HZ,
                compensated_delay_output_frames=delay // down, output_rate_hz=target_rate,
                output_frames=frames, output_frame_zero_source_frame=start, pcm16_out_of_range_components=clipped,
                amplitude='2x real mixer, peak-A input cosine gives complex amplitude A before PCM16 saturation')


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('input')
    ap.add_argument('outdir')
    ap.add_argument('--start', type=float, default=0)
    ap.add_argument('--seconds', type=float, default=240)
    ap.add_argument('--sample-rate', type=int, help='raw CS8 complex samples per second')
    ap.add_argument('--offset-hz', type=float, default=0., help='CS8 channel minus center, Hz')
    ap.add_argument('--real-if-hz', type=float, help='positive carrier frequency in a mono real IF WAV, Hz. '
                    'Extract ±5050 Hz to I/Q. A cosine of peak A produces complex amplitude A.')
    ap.add_argument('--mlc-iterations', type=int, choices=range(5),
                    help='Dream multi-level channel decoder iterations (0–4); omit to use its configuration')
    ap.add_argument('--reception-profile', choices=RECEPTION_PROFILES,
                    help='select a fixed Dream channel estimator for this pass')
    args = ap.parse_args()
    if args.start < 0 or not 0 < args.seconds <= 600:
        ap.error('start must be nonnegative; seconds must be in (0, 600]')
    src = Path(args.input).resolve()
    if src.suffix.lower() != '.cs8' and (args.offset_hz or args.sample_rate is not None):
        ap.error('--offset-hz and --sample-rate on this command require raw CS8. '
                 'Use extract_iq_channel.py to tune a channel from a stereo IQ WAV.')
    try:
        rate, frames = input_info(src, args.sample_rate, args.real_if_hz)
    except (OSError, ValueError) as error:
        ap.error(str(error))
    start = round(args.start * rate)
    if start >= frames:
        ap.error('window begins past end of input')
    count = min(round(args.seconds * rate), frames - start)
    if count == 0:
        ap.error('window contains zero source samples')
    out = Path(args.outdir).resolve()
    out.mkdir(parents=True, exist_ok=False)  # never reuse an incomplete cache
    meta = dict(source=str(src), source_bytes=src.stat().st_size,
                source_sample_rate=rate, source_frames=frames,
                start_sample=start, sample_count=count,
                start_seconds=start / rate,
                duration_seconds=count / rate,
                channel_offset_hz=args.offset_hz,
                timing_note='Nominal sample rate used; physical clock calibration unknown. '
                            'Dump record index is NOT a source timestamp.',
                status='running')
    manifest = out / 'manifest.json'
    if args.mlc_iterations is not None:
        meta['mlc_iterations'] = args.mlc_iterations
    if args.reception_profile is not None:
        settings = dict(RECEPTION_PROFILES[args.reception_profile],
                        mlciter=args.mlc_iterations if args.mlc_iterations is not None else 1)
        ini = '[Receiver]\n' + ''.join(f'{name}={value}\n' for name, value in settings.items())
        (out / 'Dream.ini').write_text(ini, encoding='ascii')
        meta.update(reception_profile=args.reception_profile, receiver_settings=settings)
    manifest.write_text(json.dumps(meta, indent=2), encoding='utf-8')
    wav = out / 'iq48.wav'
    try:
        if src.suffix.lower() == '.cs8':
            convert_cs8(src, wav, rate, 48000, args.offset_hz, start, count)
        elif args.real_if_hz is not None:
            meta['real_if'] = convert_real_if(src, wav, args.real_if_hz, start, count)
        else:
            with sf.SoundFile(src) as f:
                f.seek(start)
                x = f.read(count, dtype='float32', always_2d=True)
            g = math.gcd(rate, 48000)
            y = resample_poly(x, 48000 // g, rate // g, axis=0)
            sf.write(wav, y, 48000, subtype='PCM_16')
            del x, y
        dump = out / 'msc.bin'
        log = out / 'dream.log'
        seconds = math.ceil(meta['duration_seconds'] * 1.15 + 60)
        t0 = time.monotonic()
        binary = dream_binary()
        command = ['env', 'QT_QPA_PLATFORM=offscreen', 'KCBS_DUMP_MSC=' + linux(dump),
                   'DREAM_FILE_OFFLINE=1', 'timeout', str(seconds), binary,
                   '-c', '6', '--sigsrate', '48000', '-m', '1', '-f', linux(wav)]
        if args.mlc_iterations is not None:
            command.extend(['--mlciter', str(args.mlc_iterations)])
        if os.name == 'nt' and (binary == WSL_LEGACY_DREAM or args.reception_profile is not None):
            # The legacy build normally reads its settings from the build directory.
            config_dir = linux(out) if args.reception_profile is not None else '/root/kcbs/dream-src'
            command = linux_command('bash', '-lc', 'cd ' + shlex.quote(config_dir) + ' && ' +
                                    shlex.join(command))
        else:
            command = linux_command(*command)
        with log.open('wb') as output:
            proc = subprocess.run(command, stdout=output, stderr=subprocess.STDOUT,
                                  cwd=out, timeout=seconds + 60)
        meta.update(wall_seconds=time.monotonic() - t0, returncode=proc.returncode,
                    dump_bytes=dump.stat().st_size if dump.exists() else 0,
                    status='finished' if proc.returncode in (0, 124) else 'failed')
        if meta['status'] == 'finished' and not meta['dump_bytes']:
            meta['status'] = 'no_msc_output'
        # Keep the raw dump/log; remove only this run's resampled intermediate.
        wav.unlink()
    except Exception as exc:
        meta.update(status='failed', error=str(exc))
        raise
    finally:
        manifest.write_text(json.dumps(meta, indent=2), encoding='utf-8')
    print(json.dumps(meta, indent=2), flush=True)
    if meta['status'] == 'failed':
        raise SystemExit(1)


if __name__ == '__main__':
    main()
