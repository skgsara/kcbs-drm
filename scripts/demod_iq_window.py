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

import soundfile as sf
from scipy.signal import resample_poly

from build_evs_gcc_independent import linux, linux_command
from resample_iq import cs8_frames, convert_cs8


WSL_LEGACY_DREAM = '/root/kcbs/dream-src/dream'


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


def input_info(src, sample_rate):
    if src.suffix.lower() == '.cs8':
        if sample_rate is None or sample_rate <= 0:
            raise ValueError('raw CS8 requires a positive --sample-rate (complex samples/s)')
        return sample_rate, cs8_frames(src)
    info = sf.info(src)
    if info.channels != 2 or (abs(info.samplerate - 12000) > 3 and info.samplerate != 48000):
        raise ValueError(f'expected two-channel IQ at approximately 12 kHz or at 48 kHz: {src}')
    return info.samplerate, info.frames


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('input')
    ap.add_argument('outdir')
    ap.add_argument('--start', type=float, default=0)
    ap.add_argument('--seconds', type=float, default=240)
    ap.add_argument('--sample-rate', type=int, help='raw CS8 complex samples per second')
    ap.add_argument('--offset-hz', type=float, default=0., help='CS8 channel minus center, Hz')
    args = ap.parse_args()
    if args.start < 0 or not 0 < args.seconds <= 600:
        ap.error('start must be nonnegative; seconds must be in (0, 600]')
    src = Path(args.input).resolve()
    try:
        rate, frames = input_info(src, args.sample_rate)
    except (OSError, ValueError) as error:
        ap.error(str(error))
    start = round(args.start * rate)
    if start >= frames:
        ap.error('window begins past end of input')
    count = min(round(args.seconds * rate), frames - start)
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
    manifest.write_text(json.dumps(meta, indent=2), encoding='utf-8')
    wav = out / 'iq48.wav'
    try:
        if src.suffix.lower() == '.cs8':
            convert_cs8(src, wav, rate, 48000, args.offset_hz, start, count)
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
        if os.name == 'nt' and binary == WSL_LEGACY_DREAM:
            # Older WSL builds find their configuration relative to this directory.
            command = linux_command('bash', '-lc', 'cd /root/kcbs/dream-src && ' +
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
