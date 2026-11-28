"""Render one capture as a single continuous decode.

Motivation: decoding many 1.2 s islands leaves the codec starting cold every time,
which sounds far worse than a continuous stream. Three tiers of evidence are mixed
in one pass and recorded per group so the output cannot be mistaken for a full decode:

  A keyed       - role 0 and the first five keyed bytes of role 1 use the supplied
                  candidate. For playback, the other six role-1 bytes are copied
                  from the preceding role-0 frame. Roles 2 and 3 are erased.
  B unkeyed     - no key at all: the 21 unencrypted bytes per frame are real, all
                  eleven keyed bytes are filled from a nearby keyed group
  (groups absent from the capture are genuine gaps and are erased)

Usage: python scripts/render_continuous.py <salvage dir> <keys.npz> --out <dir> [--rate 32000]
"""
import argparse
import json
from pathlib import Path
import subprocess
import wave

import numpy as np
from build_evs_gcc_independent import linux

PACKET_STARTS = [(7 if r == 0 else 40 if r == 1 else 73 if r == 2 else 106) + 131*c
                 for c in range(5) for r in range(4)]
MODE_POSITIONS = [(2 + c) if r == 0 else
                  ((39 if r == 1 else 72 if r == 2 else 105) + 131*c)
                  for c in range(5) for r in range(4)]
KEYED = np.arange(0, 32, 3)


def group_frames(du_row, key):
    """33-byte frames for one group; role 0 and 5 role-1 keyed bytes decrypted."""
    flat = np.zeros((60, 32), np.uint8)
    modes = np.zeros(60, np.uint8)
    for phase in range(3):
        for j, (begin, mode_byte) in enumerate(zip(PACKET_STARTS, MODE_POSITIONS)):
            flat[phase*20 + j] = du_row[phase, begin:begin+32]
            modes[phase*20 + j] = du_row[phase, mode_byte]
    if key is not None:
        slot = np.arange(60) % 4
        flat[np.ix_(np.flatnonzero(slot == 0), KEYED)] ^= key[:11]
        flat[np.ix_(np.flatnonzero(slot == 1), KEYED[:5])] ^= key[11:16]
    return modes, flat


def fill_p2_for_playback(payload):
    """Copy six substitute octets from each preceding P1 into a P2 payload."""
    unknown = KEYED[5:]
    payload[1::4, unknown] = payload[0::4, unknown]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('salvage')
    ap.add_argument('keys')
    ap.add_argument('--out', required=True)
    ap.add_argument('--rate', type=int, default=32000)
    ap.add_argument('--chunk', type=int, default=0,
                    help='decode in chunks of N groups to limit decoder state drift; 0 = one stream')
    ap.add_argument('--merge-gap', type=int, default=0,
                    help='bridge up to N unkeyed groups inside one decoder call (PLC), '
                         'and silence the rest; 0 = one stream over everything')
    ap.add_argument('--no-fill', action='store_true',
                    help='do not supply unkeyed groups; erase them instead')
    a = ap.parse_args()
    root = Path(__file__).resolve().parents[1]
    salvage = (root/a.salvage).resolve()
    out = (root/a.out).resolve()
    out.mkdir(parents=True, exist_ok=True)

    with np.load(salvage/'groups.npz') as d:
        counters = d['counters'].astype(np.int64)
        du = d['du'].copy()
    with np.load(root/a.keys) as d:
        usable = d['candidate_mask'].all(axis=1)
        keys = {int(c): k.copy() for c, k in zip(d['counters'][usable], d['ks'][usable])}
    idx = {int(c): i for i, c in enumerate(counters)}
    first, last = int(counters[0]), int(counters[-1])
    print('groups %d, keyed %d, span %d..%d (%d counters)'
          % (len(counters), len(keys), first, last, last-first+1), flush=True)

    keyed_sorted = sorted(keys)
    plains = {g: group_frames(du[idx[g]], keys[g]) for g in keyed_sorted}

    frames = np.zeros(((last-first+1)*60, 33), np.uint8)
    supplied = np.zeros(len(frames), bool)
    supplied0 = supplied
    tier = np.zeros(last-first+1, np.uint8)
    for g in range(first, last+1):
        base = (g-first)*60
        if g not in idx:
            tier[g-first] = 0            # not received: leave erased
            continue
        if g in keys:
            modes, original = plains[g]
            flat = original.copy()  # Other groups can still use the original donor.
            fill_p2_for_playback(flat)
            tier[g-first] = 1
            supplied[base:base+60] = np.arange(60) % 4 < 2
        elif a.no_fill:
            tier[g-first] = 0
            continue
        else:
            # Tier B: the 21 unencrypted bytes are real; all eleven keyed bytes come
            # from the nearest keyed group.
            donor = min(keyed_sorted, key=lambda x: (abs(x - g), x))
            dflat = plains[donor][1]
            modes, flat = group_frames(du[idx[g]], None)
            flat[:, KEYED] = dflat[:, KEYED]
            tier[g-first] = 2
            supplied[base:base+60] = True
        frames[base:base+60, 0] = modes
        frames[base:base+60, 1:] = flat

    def decode_slice(lo, hi):
        part, keep = frames[lo:hi], supplied[lo:hi]
        stream = out/('slice_%06d.192' % lo)
        raw = out/('slice_%06d.raw' % lo)
        with stream.open('wb') as f:
            for bits, good in zip(np.unpackbits(part, axis=1), keep):
                if good:
                    f.write(np.array([0x6b21, 264], '<u2').tobytes())
                    f.write(np.where(bits, 0x81, 0x7f).astype('<u2').tobytes())
                else:
                    f.write(np.array([0x6b20, 0], '<u2').tobytes())
        command = ['wsl', '-d', 'Ubuntu', '--', linux(root/'work/evs_gcc_independent/EVS_dec'),
                   '-q', '-no_delay_cmp', str(a.rate//1000), linux(stream), linux(raw)]
        p = subprocess.run(command, capture_output=True, timeout=3600)
        if p.returncode:
            raise SystemExit(p.stderr.decode(errors='replace')[-2000:])
        pcm = np.fromfile(raw, '<i2')
        stream.unlink(); raw.unlink()
        return pcm

    if a.merge_gap:
        # Decode each stretch of keyed groups that are within merge_gap of each other
        # in one call, so the decoder warms up and bridges the short holes, then keep
        # silence outside the stretches. This avoids both cold starts every 1.2 s and
        # concealment babble in the long empty regions.
        span = last - first + 1
        keyed_offsets = sorted(g - first for g in keys)
        # Stretch boundaries: start a new one when the hole exceeds merge_gap. The
        # first offset seeds the first stretch, so a lone leading group is handled.
        bounds, start, previous = [], keyed_offsets[0], keyed_offsets[0]
        for offset in keyed_offsets[1:]:
            if offset - previous > a.merge_gap:
                bounds.append((start, previous))
                start = offset
            previous = offset
        bounds.append((start, previous))
        canvas = np.zeros(span*60*(a.rate//50), np.int16)
        for lo_group, hi_group in bounds:
            lo = lo_group*60
            hi = (hi_group + 1)*60
            canvas[lo*(a.rate//50):hi*(a.rate//50)] = decode_slice(lo, hi)
        pcm = canvas
        n_slices = len(bounds)
    else:
        step = a.chunk*60 if a.chunk else len(frames)
        pieces = [decode_slice(s0, min(s0 + step, len(frames)))
                  for s0 in range(0, len(frames), step)]
        pcm = np.concatenate(pieces)
        n_slices = len(pieces)
    tag = ('nofill' if a.no_fill else 'filled')
    tag += '_merge%d' % a.merge_gap if a.merge_gap else ('_chunk%d' % a.chunk if a.chunk else '')
    path = out/('KCBS2_%s_KEYS_%s_%dk_%d-%d.wav'
                % ('HANGUL' if keys else 'NONE', tag, a.rate//1000, first, last))
    with wave.open(str(path), 'wb') as w:
        w.setparams((1, 2, a.rate, 0, 'NONE', 'not compressed'))
        w.writeframes(pcm.tobytes())
    report = dict(file=path.name, seconds=round(len(pcm)/a.rate, 2), chunk_groups=a.chunk,
                  fill_unkeyed=not a.no_fill,
                  counters=last-first+1,
                  tier_keyed=int((tier == 1).sum()),
                  tier_unkeyed_filled=int((tier == 2).sum()),
                  tier_missing=int((tier == 0).sum()),
                  supplied_frames=int(supplied.sum()), total_frames=int(len(frames)),
                  decoder_calls=n_slices, clipped_fraction=round(float(np.mean(np.abs(pcm) >= 32767)), 5),
                  rms=round(float(np.sqrt(np.mean((pcm.astype(float)/32768)**2))), 4),
                  note='Tier 1 uses the supplied candidate for P1 and five P2 octets. '
                       'Six P2 octets per frame are playback substitutes copied from P1. '
                       'Tier 2 takes eleven payload octets from a donor for playback.')
    (out/'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2), flush=True)


if __name__ == '__main__':
    main()
