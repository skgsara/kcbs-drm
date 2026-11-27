"""Raise decoded quality by using partially known frames instead of erasing them.

Knowledge per 4-frame cycle: role 0 fully known; role 1 known except 6 keyed bytes
(frame bytes 16, 19, 22, 25, 28, 31); roles 2 and 3 unknown at all 11 keyed bytes.

Strategies are judged on GENUINE reference speech encoded at 13.2 kbps, where the
true audio is known: the same byte mask is applied, each strategy fills the unknown
bytes, and STOI/eSTOI are measured against the unmasked decode. Only strategies that
beat the current erase-everything baseline on held-out excerpts are applied to the
November capture. Filled bytes are substitutes, not recovered key material.
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import wave

import numpy as np

from build_evs_gcc_independent import linux_command

ROOT = Path(__file__).resolve().parents[1]
RATE = 16000
STARTS = [7 + 131*c for c in range(5)]
ROLE1_UNKNOWN = np.array([16, 19, 22, 25, 28, 31])
ROLE23_UNKNOWN = np.array([1, 4, 7, 10, 13, 16, 19, 22, 25, 28, 31])


def run(argv, log, timeout=300):
    p = subprocess.run([str(x) for x in argv], capture_output=True, timeout=timeout)
    log.append(dict(command=[str(x) for x in argv], returncode=p.returncode,
                    stderr=p.stderr.decode(errors='replace')[-400:]))
    if p.returncode:
        raise RuntimeError(log[-1])


def gcc(tool, args, log):
    run(linux_command(ROOT/'work/evs_gcc_independent'/tool, *args), log)


def decode(tmp, label, frames, keep, log, rate=RATE):
    stream, raw = tmp/(label + '.192'), tmp/(label + '.raw')
    with stream.open('wb') as f:
        for b, good in zip(np.unpackbits(frames, axis=1), keep):
            if good:
                f.write(np.array([0x6b21, 264], '<u2').tobytes())
                f.write(np.where(b, 0x81, 0x7f).astype('<u2').tobytes())
            else:
                f.write(np.array([0x6b20, 0], '<u2').tobytes())
    gcc('EVS_dec', ['-q', '-no_delay_cmp', str(rate//1000), stream, raw], log)
    return np.fromfile(raw, '<i2')


def apply_strategy(frames, name, rng, donor_source):
    """Return (frames, keep). Known bytes are never altered."""
    n = len(frames)
    slot = np.arange(n) % 4
    out = frames.copy()
    keep = slot == 0
    if name == 'erase_all':
        return out, keep
    for role, unknown in ((1, ROLE1_UNKNOWN), (2, ROLE23_UNKNOWN), (3, ROLE23_UNKNOWN)):
        if role > 1 and 'roles123' not in name:
            continue
        rows = np.flatnonzero(slot == role)
        if 'zeros' in name:
            out[np.ix_(rows, unknown)] = 0
        elif 'random' in name:
            out[np.ix_(rows, unknown)] = rng.integers(0, 256, (len(rows), len(unknown)), dtype=np.uint8)
        elif 'donor' in name:
            # Copy those byte positions from the nearest known role-0 frame.
            source = np.clip((rows + 2)//4*4, 0, (n - 1)//4*4)
            out[np.ix_(rows, unknown)] = donor_source[np.ix_(source, unknown)]
        else:
            raise ValueError(name)
        keep[rows] = True
    return out, keep


def _stoi(*args, **kwargs):
    from pystoi import stoi          # imported on use: only scoring needs it
    return stoi(*args, **kwargs)


def quality(truth, test):
    n = min(len(truth), len(test))
    a = truth[:n].astype(float)/32768
    b = test[:n].astype(float)/32768
    return dict(stoi=round(float(_stoi(a, b, RATE)), 4),
                estoi=round(float(_stoi(a, b, RATE, extended=True)), 4))


STRATEGIES = ['erase_all', 'role1_zeros', 'role1_random', 'role1_donor',
              'roles123_zeros', 'roles123_donor']


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out', required=True)
    ap.add_argument('--select', type=int, default=4, help='control excerpts used to choose')
    ap.add_argument('--holdout', type=int, default=4, help='further excerpts used only to confirm')
    a = ap.parse_args()
    out = (ROOT/a.out).resolve()
    out.mkdir(parents=True, exist_ok=False)
    log, controls = [], []
    rng = np.random.default_rng(777)
    reference = ROOT/'work/live/session_20261125T054037Z/ref_20261125T054037Z.ts'
    with tempfile.TemporaryDirectory(prefix='pq_', dir=out) as td:
        tmp = Path(td)
        for i in range(a.select + a.holdout):
            offset = 110 + i*95
            source = tmp/('c' + str(i) + '.raw')
            run(['ffmpeg', '-nostdin', '-v', 'error', '-ss', str(offset), '-i', str(reference),
                 '-map', '0:a:0', '-af', 'aresample=' + str(RATE) + ',atrim=end_sample=' + str(12*RATE),
                 '-t', '14', '-ac', '1', '-ar', str(RATE), '-f', 's16le', str(source)], log, 120)
            encoded = tmp/('c' + str(i) + '.192')
            gcc('EVS_cod', ['-q', '-no_delay_cmp', '-max_band', 'SWB', '13200', '16', source, encoded], log)
            words = np.fromfile(encoded, '<u2').reshape(-1, 266)
            frames = np.packbits(words[:, 2:] == 0x81, axis=1)
            truth = decode(tmp, 'c' + str(i) + '_truth', frames, np.ones(len(frames), bool), log)
            row = dict(excerpt='ref_' + str(offset) + 's',
                       role=('select' if i < a.select else 'holdout'), scores={})
            for name in STRATEGIES:
                built, keep = apply_strategy(frames, name, rng, frames)
                pcm = decode(tmp, 'c' + str(i) + '_' + name, built, keep, log)
                row['scores'][name] = quality(truth, pcm)
            controls.append(row)
            print(json.dumps(row), flush=True)
        baseline = 'erase_all'

        def mean(group, name, metric):
            return float(np.mean([r['scores'][name][metric] for r in controls if r['role'] == group]))

        chosen = [n for n in STRATEGIES if n != baseline
                  and mean('select', n, 'estoi') > mean('select', baseline, 'estoi') + .01
                  and mean('select', n, 'stoi') > mean('select', baseline, 'stoi')]
        chosen.sort(key=lambda n: -mean('select', n, 'estoi'))
        confirmed = [n for n in chosen
                     if mean('holdout', n, 'estoi') > mean('holdout', baseline, 'estoi') + .01
                     and mean('holdout', n, 'stoi') > mean('holdout', baseline, 'stoi')]
        summary = dict(baseline_select=dict(stoi=round(mean('select', baseline, 'stoi'), 4),
                                            estoi=round(mean('select', baseline, 'estoi'), 4)),
                       baseline_holdout=dict(stoi=round(mean('holdout', baseline, 'stoi'), 4),
                                             estoi=round(mean('holdout', baseline, 'estoi'), 4)),
                       per_strategy={n: dict(select_stoi=round(mean('select', n, 'stoi'), 4),
                                             select_estoi=round(mean('select', n, 'estoi'), 4),
                                             holdout_stoi=round(mean('holdout', n, 'stoi'), 4),
                                             holdout_estoi=round(mean('holdout', n, 'estoi'), 4))
                                     for n in STRATEGIES},
                       selected_on_select_set=chosen, confirmed_on_holdout=confirmed)
        print(json.dumps(summary, indent=2), flush=True)

        rendered = []
        if confirmed:
            best = confirmed[0]
            with np.load(ROOT/'work/nov25_repeated_text/keys.npz') as d:
                take = d['crc_supported'][:, :11].all(axis=1)
                counters = d['counters'][take].astype(np.int64)
                keys = d['ks'][take, :16].copy()
            with np.load(ROOT/'work/nov25_decode_salvaged/groups.npz') as d:
                ix = np.searchsorted(d['counters'], counters)
                assert np.array_equal(d['counters'][ix], counters)
                du = d['du'][ix].copy()
            mode_positions = [(2 + c) if role == 0 else
                              ((39 if role == 1 else 72 if role == 2 else 105) + 131*c)
                              for c in range(5) for role in range(4)]
            packet_starts = [(7 if role == 0 else 40 if role == 1 else 73 if role == 2 else 106) + 131*c
                             for c in range(5) for role in range(4)]
            runs = np.split(np.arange(len(counters)), np.flatnonzero(np.diff(counters) != 1) + 1)
            keyed = np.arange(0, 32, 3)
            for ids in runs:
                span = len(ids)*60
                frames = np.zeros((span, 33), np.uint8)
                flat = np.zeros((span, 32), np.uint8)
                slot = np.arange(span) % 4
                for k, g in enumerate(ids):
                    for p in range(3):
                        row = du[g, p]
                        for j, (start_byte, mode_byte) in enumerate(zip(packet_starts, mode_positions)):
                            i = k*60 + p*20 + j
                            flat[i] = row[start_byte:start_byte+32]
                            frames[i, 0] = row[mode_byte]
                    base = k*60
                    rows0 = base + np.flatnonzero(slot[base:base+60] == 0)
                    rows1 = base + np.flatnonzero(slot[base:base+60] == 1)
                    flat[np.ix_(rows0, keyed)] ^= keys[g, :11]
                    flat[np.ix_(rows1, keyed[:5])] ^= keys[g, 11:16]
                frames[:, 1:] = flat
                built, keep = apply_strategy(frames, best, rng, frames)
                for rate in (16000, 32000):
                    pcm = decode(tmp, 'nov_' + str(counters[ids[0]]) + '_' + str(rate), built, keep, log, rate)
                    name = ('NOV25_' + best + '_' + str(rate//1000) + 'k_' +
                            str(counters[ids[0]]) + '-' + str(counters[ids[-1]]))
                    path = out/(name + '.wav')
                    with wave.open(str(path), 'wb') as w:
                        w.setparams((1, 2, rate, 0, 'NONE', 'not compressed'))
                        w.writeframes(pcm.tobytes())
                    rendered.append(dict(file=path.name, strategy=best, rate=rate,
                                         seconds=len(pcm)/rate,
                                         rms=round(float(np.sqrt(np.mean((pcm.astype(float)/32768)**2))), 5)))
        (out/'report.json').write_text(json.dumps(dict(summary=summary, controls=controls,
            rendered=rendered,
            note='Fills are substitutes for unknown bytes, validated only on genuine controls. '
                 'November output remains unverified broadcast audio.'), indent=2), encoding='utf-8')
        (out/'calls.json').write_text(json.dumps(log, indent=2), encoding='utf-8')
        print(json.dumps(rendered, indent=2), flush=True)


if __name__ == '__main__':
    main()
