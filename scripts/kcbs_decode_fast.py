"""Fast decode for captures with the March-style idle tail.

The March phase-0 tail plaintext is sixteen 0xFF bytes, so the keystream falls out
directly: ks[0..15] = tail XOR 0xFF, and the known text payload plus its CRC-16
confirm it per group. There is nothing to search, so this path skips fill-crib
scanning, repeated-text matching and per-group decoding.

Speed measures: existing MSC dumps are reused when present (no re-demodulation),
keys come from one vectorised pass, and the codec runs once per stretch of
usable groups instead of once per group.

The mask is known for all role-0 bytes and five of eleven role-1 bytes. The six
unknown role-1 bytes are substitutes. Roles 2/3 are erased by default, or replay
nearby supplied frames with --replay-nearby. The codec and audio are unverified.

Several captures of the same broadcast may be passed at once. Sequential recordings
extend the decoded span and simultaneous ones fill each other's gaps, because groups
merge by their 32-bit counter.

Usage:
  python scripts/kcbs_decode_fast.py <iq.wav> [more.wav ...] --out <dir>
"""
import argparse
import glob
import json
from pathlib import Path
import subprocess
import tempfile
import time
import wave

import numpy as np
from build_evs_gcc_independent import linux_command

from tail_fill_audit import audit, idle_prefixes
import render_continuous as rc

ROOT = Path(__file__).resolve().parents[1]

def find_dumps(source):
    """Existing dumps for this capture, so demodulation is not repeated."""
    stem = Path(source).stem.replace('_iq', '')
    found = sorted(glob.glob(str(ROOT/'dumps'/(stem + '*.msc.bin'))))
    found += sorted(glob.glob(str(ROOT/'work/drmradio/_chunks'/(stem + '__c*')/'msc.bin')))
    found += sorted(glob.glob(str(ROOT/'DRM Radio'/(stem + '*.msc.bin'))))
    return [Path(f) for f in found if Path(f).stat().st_size > 0]


def idle_keys(groups_npz):
    """Vectorised keystream recovery from the phase-0 idle tail."""
    with np.load(groups_npz) as d:
        tails = d['tails']
        counters = d['counters'].astype(np.int64)
        du = d['du']
    keys, ok = idle_prefixes(tails)
    return counters[ok], keys[ok], du[ok], int(ok.sum()), len(counters)



def assemble_frames(du, keys, offsets, span):
    frames = np.zeros((span*60, 33), np.uint8)
    supplied = np.zeros(span*60, bool)
    rows0 = np.arange(0, 60, 4)
    rows1 = rows0 + 1
    for off, row_du, key in zip(offsets, du, keys):
        base = int(off)*60
        modes, payload = rc.group_frames(row_du, key)
        rc.fill_p2_for_playback(payload)
        frames[base:base+60, 0] = modes
        frames[base:base+60, 1:] = payload
        supplied[base + rows0] = supplied[base + rows1] = True
    return frames, supplied


def group_runs(offsets, merge_gap):
    """Half-open stretches of sorted, nonempty offsets, bridging up to merge_gap holes."""
    breaks = np.flatnonzero(np.diff(offsets) - 1 > merge_gap)
    return [(int(offsets[lo]), int(offsets[hi]) + 1)
            for lo, hi in zip(np.r_[0, breaks+1], np.r_[breaks, len(offsets)-1])]


def replay_nearby(frames, supplied):
    """Fill loss slots only inside received four-frame cycles; keep supplied bytes intact."""
    out, keep = frames.copy(), supplied.copy()
    rows = np.arange(len(frames))
    active = np.repeat(supplied[::4], 4)
    for role, shift in ((2, -1), (3, 1), (3, -2)):
        targets = rows[active & (rows % 4 == role) & ~keep]
        targets = targets[(targets + shift >= 0) & (targets + shift < len(frames))]
        targets = targets[supplied[targets + shift]]
        out[targets] = frames[targets + shift]
        keep[targets] = True
    return out, keep


def attenuate(pcm, db):
    if not db:
        return pcm
    gain = np.float32(10**(-db/20))
    return np.rint(pcm.astype(np.float32)*gain).astype('<i2')


def decode_evs(part, keep, rate, temporary):
    stream, raw = temporary/'stream.192', temporary/'stream.raw'
    with stream.open('wb') as f:
        for bits, good in zip(np.unpackbits(part, axis=1), keep):
            if good:
                f.write(np.array([0x6b21, 264], '<u2').tobytes())
                f.write(np.where(bits, 0x81, 0x7f).astype('<u2').tobytes())
            else:
                f.write(np.array([0x6b20, 0], '<u2').tobytes())
    command = linux_command(ROOT/'work/evs_gcc_independent/EVS_dec',
                            '-q', '-no_delay_cmp', rate//1000, stream, raw)
    proc = subprocess.run(command, capture_output=True, timeout=7200)
    if proc.returncode:
        raise SystemExit(proc.stderr.decode(errors='replace')[-2000:])
    expected_bytes = 2*len(part)*(rate//50)
    if not raw.is_file() or raw.stat().st_size != expected_bytes:
        raise SystemExit(f'EVS decoder did not write the expected {expected_bytes} PCM bytes')
    got = np.fromfile(raw, '<i2')
    raw.unlink()
    return got

def render_timeline(frames, supplied, runs, rate, decode):
    per_frame = rate//50
    pcm = np.zeros(len(frames)*per_frame, dtype='<i2')
    ramp = np.linspace(0, 1, per_frame)
    for r, (lo, hi) in enumerate(runs):
        start, stop = lo*60, hi*60
        part = pcm[start*per_frame:stop*per_frame]
        part[:] = decode(frames[start:stop], supplied[start:stop])
        if r:
            part[:per_frame] = np.rint(part[:per_frame]*ramp)
        if r+1 < len(runs):
            part[-per_frame:] = np.rint(part[-per_frame:]*ramp[::-1])
    return pcm


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('source', nargs='+',
                    help='one or more captures; sequential or simultaneous recordings of '
                         'the same broadcast merge by counter and raise coverage')
    ap.add_argument('--out', required=True, help='new directory for the result and audit')
    ap.add_argument('--rate', type=int, default=32000, choices=(16000, 32000, 48000))
    ap.add_argument('--fresh', action='store_true', help='ignore cached dumps')
    ap.add_argument('--merge-gap', type=int, default=4,
                    help='bridge at most N missing groups with decoder concealment; '
                         'silence longer gaps (default: 4; 0 silences every gap)')
    ap.add_argument('--replay-nearby', action='store_true',
                    help='replay neighbouring supplied frames instead of concealing roles 2/3')
    ap.add_argument('--attenuate-db', type=float, default=0,
                    help='lower the final PCM level without compression or limiting')
    a = ap.parse_args()
    if not 0 <= a.attenuate_db <= 60:
        ap.error('--attenuate-db must be between 0 and 60')
    if a.merge_gap < 0:
        ap.error('--merge-gap must be nonnegative')
    out = (ROOT/a.out).resolve()
    out.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    timings = {}

    dumps, need_demod = [], []
    for src in a.source:
        found = [] if a.fresh else find_dumps(src)
        if found:
            dumps += found
        else:
            need_demod.append(Path(src).resolve())
    if dumps:
        print('reusing %d cached dump(s)' % len(dumps), flush=True)
    if need_demod:
        from kcbs_decode_audio import stage_demod
        log = []
        dumps += stage_demod(need_demod, out, 0, 0, log)
    timings['dumps_seconds'] = round(time.monotonic() - started, 1)

    if not dumps:
        raise SystemExit('no dumps available')
    groups_npz = out/'salvage'/'groups.npz'
    stage = time.monotonic()
    audit([str(p) for p in dumps], out/'salvage')
    counters, keys, du, verified, total = idle_keys(groups_npz)
    timings['audit_and_keys_seconds'] = round(time.monotonic() - stage, 1)
    print('idle keys: %d of %d groups pass the known text + CRC (%d verified)'
          % (verified, total, verified), flush=True)
    if not verified:
        raise SystemExit('no idle-key groups; this capture is not March-style')

    # Contiguous stream over the keyed span; unkeyed groups stay erased.
    first, last = int(counters[0]), int(counters[-1])
    span = last - first + 1
    offsets = counters - first
    stage = time.monotonic()
    frames, supplied = assemble_frames(du, keys, offsets, span)
    supplied_frames = int(supplied.sum())
    if a.replay_nearby:
        frames, supplied = replay_nearby(frames, supplied)
    replayed_frames = int(supplied.sum()) - supplied_frames
    runs = group_runs(offsets, a.merge_gap)
    timings['frames_seconds'] = round(time.monotonic() - stage, 1)

    stage = time.monotonic()
    with tempfile.TemporaryDirectory(prefix='evs_', dir=out) as tmp:
        temporary = Path(tmp)
        pcm = render_timeline(frames, supplied, runs, a.rate,
                              lambda f, s: decode_evs(f, s, a.rate, temporary))
    timings['decode_seconds'] = round(time.monotonic() - stage, 1)
    pcm = attenuate(pcm, a.attenuate_db)
    tag = ('_REPLAY' if a.replay_nearby else '') + ('_QUIETER' if a.attenuate_db else '')
    path = out/f'KCBS2_MARCH_UNVERIFIED{tag}_{a.rate//1000}k_{first}-{last}.wav'
    with wave.open(str(path), 'wb') as w:
        w.setparams((1, 2, a.rate, 0, 'NONE', 'not compressed'))
        w.writeframes(pcm.tobytes())

    silenced = [dict(start_seconds=round(hi*1.2, 2), duration_seconds=round((lo-hi)*1.2, 2))
                for (_, hi), (lo, _) in zip(runs, runs[1:])]
    peak = max(int(pcm.max()), -int(pcm.min()))
    clipped = int(np.count_nonzero((pcm == -32768) | (pcm == 32767)))
    norm = pcm.astype(np.float32) / 32768
    report = dict(source=list(a.source), dumps=len(dumps), file=path.name,
                  seconds=round(len(pcm)/a.rate, 2), pcm_samples=len(pcm),
                  keyed_groups=verified, groups_in_span=span,
                  coverage=round(verified/span, 3), supplied_frames=supplied_frames,
                  replayed_frames=replayed_frames, attenuation_db=a.attenuate_db,
                  fully_unmasked_frames=verified*15, total_frames=len(frames),
                  rms=round(float(np.sqrt(np.mean(norm**2))), 4), peak_pcm=peak,
                  full_scale_samples=clipped, clipped_fraction=clipped/len(pcm),
                  merge_gap=a.merge_gap, decoder_calls=len(runs), silenced_gaps=silenced,
                  timings=timings, wall_seconds=round(time.monotonic() - started, 1),
                  note='The idle text and CRC support the 16-byte mask prefix, not codec identity '
                       'or an audio match. Role 1 has six role-0 donor bytes; replayed frames are copies.')
    (out/'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2), flush=True)


if __name__ == '__main__':
    main()
