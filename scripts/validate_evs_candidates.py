"""Validate and benchmark the EVS candidate decoder against the reference EVS_dec.

a) exactness  FEED whole streams in random chunk sizes; the PCM must be byte-identical
              to 'EVS_dec -q -no_delay_cmp <rate_khz> in.192 out.raw'.
b) snapshots  random split points and random candidate modifications after the split
              (bit flips, erasures, erased frames made good, shared role-mask bytes,
              late-only changes).  Every EVAL candidate must equal EVS_dec run from
              scratch on the modified full stream; the base state must be unchanged by
              EVAL (the original continuation is FEEDed afterwards and compared); half of
              the trials pass through CHECKPOINT / FEED junk / RESTORE first; EVAL
              diagnostics must equal a fresh FEED of the same modified stream.
c) benchmark  EVAL of 256 candidates x 15 and x 60 frames (one mask byte of one role
              varied over a real broadcast group); wall time and frames/s per setting,
              plus a fresh-EVS_dec-process-per-candidate baseline for context.

Streams:
  programme  examples/nov27/programme.192.gz (TCX/HQ, 350 erasures)
  broadcast  a November 26 3205 kHz run rebuilt from a contrib dump: role 0 and role-1
             j=0..4 unmasked with CRC-supported text keys, roles 2-3 still masked, so it
             holds ACELP/TCX/HQ frames plus BER-triggered concealment; unkeyed groups
             are left fully masked and missing groups erased.
Writes <out>/validation.json (inputs with SHA-256, parameters, results).
"""
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import time

import numpy as np

from evs_candidates import (CandidateDecoder, DEFAULT_BINARY, FRAME_BYTES, group_frames_from_du,
                            known_mask_from_text, read_g192, role_byte_candidates, unmask_group,
                            write_g192)

ROOT = Path(__file__).resolve().parents[1]
EVS_DEC = ROOT/'work/evs_gcc_independent/EVS_dec'
PROGRAMME = 'examples/nov27/programme.192.gz'
DUMP = 'contrib/kcbsdrm/reference/sf_2026-11-26_0500KST_3205_hl5ntr.bin'
KEYS = 'contrib/kcbsdrm/keys/keys_2026-11-26_0500KST_3205_hl5ntr.npz'


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def evs_dec(frames, good, rate, tmp, name='stream'):
    """PCM (n, L) from the reference decoder run from scratch on these frames."""
    stream, raw = Path(tmp)/(name + '.192'), Path(tmp)/(name + '.raw')
    write_g192(stream, frames, good)
    p = subprocess.run([str(EVS_DEC), '-q', '-no_delay_cmp', str(rate//1000), str(stream), str(raw)],
                       capture_output=True, timeout=600)
    if p.returncode:
        raise RuntimeError('EVS_dec failed: ' + p.stderr.decode(errors='replace')[-500:])
    return np.fromfile(raw, '<i2').reshape(-1, rate//50)


def load_programme(tmp):
    path = Path(tmp)/'programme.192'
    path.write_bytes(gzip.decompress((ROOT/PROGRAMME).read_bytes()))
    return read_g192(path)


def load_broadcast(work, margin=10):
    """Frames around the longest run of consecutive keyed groups of the contrib dump."""
    salvage = work/'salvage_0500'
    if not (salvage/'groups.npz').exists():
        subprocess.run([sys.executable, str(ROOT/'scripts/salvage_msc_packets.py'), str(ROOT/DUMP),
                        '--out', str(salvage), '--transport-only'], check=True, capture_output=True)
    with np.load(salvage/'groups.npz') as d:
        counters, du = d['counters'].astype(int), d['du'].copy()
    with np.load(ROOT/KEYS) as k:
        keys = {int(c): ks for c, ks, ok in zip(k['counters'], k['ks'], k['crc_supported']) if ok.all()}
    index = {int(c): i for i, c in enumerate(counters)}
    runs, cur = [], []
    for c in range(counters[0], counters[-1] + 1):
        if c in index and c in keys:
            cur.append(c)
        elif cur:
            runs.append(cur)
            cur = []
    runs.append(cur)
    best = max(runs, key=len)
    span = range(best[0] - margin, best[-1] + margin + 1)
    frames, good, keyed = [], [], []
    for c in span:
        if c in index:
            f = group_frames_from_du(du[index[c]])
            if c in keys:
                f = unmask_group(f, *known_mask_from_text(keys[c]))
            frames.append(f)
            good.append(np.ones(60, bool))
        else:
            frames.append(np.zeros((60, FRAME_BYTES), np.uint8))
            good.append(np.zeros(60, bool))
        keyed.append(c in keys and c in index)
    info = dict(counters=[span[0], span[-1]], keyed_run=[best[0], best[-1]],
                keyed_groups=int(sum(keyed)), present_groups=sum(c in index for c in span))
    return np.concatenate(frames), np.concatenate(good), info, {c: keys.get(c) for c in span}


def check_exactness(streams, rates, rng, tmp):
    rows = []
    for name, (frames, good) in streams.items():
        for rate in rates:
            ref = evs_dec(frames, good, rate, tmp)
            with CandidateDecoder(rate) as dec:
                pieces, pos, chunks = [], 0, 0
                while pos < len(frames):
                    n = int(rng.integers(1, 200))
                    pcm, _ = dec.feed(frames[pos:pos + n], good[pos:pos + n])
                    pieces.append(pcm.copy())
                    pos += n
                    chunks += 1
                ours = np.concatenate(pieces)
            row = dict(stream=name, rate=rate, frames=len(frames), feed_calls=chunks,
                       identical=bool(np.array_equal(ours, ref)),
                       sha256_candidate=hashlib.sha256(ours.tobytes()).hexdigest(),
                       sha256_evs_dec=hashlib.sha256(ref.tobytes()).hexdigest())
            rows.append(row)
            print('exactness', json.dumps(row), flush=True)
    return rows


def modify(window, wgood, rng, start):
    """A random modification of a candidate window, touching frames >= start only."""
    c, g = window.copy(), wgood.copy()
    n = len(c)
    kinds = rng.choice(['flip', 'erase', 'unerase', 'mask', 'random'], size=int(rng.integers(1, 3)),
                       replace=False)
    for kind in kinds:
        if kind == 'flip':
            for _ in range(int(rng.integers(1, 25))):
                i, b = int(rng.integers(start, n)), int(rng.integers(0, 264))
                c[i, b // 8] ^= np.uint8(1 << (7 - b % 8))
        elif kind == 'erase':
            g[rng.integers(start, n, int(rng.integers(1, 6)))] = False
        elif kind == 'unerase':
            idx = np.flatnonzero(~g[start:]) + start
            if len(idx):
                i = int(rng.choice(idx))
                g[i] = True
                c[i, 1:] = rng.integers(0, 256, FRAME_BYTES - 1, dtype=np.uint8)
        elif kind == 'mask':
            role, j = int(rng.integers(0, 4)), int(rng.integers(0, 11))
            rows = np.arange(start, n)
            rows = rows[(rows % 4) == role]
            c[rows, 1 + 3*j] ^= np.uint8(rng.integers(1, 256))
        else:
            i = int(rng.integers(start, n))
            c[i, 1:] = rng.integers(0, 256, FRAME_BYTES - 1, dtype=np.uint8)
            g[i] = True
    return c, g


def check_snapshots(streams, trials, K, rng, tmp):
    rows = []
    refs = {}
    names = list(streams)
    for t in range(trials):
        name = names[t % len(names)]
        frames, good = streams[name]
        rate = (16000, 32000)[(t // len(names)) % 2]
        if (name, rate) not in refs:
            refs[name, rate] = evs_dec(frames, good, rate, tmp)
        ref = refs[name, rate]
        N = int(rng.integers(15, 61))
        s = int(rng.integers(1, len(frames) - N))
        late = int(rng.integers(0, N)) if t % 3 == 2 else 0
        window, wgood = frames[s:s + N], good[s:s + N]
        cands, cgood = [window.copy()], [wgood.copy()]
        for _ in range(K - 1):
            c, g = modify(window, wgood, rng, late)
            cands.append(c)
            cgood.append(g)
        cands, cgood = np.array(cands), np.array(cgood)
        use_checkpoint = t % 2 == 1
        with CandidateDecoder(rate) as dec:
            dec.feed(frames[:s], good[:s])
            if use_checkpoint:
                dec.checkpoint('split')
                junk = rng.integers(0, 256, (7, FRAME_BYTES), dtype=np.uint8)
                dec.feed(junk, rng.random(7) < 0.7)
                dec.restore('split')
            res = dec.eval(cands, cgood)
            after, _ = dec.feed(window, wgood)
            base_unchanged = bool(np.array_equal(after, ref[s:s + N]))
            per = []
            for k in range(K):
                full = evs_dec(np.concatenate([frames[:s], cands[k]]),
                               np.concatenate([good[:s], cgood[k]]), rate, tmp, 'cand')
                dec.reset(rate)
                dec.feed(frames[:s], good[:s])
                _, fresh_diag = dec.feed(cands[k], cgood[k])
                per.append(dict(
                    pcm_identical=bool(np.array_equal(full[s:], res.pcm[k])),
                    history_identical=bool(np.array_equal(full[:s], ref[:s])),
                    diag_identical=bool(fresh_diag.tobytes() == res.diag[k].tobytes()),
                    status=int(res.status[k]),
                    frames_changed=int(((cands[k] != window).any(1) | (cgood[k] != wgood)).sum()),
                    bfi_out=int(res.diag[k]['bfi_out'].sum()),
                    ber_detect=int(res.diag[k]['ber_detect'].sum())))
        row = dict(trial=t, stream=name, rate=rate, split=s, N=N, K=K, changes_from=late,
                   prefix=int(res.prefix), checkpoint_restore=use_checkpoint,
                   base_unchanged=base_unchanged,
                   all_identical=all(p['pcm_identical'] and p['history_identical'] and
                                     p['diag_identical'] and p['status'] == 0 for p in per),
                   candidates=per)
        rows.append(row)
        print('snapshot', json.dumps({k: v for k, v in row.items() if k != 'candidates'}), flush=True)
    return rows


def eval_cpu_seconds(dec):
    """CPU seconds consumed so far by reaped EVAL descendants of the base state process.

    The state process waits for its dispatcher, the dispatcher for its workers and the
    workers for their candidate children, so cutime+cstime of the base (a direct child of
    the router) accumulates all EVAL decoding.  Linux /proc only."""
    pid = dec._proc.pid
    ticks = os.sysconf('SC_CLK_TCK')
    total = 0
    for child in Path('/proc/%d/task/%d/children' % (pid, pid)).read_text().split():
        fields = Path('/proc/%s/stat' % child).read_text().rsplit(')', 1)[1].split()
        total += int(fields[13]) + int(fields[14])      # cutime, cstime
    return total/ticks


def benchmark(frames, good, keys, info, repeats, tmp):
    """EVAL 256 candidates of one mask byte over a real broadcast group."""
    c0 = info['counters'][0]
    g = info['keyed_run'][0] - c0 + 12          # a keyed group with history before it
    group = frames[60*g:60*g + 60]
    mask, known = known_mask_from_text(keys[c0 + g])
    # `group` is already unmasked for known bytes; pass a zero mask so nothing is re-applied
    zero = np.zeros_like(mask)
    rows = []
    for rate in (16000, 32000):
        for jobs in (4, 1):
            with CandidateDecoder(rate, jobs=jobs) as dec:
                dec.feed(frames[:60*g], good[:60*g])
                for erase in ('unknown', ()):
                    cands, cgood = role_byte_candidates(group, zero, known, role=1, j=5,
                                                        erase_roles=erase)
                    for N in (15, 60):
                        times = []
                        load = os.getloadavg()[0]
                        cpu0 = eval_cpu_seconds(dec)
                        for _ in range(repeats):
                            t0 = time.perf_counter()
                            res = dec.eval(cands[:, :N], cgood[:, :N])
                            times.append(time.perf_counter() - t0)
                        cpu = (eval_cpu_seconds(dec) - cpu0)/repeats
                        assert (res.status == 0).all()
                        med = float(np.median(times))
                        row = dict(rate=rate, jobs=jobs, K=256, N=N,
                                   erased_roles='2,3' if erase == 'unknown' else 'none',
                                   wall_median_s=round(med, 4), wall_min_s=round(min(times), 4),
                                   frames_per_s=round(256*N/med),
                                   frames_per_s_best=round(256*N/min(times)),
                                   cpu_s_per_eval=round(cpu, 4),
                                   frames_per_cpu_s=round(256*N/cpu) if cpu else None,
                                   loadavg_1min_before=round(load, 2), prefix=int(res.prefix))
                        rows.append(row)
                        print('benchmark', json.dumps(row), flush=True)
    # context: one fresh -O0 EVS_dec process per candidate from the group boundary
    cands, cgood = role_byte_candidates(group, zero, known, role=1, j=5, erase_roles=())
    t0 = time.perf_counter()
    n = 32
    for k in range(n):
        evs_dec(cands[k], cgood[k], 16000, tmp, 'base')
    per = (time.perf_counter() - t0)/n
    baseline = dict(method='fresh EVS_dec (-O0) process per candidate, 60 frames, no history, '
                           'sequential', candidates_timed=n, seconds_per_candidate=round(per, 4),
                    extrapolated_256_s=round(256*per, 2), loadavg_1min=round(os.getloadavg()[0], 2))
    print('baseline', json.dumps(baseline), flush=True)
    return rows, baseline


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--out', default='work/evs_candidate/validation')
    ap.add_argument('--seed', type=int, default=20261128)
    ap.add_argument('--trials', type=int, default=24, help='snapshot-equivalence trials')
    ap.add_argument('--candidates', type=int, default=6, help='candidates per trial')
    ap.add_argument('--repeats', type=int, default=5, help='benchmark repeats per setting')
    ap.add_argument('--skip', nargs='*', default=[], choices=['exactness', 'snapshots', 'benchmark'])
    a = ap.parse_args()
    out = (ROOT/a.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    for path in (DEFAULT_BINARY, EVS_DEC):
        if not Path(path).exists():
            raise SystemExit('%s missing (build_evs_candidate_decoder.py / build_evs_gcc_independent.py)'
                             % path)
    rng = np.random.default_rng(a.seed)
    started = time.time()
    with tempfile.TemporaryDirectory(dir=out) as tmp:
        programme = load_programme(tmp)
        bframes, bgood, binfo, bkeys = load_broadcast(out)
        streams = {'programme': programme, 'broadcast': (bframes, bgood)}
        receipt = dict(
            tool='validate_evs_candidates.py', seed=a.seed,
            inputs={p: sha256(ROOT/p) for p in (PROGRAMME, DUMP, KEYS)},
            binaries={str(DEFAULT_BINARY.relative_to(ROOT)): sha256(DEFAULT_BINARY),
                      str(EVS_DEC.relative_to(ROOT)): sha256(EVS_DEC)},
            build_json_sha256=sha256(DEFAULT_BINARY.parent/'build.json')
            if (DEFAULT_BINARY.parent/'build.json').exists() else None,
            machine=dict(cpus=os.cpu_count(), platform=platform.platform(),
                         loadavg_at_start=[round(x, 2) for x in os.getloadavg()],
                         cpu=next((l.split(':', 1)[1].strip() for l in
                                   open('/proc/cpuinfo') if l.startswith('model name')), None)),
            streams=dict(programme=dict(frames=len(programme[0]), good=int(programme[1].sum())),
                         broadcast=dict(frames=len(bframes), good=int(bgood.sum()), **binfo)))
        if 'exactness' not in a.skip:
            rows = check_exactness(streams, (16000, 32000, 48000), rng, tmp)
            receipt['exactness'] = dict(all_identical=all(r['identical'] for r in rows), runs=rows)
        if 'snapshots' not in a.skip:
            rows = check_snapshots(streams, a.trials, a.candidates, rng, tmp)
            receipt['snapshots'] = dict(
                trials=len(rows), candidates=sum(len(r['candidates']) for r in rows),
                all_identical=all(r['all_identical'] for r in rows),
                base_unchanged=all(r['base_unchanged'] for r in rows),
                prefix_lengths=sorted({r['prefix'] for r in rows}), runs=rows)
        if 'benchmark' not in a.skip:
            rows, baseline = benchmark(bframes, bgood, bkeys, binfo, a.repeats, tmp)
            receipt['benchmark'] = dict(runs=rows, baseline=baseline)
    receipt['seconds'] = round(time.time() - started, 1)
    (out/'validation.json').write_text(json.dumps(receipt, indent=2), encoding='utf-8')
    summary = {k: receipt[k].get('all_identical') for k in ('exactness', 'snapshots') if k in receipt}
    print(json.dumps(dict(validation=str(out/'validation.json'), **summary)))
    if not all(summary.values()):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
