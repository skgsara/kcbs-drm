#!/usr/bin/env python3
"""Mask-byte recovery by CODEC-PARAMETER LIKELIHOOD (method 'params').

Instrumented decoder.  `--build` compiles patched COPIES of the EVS reference
lib_com/bitstream.c (every bit reader wrapped: call site, reader kind, bit position, width
and value of each read are logged) and lib_dec/hq_lr_dec.c (decoded HQ band-energy indices),
plus a copy of the candidate harness scripts/evs_candidate_decoder.c that returns each frame's
parameter log (and LSF, pitch, IGF values from the decoder state) in place of its PCM.  The
patches are applied textually at build time under work/methods/params/build; no reference
code is tracked.  The decoder's parse is unchanged (diagnostics bit-identical to the harness).

Priors from CLEAR frames.  A field is a call site (+ width + reader).  FieldModel learns
  * marginals P(v) (dense over the top 10 bits, per-bit below) from clear frames of public audio
    that is in no benchmark split (`--make-train`, encoded like the synthetic splits) and from
    DEV role-0 frames (visible in every T1/TH input),
  * neighbour conditionals P(v_t | v_{t-lag}) for lags +-1..3 (consecutive clear synthetic
    frames; same site and occurrence) and within-frame P(v_k | v_{k-1}) of repeated sites,
  * log-density ratios (consecutive vs random frame) of decoded LSF, pitch, IGF scale-factor and
    HQ band-energy differences.
Scoring.  For target byte (role r, j) all 256 values are decoded with the fork-snapshot harness
(other roles with unknown bytes erased, earlier bytes of the role fixed at their current best
value).  For each of the role's 15 frames, the entries whose bits overlap byte j, or that are
read from clear bits before the next unknown byte (parse alignment), are scored: marginal LLR
vs uniform, neighbour / occurrence LLR vs the marginal (reference = nearest clear frame),
decoded-value LLRs, plus parse-validity counts (BER/bfi, bit position, unseen fields), each
summed per core family (ACELP / TCX / HQ).  A conditional logit (weights fitted on own synthetic
items and DEV labels, see the freeze record) turns them into a 256-way distribution.

The predict path reads only the given inputs file (never truth):
    python3 scripts/mask_method_params.py --inputs work/benchmark/tasks/dev.T1.inputs.npz \
        --out work/methods/params/dev.T1.pred.npz [--groups 300 --seed 1] [--control wrong-group]
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))
REF = ROOT/'work/ref/evs/src/c-code'
WORK = ROOT/'work/methods/params'
BUILD = WORK/'build'
BINARY = BUILD/'evs_param_decoder'
HARNESS = SCRIPTS/'evs_candidate_decoder.c'
BUILD_FLAGS = ['-O2', '-std=gnu99', '-fno-strict-aliasing', '-fwrapv', '-ffp-contract=off',
               '-fno-optimize-sibling-calls', '-fno-pie', '-g']
LINK_FLAGS = ['-no-pie']

# ---------------------------------------------------------------------------
# build: patched COPIES of lib_com/bitstream.c and of the candidate harness
# ---------------------------------------------------------------------------
# Every bit reader (get_next_indice, get_next_indice_1, get_indice, get_indice_1,
# get_next_indice_tmp) is renamed to a static pl_* original and wrapped by a
# noinline function that logs (return address, kind, bit position, nbits, value).
# The return address identifies the call site (mapped to function/file:line with
# addr2line).  The harness writes the frame's log in place of the PCM of that frame
# (48 kHz output: 1920 bytes per frame).
PL_CODE = r'''
/* ---- params method: per-frame bit-read log (appended at build time) ---- */
#include <stdint.h>
#include <string.h>
#define PL_BYTES   1920
#define PL_VALS    64                    /* decoded floats at the end of the record */
#define PL_MAXENT  ((PL_BYTES - 4*PL_VALS)/8 - 1)
typedef struct { uint32_t site; uint16_t pos; uint16_t value; } pl_entry;
static pl_entry pl_buf[PL_MAXENT];
static int pl_n = 0, pl_trunc = 0;

static void pl_log(void *ra, int kind, int pos, int nbits, unsigned value)
{
    uint32_t a = (uint32_t)((uintptr_t)ra - 0x400000u) & 0xFFFFFFu;
    if (pl_n > 0 && kind == 1)
    {
        pl_entry *e = &pl_buf[pl_n - 1];
        int en = (e->site >> 24) & 31, ek = e->site >> 29;
        if (ek == 1 && (e->site & 0xFFFFFFu) == a && e->pos + en == pos && en < 16)
        {
            e->value = (uint16_t)((e->value << 1) | (value & 1));
            e->site = (e->site & ~(31u << 24)) | ((uint32_t)(en + 1) << 24);
            return;
        }
    }
    if (pl_n >= PL_MAXENT)
    {
        pl_trunc++;
        return;
    }
    pl_buf[pl_n].site = a | ((uint32_t)(nbits & 31) << 24) | ((uint32_t)(kind & 7) << 29);
    pl_buf[pl_n].pos = (uint16_t)pos;
    pl_buf[pl_n].value = (uint16_t)value;
    pl_n++;
}

void pl_value(int tag, int idx, int value)
{
    if (pl_n >= PL_MAXENT)
    {
        pl_trunc++;
        return;
    }
    pl_buf[pl_n].site = (uint32_t)(tag & 0xFFFFFF) | (5u << 29);
    pl_buf[pl_n].pos = (uint16_t)idx;
    pl_buf[pl_n].value = (uint16_t)(int16_t)value;
    pl_n++;
}

void pl_begin_frame(void)
{
    pl_n = 0;
    pl_trunc = 0;
}

void pl_end_frame(Decoder_State *st, unsigned char *out, int out_bytes)
{
    float v[PL_VALS];
    uint16_t head[4];
    int i, k = 0;
    if (out_bytes < PL_BYTES)
    {
        return;
    }
    memset(out, 0, PL_BYTES);
    head[0] = (uint16_t)pl_n;
    head[1] = (uint16_t)(pl_trunc > 65535 ? 65535 : pl_trunc);
    head[2] = (uint16_t)st->next_bit_pos;
    head[3] = (uint16_t)(st->total_brate / 50);
    memcpy(out, head, 8);
    memcpy(out + 8, pl_buf, (size_t)pl_n * sizeof(pl_entry));
    memset(v, 0, sizeof(v));
    for (i = 0; i < M; i++) v[k++] = st->lsf_old[i];                 /* 0..15 */
    for (i = 0; i < 2*NB_SUBFR16k+2; i++) v[k++] = st->old_pitch_buf[i];   /* 16..27 */
    v[k++] = st->lp_gainp;  v[k++] = st->lp_gainc;  v[k++] = st->lp_ener;  v[k++] = st->enr_old;
    v[k++] = st->old_enr_LP; v[k++] = st->tilt_code; v[k++] = st->prev_ener_shb; v[k++] = st->old_fpitch;
    v[k++] = st->tcxltp_gain; v[k++] = (float)st->tcxltp_pitch_int; v[k++] = st->last_gain_syn_deemph;
    for (i = 0; i < GAIN_PRED_ORDER; i++) v[k++] = st->past_qua_en[i];
    v[k++] = st->prev_gain_pit_dec; v[k++] = st->old_Es_pred;
    for (i = 0; i < 16; i++) v[k++] = (float)st->hIGFDec.igfData.igf_curr[i];   /* 45..60 */
    v[k++] = (float)st->hIGFDec.igfData.igf_curr[16];
    memcpy(out + PL_BYTES - 4*PL_VALS, v, sizeof(v));
}

__attribute__((noinline)) unsigned short get_next_indice(Decoder_State *st, short nb_bits)
{
    int pos = st->next_bit_pos;
    unsigned short v = pl_get_next_indice(st, nb_bits);
    pl_log(__builtin_return_address(0), 0, pos, nb_bits, v);
    return v;
}

__attribute__((noinline)) unsigned short get_next_indice_1(Decoder_State *st)
{
    int pos = st->next_bit_pos;
    unsigned short v = pl_get_next_indice_1(st);
    pl_log(__builtin_return_address(0), 1, pos, 1, v);
    return v;
}

__attribute__((noinline)) void get_next_indice_tmp(Decoder_State *st, short nb_bits)
{
    int pos = st->next_bit_pos;
    pl_get_next_indice_tmp(st, nb_bits);
    pl_log(__builtin_return_address(0), 4, pos, 0, (unsigned)(uint16_t)nb_bits);
}

__attribute__((noinline)) unsigned short get_indice(Decoder_State *st, short pos, short nb_bits)
{
    unsigned short v = pl_get_indice(st, pos, nb_bits);
    pl_log(__builtin_return_address(0), 2, pos, nb_bits, v);
    return v;
}

__attribute__((noinline)) unsigned short get_indice_1(Decoder_State *st, short pos)
{
    unsigned short v = pl_get_indice_1(st, pos);
    pl_log(__builtin_return_address(0), 3, pos, 1, v);
    return v;
}
'''

BITSTREAM_RENAMES = [
    ('unsigned short get_next_indice(   /* o  : value of the indice */',
     'static unsigned short pl_get_next_indice(   /* o  : value of the indice */'),
    ('unsigned short get_next_indice_1(     /* o  : value of the indice */',
     'static unsigned short pl_get_next_indice_1(     /* o  : value of the indice */'),
    ('void get_next_indice_tmp(\n', 'static void pl_get_next_indice_tmp(\n'),
    ('unsigned short get_indice(    /* o  : value of the indice */',
     'static unsigned short pl_get_indice(    /* o  : value of the indice */'),
    ('unsigned short get_indice_1(  /* o  : value of the indice */',
     'static unsigned short pl_get_indice_1(  /* o  : value of the indice */'),
]
HQ_LR_PATCHES = [
    ('        bq1[k] = bq2[k] + bq1[k - 1];\n    }\n',
     '        bq1[k] = bq2[k] + bq1[k - 1];\n    }\n'
     '    { extern void pl_value(int tag, int idx, int value); int kk;\n'
     '      for (kk = 0; kk < bands; kk++) pl_value(1, kk, bq1[kk]); }\n'),
]
HARNESS_PATCHES = [
    ('#include "rom_com.h"\n',
     '#include "rom_com.h"\n'
     'void pl_begin_frame(void);\n'
     'void pl_end_frame(Decoder_State *st, unsigned char *out, int out_bytes);\n'),
    ('        if (!read_indices(st, fp, 0))\n',
     '        pl_begin_frame();\n        if (!read_indices(st, fp, 0))\n'),
    ('        clipped = syn_output(output, (short)cd_output_frame, data);\n',
     '        clipped = syn_output(output, (short)cd_output_frame, data);\n'
     '        pl_end_frame(st, (unsigned char *)data, (int)(sizeof(short) * cd_output_frame));\n'),
]


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _patch(text, patches, name):
    for old, new in patches:
        if text.count(old) != 1:
            raise RuntimeError('%s: patch anchor found %d times: %r' % (name, text.count(old), old))
        text = text.replace(old, new)
    return text


def build(out=BUILD, jobs=2):
    """Compile the instrumented parameter-log decoder into `out` (work/methods/params/build)."""
    from build_evs_candidate_decoder import compile_one, reference_sources
    from build_evs_gcc_independent import linux, linux_command
    out = Path(out).resolve()
    src_dir, objdir = out/'src', out/'obj'
    for d in (src_dir, objdir):
        if d.exists():
            shutil.rmtree(d)
        d.mkdir(parents=True)
    bitstream = (REF/'lib_com/bitstream.c').read_text(encoding='latin1')
    bitstream = _patch(bitstream, BITSTREAM_RENAMES, 'bitstream.c') + PL_CODE
    (src_dir/'bitstream.c').write_text(bitstream, encoding='latin1')
    hq = (REF/'lib_dec/hq_lr_dec.c').read_text(encoding='latin1')
    (src_dir/'hq_lr_dec.c').write_text(_patch(hq, HQ_LR_PATCHES, 'hq_lr_dec.c'), encoding='latin1')
    harness = _patch(HARNESS.read_text(encoding='utf-8'), HARNESS_PATCHES, HARNESS.name)
    (src_dir/'evs_param_decoder.c').write_text(harness, encoding='utf-8')
    patched = ('bitstream.c', 'hq_lr_dec.c')
    sources = [p for p in reference_sources(REF) if p.name not in patched]
    sources += [src_dir/n for n in patched] + [src_dir/'evs_param_decoder.c']
    includes = ['-I' + linux(REF/sub) for sub in ('lib_com', 'lib_dec', 'lib_enc')]
    t0 = time.time()
    with ThreadPoolExecutor(jobs) as pool:
        futs = [pool.submit(compile_one, s, objdir/('%03d_%s.o' % (i, s.stem)), BUILD_FLAGS, includes)
                for i, s in enumerate(sources)]
        results = [f.result() for f in futs]
    failed = [(s, err) for s, code, err in results if code]
    if failed:
        raise RuntimeError('compile failed: %s\n%s' % (failed[0][0], failed[0][1][-3000:]))
    rsp = out/'link.rsp'
    rsp.write_text('\n'.join('"%s"' % linux(o) for o in sorted(objdir.glob('*.o'))))
    r = subprocess.run(linux_command('gcc', *BUILD_FLAGS, *LINK_FLAGS, '@' + linux(rsp), '-lm',
                                     '-o', out/BINARY.name), capture_output=True)
    if r.returncode:
        raise RuntimeError('link failed: ' + r.stderr.decode(errors='replace')[-3000:])
    shutil.rmtree(objdir)
    receipt = dict(binary=str(out/BINARY.name), sha256=_sha(out/BINARY.name), flags=BUILD_FLAGS,
                   link=LINK_FLAGS, harness_sha256=_sha(HARNESS),
                   ref_sha256={n: _sha(REF/n) for n in ('lib_com/bitstream.c', 'lib_dec/hq_lr_dec.c')},
                   patched_sha256={p.name: _sha(p) for p in sorted(src_dir.glob('*.c'))},
                   seconds=round(time.time() - t0, 1))
    (out/'build.json').write_text(json.dumps(receipt, indent=2))
    return receipt


# ---------------------------------------------------------------------------
# clear training streams: public audio that is in NO benchmark split, encoded
# exactly like the synthetic splits (EVS_cod -q -max_band SWB 13200 32, -20 dBFS)
# ---------------------------------------------------------------------------
_ARCH = 'https://archive.org/download/'
_WJS = _ARCH + 'wangjaesangyongumaktan-che1chip/'
TRAIN_SOURCES = (
    dict(name='wjs-01-happy-country', url=_WJS + '01.%20%ED%96%89%EB%B3%B5%ED%95%9C%20%EB%82%B4%20%EB%82%98%EB%9D%BC%20%3D%20My%20Happy%20Country.mp3', start=0, seconds=120),
    dict(name='wjs-04-merry-laughter', url=_WJS + '04.%20%EC%9B%83%EC%9D%8C%EA%BD%83%EC%9D%B4%20%EB%A7%8C%EB%B0%9C%ED%96%88%EB%84%A4%20%3D%20Merry%20Laughter%20Is%20In%20Full%20Bloom.mp3', start=0, seconds=120),
    dict(name='wjs-07-wellside', url=_WJS + '07.%20%EC%83%98%EB%AC%BC%ED%84%B0%EC%97%90%EC%84%9C%20%20%3D%20By%20The%20Wellside.mp3', start=0, seconds=120),
    dict(name='wjs-10-return-voyage', url=_WJS + '10.%20%EA%B7%80%ED%95%AD%EC%9D%98%20%EB%85%B8%EB%9E%98%20%3D%20Song%20Of%20Return%20Voyage.mp3', start=0, seconds=120),
    dict(name='wjs-13-cuckoos', url=_WJS + '13.%20%EB%BB%90%EA%BE%B9%EC%83%88%20%3D%20Cuckoos.mp3', start=0, seconds=120),
    dict(name='librivox-ko-hyun-02', url=_ARCH + 'short_stories_hyun_1411_librivox/short_stories_02_hyun_128kb.mp3', start=0, seconds=150),
    dict(name='librivox-ko-hyun-03', url=_ARCH + 'short_stories_hyun_1411_librivox/short_stories_03_hyun_128kb.mp3', start=0, seconds=150),
)
TRAIN_DIR = WORK/'train'


def make_train_streams(out=TRAIN_DIR):
    """Download TRAIN_SOURCES and encode each to a clear G.192 stream (frames npz)."""
    import urllib.request
    import numpy as np
    from build_mask_benchmark import pcm_32k, normalise, encode
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    receipt = []
    for src in TRAIN_SOURCES:
        npz = out/(src['name'] + '.npz')
        dl = out/'audio'/src['name']
        dl.mkdir(parents=True, exist_ok=True)
        path = dl/'source.mp3'
        if not path.exists():
            req = urllib.request.Request(src['url'], headers={'User-Agent': 'evs-research/1'})
            with urllib.request.urlopen(req, timeout=300) as r, open(path, 'wb') as f:
                shutil.copyfileobj(r, f)
        if not npz.exists():
            pcm, gain_db = normalise(pcm_32k(path, src['start'], src['seconds']))
            frames, stream = encode(pcm, out, src['name'])
            np.savez_compressed(npz, frames=frames)
            stream.unlink()
        frames = np.load(npz)['frames']
        receipt.append(dict(src, sha256=_sha(path), frames=int(len(frames))))
        print(json.dumps(receipt[-1]), flush=True)
    (out/'receipt.json').write_text(json.dumps(receipt, indent=2))
    return receipt


# ---------------------------------------------------------------------------
# parameter logs
# ---------------------------------------------------------------------------
RATE = 48000
REC_BYTES = 1920
N_VALS = 64
MAX_ENT = (REC_BYTES - 4*N_VALS)//8 - 1
KIND_NEXT, KIND_BIT, KIND_ABS, KIND_ABS1, KIND_SKIP, KIND_VALUE = range(6)
FRAME_BITS = 264


def keyed_range(j):
    """Frame bit range [lo, hi) of mask byte j (payload byte 3j)."""
    return 8 + 24*j, 16 + 24*j


def parse_logs(pcm):
    """Flat entry table from param-decoder records pcm (R, 960) int16 (R = frames).

    Returns dict of arrays over entries: row, site (u32 raw word), addr, nbits, kind,
    pos, value (u16; int16 for KIND_VALUE/KIND_SKIP), occ (occurrence of the same
    site word within its row), plus per-row n, trunc and vals (R, 64) float32."""
    import numpy as np
    b = np.ascontiguousarray(pcm).view(np.uint8).reshape(-1, REC_BYTES)
    head = b[:, :8].copy().view('<u2')
    n = head[:, 0].astype(np.int64)
    ent = b[:, 8:8 + 8*MAX_ENT].copy().view(np.dtype([('site', '<u4'), ('pos', '<u2'), ('value', '<u2')]))
    valid = np.arange(MAX_ENT)[None, :] < n[:, None]
    rows, cols = np.nonzero(valid)
    e = ent[rows, cols]
    site = e['site'].astype(np.uint32)
    kind = (site >> 29).astype(np.int8)
    out = dict(row=rows.astype(np.int32), site=site, addr=(site & 0xFFFFFF).astype(np.uint32),
               nbits=((site >> 24) & 31).astype(np.int16), kind=kind,
               pos=e['pos'].astype(np.int32), value=e['value'].astype(np.int32))
    sv = (kind == KIND_VALUE) | (kind == KIND_SKIP)
    out['value'][sv] = e['value'][sv].astype(np.int16).astype(np.int32)
    # occurrence index of the same site word within the row
    order = np.lexsort((cols, site, rows))
    occ = np.zeros(len(rows), np.int16)
    if len(rows):
        key_r, key_s = rows[order], site[order]
        start = np.r_[True, (key_r[1:] != key_r[:-1]) | (key_s[1:] != key_s[:-1])]
        idx = np.arange(len(order))
        first = np.maximum.accumulate(np.where(start, idx, 0))
        occ[order] = (idx - first).astype(np.int16)
    out['occ'] = occ
    out['n'] = n
    out['trunc'] = head[:, 1].astype(np.int64)
    out['vals'] = b[:, REC_BYTES - 4*N_VALS:].copy().view('<f4').reshape(-1, N_VALS)
    return out


def site_names(addrs, binary=BINARY):
    """{addr: 'function file:line'} via addr2line (return address - 1)."""
    addrs = sorted(set(int(a) for a in addrs))
    if not addrs:
        return {}
    r = subprocess.run(['addr2line', '-f', '-s', '-e', str(binary)] +
                       [hex(0x400000 + a - 1) for a in addrs], capture_output=True, text=True)
    lines = r.stdout.split('\n')
    return {a: '%s %s' % (lines[2*k], lines[2*k + 1]) for k, a in enumerate(addrs)}


def open_decoder(jobs=2):
    from evs_candidates import CandidateDecoder
    if not BINARY.exists():
        build()
    return CandidateDecoder(rate=RATE, binary=BINARY, jobs=jobs)



# ---------------------------------------------------------------------------
# clear-frame corpora for the priors
# ---------------------------------------------------------------------------
DIAG_KEEP = ('bfi_out', 'ber_detect', 'core', 'coder_type', 'extl', 'next_bit_pos', 'nbits', 'bwidth')


def _corpus_from_feed(dec, frames, good, keep, stream_id, frame_index, group_index):
    """Decode frames (n, 33) with FEED and return the logs of rows `keep` (bool n)."""
    import numpy as np
    pcm, diag = dec.feed(frames, good)
    L = parse_logs(pcm)
    rows = np.flatnonzero(keep)
    remap = -np.ones(len(frames), np.int64)
    remap[rows] = np.arange(len(rows))
    sel = remap[L['row']] >= 0
    ent = {k: L[k][sel] for k in ('site', 'pos', 'value', 'occ')}
    ent['row'] = remap[L['row'][sel]]
    meta = dict(stream=np.full(len(rows), stream_id, np.int32), frame=frame_index[rows].astype(np.int32),
                group=group_index[rows].astype(np.int32), mode=frames[rows, 0].astype(np.int16),
                vals=L['vals'][rows], n=L['n'][rows], trunc=L['trunc'][rows])
    for k in DIAG_KEEP:
        meta['d_' + k] = diag[k][rows].astype(np.int16)
    return ent, meta


def _concat(parts):
    import numpy as np
    ents, metas = zip(*parts)
    offs = np.cumsum([0] + [len(m['stream']) for m in metas[:-1]])
    ent = {k: np.concatenate([e[k] + (o if k == 'row' else 0) for e, o in zip(ents, offs)]) for k in ents[0]}
    meta = {k: np.concatenate([m[k] for m in metas]) for k in metas[0]}
    return ent, meta


def corpus_train_streams(out=WORK/'corpus_syn.npz', jobs=2):
    """Clear consecutive frames of every TRAIN_SOURCES stream (decoded from the start)."""
    import numpy as np
    parts = []
    dec = open_decoder(jobs)
    for sid, src in enumerate(TRAIN_SOURCES):
        frames = np.load(TRAIN_DIR/(src['name'] + '.npz'))['frames']
        dec.reset(RATE)
        n = len(frames)
        idx = np.arange(n)
        parts.append(_corpus_from_feed(dec, frames, np.ones(n, bool), np.ones(n, bool), sid, idx, idx//60))
    dec.close()
    ent, meta = _concat(parts)
    np.savez_compressed(out, **{'e_' + k: v for k, v in ent.items()}, **meta)
    return out


def visible_mask(known_row):
    """(mask (4, 11) uint8, known (4, 11) bool) from a benchmark int16 known row (44,)."""
    import numpy as np
    kn = np.asarray(known_row)
    return np.where(kn >= 0, kn, 0).astype(np.uint8).reshape(4, 11), (kn >= 0).reshape(4, 11)


def corpus_role0(inputs, out, jobs=2):
    """Role-0 frames of every group whose role-0 mask is fully visible in a T1/TH inputs file,
    decoded run by run with every role that has an unknown byte erased (inference context)."""
    import numpy as np
    from evs_candidates import unmask_group
    d = np.load(inputs)
    dec = open_decoder(jobs)
    parts = []
    for run in np.unique(d['run_id']):
        gs = np.flatnonzero(d['run_id'] == run)
        frames, good, keep = [], [], []
        for g in gs:
            mask, known = visible_mask(d['known'][g])
            frames.append(unmask_group(d['frames'][g], mask, known))
            gd = d['present'][g].copy()
            for r in range(4):
                if not known[r].all():
                    gd[r::4] = False
            good.append(gd)
            kp = np.zeros(60, bool)
            kp[0::4] = gd[0::4] & known[0].all()
            keep.append(kp)
        frames, good, keep = np.concatenate(frames), np.concatenate(good), np.concatenate(keep)
        dec.reset(RATE)
        fidx = np.arange(len(frames))
        parts.append(_corpus_from_feed(dec, frames, good, keep, int(run), fidx, gs[fidx//60]))
    dec.close()
    ent, meta = _concat(parts)
    np.savez_compressed(out, **{'e_' + k: v for k, v in ent.items()}, **meta)
    return out



# ---------------------------------------------------------------------------
# field models learned from clear frames
# ---------------------------------------------------------------------------
HEAD_BITS = 10       # dense table over the top bits of a field; lower bits per-bit
SMALL_BITS = 6       # fields up to this width get a full conditional table P(v | v_ref)
LAGS = (1, -1, 2, -2, 3, -3)     # reference frame = t - lag (lag > 0: an earlier frame)


def _bits_of(v, n):
    import numpy as np
    sh = np.arange(n - 1, -1, -1)
    return (np.asarray(v)[:, None] >> sh[None, :]) & 1


class FieldModel:
    """Marginal and neighbour-conditioned distributions of every bit-read field.

    A field is a raw site word (call site + nbits + reader kind).  Marginal:
    P(v) = head(top h bits) * prod per-bit(low bits), head shrunk towards the per-bit
    model with strength beta.  Neighbour (lag L, matched on site word and occurrence):
    n <= SMALL_BITS: full conditional table shrunk towards the marginal;
    SMALL_BITS < n <= HEAD_BITS: (1-lam) P(v) + lam H(v - v_ref), lam by EM.
    Decoded values: Laplace scales of lag differences of LSF, pitch, HQ band
    energies and IGF scale factors."""

    def __init__(self, beta=8.0, beta_nb=4.0):
        self.beta, self.beta_nb = beta, beta_nb

    # -- marginals --------------------------------------------------------------
    def fit_marginal(self, sites, values, weights=None):
        import numpy as np
        kind = sites >> 29
        nb = (sites >> 24) & 31
        ok = (kind < 4) & (nb > 0)
        sites, values = sites[ok], values[ok]
        w = np.ones(len(sites)) if weights is None else np.asarray(weights, float)[ok]
        keys, inv = np.unique(sites, return_inverse=True)
        self.keys = keys
        self.nb = ((keys >> 24) & 31).astype(np.int64)
        self.h = np.minimum(self.nb, HEAD_BITS)
        self.count = np.bincount(inv, w, len(keys))
        self.bitlp = []          # per field: (n, 2) log P(bit = 0/1)
        self.head_off = np.zeros(len(keys) + 1, np.int64)
        self.head_off[1:] = np.cumsum(1 << self.h)
        self.head = np.zeros(self.head_off[-1])
        order = np.argsort(inv, kind='stable')
        bounds = np.searchsorted(inv[order], np.arange(len(keys) + 1))
        for f in range(len(keys)):
            sel = order[bounds[f]:bounds[f + 1]]
            n, h = int(self.nb[f]), int(self.h[f])
            v, ww = values[sel].astype(np.int64), w[sel]
            b = _bits_of(v, n)
            p1 = (ww @ b + 0.5)/(ww.sum() + 1.0)
            lp = np.log(np.stack([1 - p1, p1], 1))
            self.bitlp.append(lp)
            u = np.arange(1 << h)
            q = np.exp(_bits_of(u, h) @ lp[:h, 1] + (1 - _bits_of(u, h)) @ lp[:h, 0])
            c = np.bincount(v >> (n - h), ww, 1 << h)
            self.head[self.head_off[f]:self.head_off[f + 1]] = np.log((c + self.beta*q)/(ww.sum() + self.beta))
        return self

    def field_index(self, sites):
        import numpy as np
        i = np.searchsorted(self.keys, sites)
        i = np.minimum(i, len(self.keys) - 1)
        return np.where(self.keys[i] == sites, i, -1)

    def marginal_lp(self, sites, values):
        """log P(v) per entry (nan for unknown fields / non-bit kinds)."""
        import numpy as np
        f = self.field_index(sites)
        out = np.full(len(sites), np.nan)
        ok = f >= 0
        fi, v = f[ok], values[ok].astype(np.int64)
        n, h = self.nb[fi], self.h[fi]
        lp = self.head[self.head_off[fi] + (v >> (n - h))]
        low = n - h
        for k in np.flatnonzero(low > 0):
            ff, nn, hh = fi[k], n[k], h[k]
            bits = (v[k] >> np.arange(nn - hh - 1, -1, -1)) & 1
            lp[k] += self.bitlp[ff][hh + np.arange(nn - hh), bits].sum()
        out[ok] = lp
        return out

    # -- neighbours -------------------------------------------------------------
    def fit_neighbour(self, lag, sites, values, ref_values):
        """Pairs (field site, value at t, value at t - lag) with matching occurrence."""
        import numpy as np
        f = self.field_index(sites)
        ok = f >= 0
        f, v, u = f[ok], values[ok].astype(np.int64), ref_values[ok].astype(np.int64)
        tabs = {}
        for ff in np.unique(f):
            sel = f == ff
            n = int(self.nb[ff])
            if n > HEAD_BITS or sel.sum() < 30:
                continue
            vv, uu = v[sel], u[sel]
            pm = np.exp(self.head[self.head_off[ff]:self.head_off[ff + 1]])
            if n <= SMALL_BITS:
                c = np.zeros((1 << n, 1 << n))
                np.add.at(c, (uu, vv), 1.0)
                cond = (c + self.beta_nb*pm[None, :])/(c.sum(1, keepdims=True) + self.beta_nb)
                tabs[int(ff)] = ('cond', np.log(cond))
            else:
                d = vv - uu + (1 << n) - 1
                hist = np.bincount(d, minlength=2*(1 << n) - 1) + 0.1
                hist = hist/hist.sum()
                lam = 0.5
                a, b = hist[d], pm[vv]
                for _ in range(30):
                    r = lam*a/(lam*a + (1 - lam)*b)
                    lam = float(np.clip(r.mean(), 1e-3, 0.999))
                tabs[int(ff)] = ('mix', lam, np.log(hist))
        if not hasattr(self, 'nbtab'):
            self.nbtab = {}
        self.nbtab[lag] = tabs
        return tabs

    def neighbour_llr(self, lag, sites, values, ref_values):
        """log P(v | v_ref) - log P(v) per entry (0 where no model)."""
        import numpy as np
        out = np.zeros(len(sites))
        tabs = self.nbtab.get(lag, {})
        f = self.field_index(sites)
        for ff in np.unique(f[f >= 0]):
            t = tabs.get(int(ff))
            if t is None:
                continue
            sel = np.flatnonzero(f == ff)
            v, u = values[sel].astype(np.int64), ref_values[sel].astype(np.int64)
            n = int(self.nb[ff])
            lpm = self.head[self.head_off[ff] + v]
            if t[0] == 'cond':
                out[sel] = t[1][u, v] - lpm
            else:
                lam, lh = t[1], t[2]
                out[sel] = np.logaddexp(np.log(lam) + lh[v - u + (1 << n) - 1], np.log(1 - lam) + lpm) - lpm
        return out



def load_corpus(path):
    import numpy as np
    c = dict(np.load(path))
    return c


def occurrence_pairs(row, site, occ, value):
    """Entries matched to the previous occurrence of the same site word in the same frame.
    Returns (index of entry, value of the previous occurrence) for entries with occ >= 1."""
    import numpy as np
    key = row.astype(np.int64)*(1 << 48) + (site.astype(np.int64) << 16) + occ.astype(np.int64)
    o = np.argsort(key)
    idx = np.flatnonzero(occ >= 1)
    q = key[idx] - 1
    i = np.minimum(np.searchsorted(key[o], q), len(o) - 1)
    hit = key[o][i] == q
    return idx[hit], value[o][i][hit]


def corpus_subset(c, rows_mask):
    """Corpus restricted to the frames rows_mask (bool over frames)."""
    import numpy as np
    keep = rows_mask[c['e_row']]
    newrow = -np.ones(len(rows_mask), np.int64)
    newrow[rows_mask] = np.arange(rows_mask.sum())
    out = {k: (v[keep] if k.startswith('e_') else v[rows_mask]) for k, v in c.items()}
    out['e_row'] = newrow[c['e_row'][keep]]
    return out


def corpus_pairs(c, lag):
    """Entries of frame t matched (site, occ) to frame t - lag of the same stream.
    Returns (site, value, ref_value, row) arrays."""
    import numpy as np
    stream, frame = c['stream'].astype(np.int64), c['frame'].astype(np.int64)
    fkey = stream*10**7 + frame
    order = np.argsort(fkey)
    pos = np.searchsorted(fkey[order], fkey - lag)
    pos = np.minimum(pos, len(order) - 1)
    ref_row = np.where(fkey[order][pos] == fkey - lag, order[pos], -1)
    row, site, occ, val = c['e_row'], c['e_site'], c['e_occ'].astype(np.int64), c['e_value']
    rr = ref_row[row]
    key = row.astype(np.int64)*0 + (site.astype(np.int64) << 16) + occ
    # join (ref_row, site, occ) against (row, site, occ)
    ek = row.astype(np.int64)*(1 << 48) + key
    o = np.argsort(ek)
    q = rr.astype(np.int64)*(1 << 48) + key
    i = np.minimum(np.searchsorted(ek[o], q), len(o) - 1)
    hit = (rr >= 0) & (ek[o][i] == q)
    return site[hit], val[hit], val[o][i][hit], row[hit]



# ---------------------------------------------------------------------------
# decoded-value continuity scales
# ---------------------------------------------------------------------------
V_LSF = slice(0, 16)
V_PITCH = slice(16, 28)
V_IGF = slice(45, 62)
HQ_ENERGY_TAG = 1


def frame_values(c_or_logs, rows_core, vals, ent_rows=None, ent_site=None, ent_pos=None, ent_value=None):
    """Per-row decoded vectors: lsf (16), pitch of the current frame's subframes (5, nan pad),
    igf (17), hq band energy indices (up to 20, nan pad)."""
    import numpy as np
    R = len(rows_core)
    lsf = vals[:, V_LSF].astype(np.float64)
    pb = vals[:, V_PITCH].astype(np.float64)
    pitch = np.full((R, 5), np.nan)
    # 12.8 kHz core: 4 subframes at [4:8]; 16 kHz core: 5 at [5:10]; unknown -> take [4:8]
    pitch[:, :4] = pb[:, 4:8]
    igf = vals[:, V_IGF].astype(np.float64)
    hq = np.full((R, 20), np.nan)
    if ent_rows is not None:
        sel = (ent_site == ((KIND_VALUE << 29) | HQ_ENERGY_TAG)) & (ent_pos < 20)
        hq[ent_rows[sel], ent_pos[sel]] = ent_value[sel]
    return dict(lsf=lsf, pitch=pitch, igf=igf, hq=hq)


def value_deltas(fv, rows, ref_rows, core, ref_core):
    """Signed differences of decoded vectors between rows and their reference rows,
    only where both frames have the same core (nan otherwise)."""
    import numpy as np
    out = {}
    same = core == ref_core
    for k, cores in (('lsf', (0, 1)), ('pitch', (0,)), ('igf', (1,)), ('hq', (3,))):
        d = fv[k][rows] - fv[k][ref_rows]
        ok = same & np.isin(core, cores)
        d[~ok] = np.nan
        out[k] = d
    return out



# ---------------------------------------------------------------------------
# per-candidate features of one target byte
# ---------------------------------------------------------------------------
FAMILIES = (('A', 0), ('T', 1), ('H', 3))
BASE_FEATURES = ('marg', 'nb', 'unseen', 'flag', 'nbp', 'lsf', 'pitch', 'igf', 'hq', 'occ')
FEATURES = tuple('%s_%s' % (f, fam) for fam, _ in FAMILIES for f in BASE_FEATURES)
REF_ORDER = (1, -1, 2, -2, 3, -3)


def reference_frames(role, good_row, fully_known_roles, max_lag=3):
    """{frame f of `role`: [(f_ref, lag), ...]}: the nearest decoded frame of a fully known
    role before f and the nearest after f, each within max_lag frames (lag = f - f_ref)."""
    out = {}
    for f in range(role, len(good_row), 4):
        refs = []
        for side in (1, -1):
            for dist in range(1, max_lag + 1):
                fr = f - side*dist
                if 0 <= fr < len(good_row) and good_row[fr] and (fr % 4) in fully_known_roles:
                    refs.append((fr, side*dist))
                    break
        if refs:
            out[f] = refs
    return out


def item_features(model, scales, res, good, role, j, unknown_other, detail=False):
    """Feature matrix (K, len(FEATURES)) for the K candidates of byte (role, j).

    res: EvalResult of the candidates (PCM = parameter records); good (K, N) decode flags;
    unknown_other: mask byte indices of `role` (other than j) whose value is still unknown
    (their bits are garbage; entries overlapping them are ignored)."""
    import numpy as np
    K, N = res.diag.shape
    fully_known = [r for r in range(4) if r != role and good[0, r::4].any()]
    refs = reference_frames(role, good[0], fully_known)
    frames = [f for f in range(role, N, 4) if good[0, f]]
    X = np.zeros((K, len(FEATURES)))
    if not frames:
        return X
    lo_j, hi_j = keyed_range(j)
    nxt = min([keyed_range(u)[0] for u in unknown_other if u > j] + [FRAME_BITS])
    cols = frames + sorted({fr for f in frames for fr, _ in refs.get(f, [])})
    C = len(cols)
    colidx = {f: i for i, f in enumerate(cols)}
    L = parse_logs(res.pcm[:, cols].reshape(K*C, -1))
    R = K*C
    diag = res.diag[:, cols].reshape(R)
    core = diag['core'].astype(np.int64)
    row = L['row']
    site, pos, val, occ = L['site'], L['pos'], L['value'], L['occ'].astype(np.int64)
    kind, nb = L['kind'], L['nbits'].astype(np.int64)
    cand_of_row = np.arange(R)//C
    col_of_row = np.arange(R) % C
    target_cols = np.array([colidx[f] for f in frames])
    is_target_row = np.isin(col_of_row, target_cols)
    # entry selection: bit reads of target frames that do not touch another unknown byte and
    # start before the next unknown byte
    bitk = (kind < 4) & (nb > 0)
    end = pos + nb
    ov_other = np.zeros(len(pos), bool)
    for u in unknown_other:
        lo, hi = keyed_range(u)
        ov_other |= (pos < hi) & (end > lo)
    sel = bitk & is_target_row[row] & ~ov_other & (pos < nxt) & (end > lo_j - 16)
    sidx = np.flatnonzero(sel)
    srow = row[sidx]
    lp = model.marginal_lp(site[sidx], val[sidx])
    unseen = np.isnan(lp)
    llr = np.where(unseen, 0.0, lp + nb[sidx]*np.log(2))
    # neighbour LLR over every (target frame, reference frame) link of the same candidate
    key_all = row.astype(np.int64)*(1 << 48) + (site.astype(np.int64) << 16) + occ
    o = np.argsort(key_all)
    sorted_keys = key_all[o]
    gain = np.zeros(len(sidx))
    links = [(colidx[f], colidx[fr], lag) for f in frames for fr, lag in refs.get(f, [])]
    for tc, rc, lag in links:
        m = col_of_row[srow] == tc
        if not m.any():
            continue
        e = sidx[m]
        rr = cand_of_row[row[e]]*C + rc
        q = rr.astype(np.int64)*(1 << 48) + (site[e].astype(np.int64) << 16) + occ[e]
        ii = np.minimum(np.searchsorted(sorted_keys, q), len(o) - 1)
        hit = sorted_keys[ii] == q
        if hit.any():
            g = np.zeros(len(e))
            g[hit] = model.neighbour_llr(int(lag), site[e][hit], val[e][hit], val[o][ii][hit])
            gain[m] += g
    # within-frame previous occurrence of the same site
    oi, ov = occurrence_pairs(row, site, occ, val)
    occ_prev = np.full(len(row), -1, np.int64)
    occ_prev[oi] = ov
    has = occ_prev[sidx] >= 0
    occ_gain = np.zeros(len(sidx))
    if has.any():
        occ_gain[has] = model.neighbour_llr('occ', site[sidx][has], val[sidx][has], occ_prev[sidx][has])
    # decoded values against each reference frame (concealed candidate frames excluded)
    fv = frame_values(None, core, L['vals'], row, site, pos, val)
    vrow, vfeat = [], {k: [] for k in ('lsf', 'pitch', 'igf', 'hq')}
    for tc, rc, lag in links:
        trows = np.arange(K)*C + tc
        rrows = np.arange(K)*C + rc
        dl = value_deltas(fv, trows, rrows, core[trows], core[rrows])
        concealed = diag['bfi_out'][trows] > 0
        for k, dd in dl.items():
            dd = dd.copy()
            dd[concealed] = np.nan
            vfeat[k].append(value_llr(scales, k, lag, dd))
        vrow.append(trows)
    vrow = np.concatenate(vrow) if vrow else np.zeros(0, np.int64)
    vfeat = {k: (np.concatenate(v) if v else np.zeros(0)) for k, v in vfeat.items()}
    flag = (diag['bfi_out'] > 0).astype(float) + (diag['ber_detect'] > 0)
    nbp = (diag['next_bit_pos'] != diag['nbits']).astype(float)
    for fi, (fam, c) in enumerate(FAMILIES):
        base = fi*len(BASE_FEATURES)
        famrow = core == c
        m = famrow[srow]
        cr = cand_of_row[srow[m]]
        X[:, base + 0] = np.bincount(cr, llr[m], K)
        X[:, base + 1] = np.bincount(cr, gain[m], K)
        X[:, base + 2] = np.bincount(cr, unseen[m], K)
        X[:, base + 9] = np.bincount(cr, occ_gain[m], K)
        tr = is_target_row & famrow
        X[:, base + 3] = np.bincount(cand_of_row[tr], flag[tr], K)
        X[:, base + 4] = np.bincount(cand_of_row[tr], nbp[tr], K)
        mv = famrow[vrow]
        for k2, name in ((5, 'lsf'), (6, 'pitch'), (7, 'igf'), (8, 'hq')):
            X[:, base + k2] = np.bincount(cand_of_row[vrow[mv]], vfeat[name][mv], K)
    if detail:
        return X, dict(cand=cand_of_row[srow], addr=L['addr'][sidx], core=core[srow], llr=llr,
                       gain=gain, occ=occ_gain, unseen=unseen)
    return X


def value_tables(c, lags=(1, 2, 3), bins=24, seed=0):
    """Per decoded component: log-density ratio of the lag difference between consecutive
    clear frames and between random frames of the same core (histogram on symmetric bins).
    Returns {(name, |lag|): (edges (C, bins+1), llr (C, bins))}."""
    import numpy as np
    rng = np.random.default_rng(seed)
    stream, frame = c['stream'].astype(np.int64), c['frame'].astype(np.int64)
    fkey = stream*10**7 + frame
    order = np.argsort(fkey)
    core = c['d_core'].astype(np.int64)
    fv = frame_values(None, core, c['vals'], c['e_row'], c['e_site'], c['e_pos'], c['e_value'])
    out = {}
    for lag in lags:
        pos = np.minimum(np.searchsorted(fkey[order], fkey - lag), len(order) - 1)
        ref = np.where(fkey[order][pos] == fkey - lag, order[pos], -1)
        rows = np.flatnonzero(ref >= 0)
        dl = value_deltas(fv, rows, ref[rows], core[rows], core[ref[rows]])
        # random same-core partner
        rnd = np.empty(len(rows), np.int64)
        for cr in np.unique(core):
            m = core[rows] == cr
            pool = np.flatnonzero(core == cr)
            rnd[m] = pool[rng.integers(0, len(pool), m.sum())]
        dr = value_deltas(fv, rows, rnd, core[rows], core[rnd])
        for name in dl:
            C = dl[name].shape[1]
            edges = np.full((C, bins + 1), np.inf)
            llr = np.zeros((C, bins))
            for k in range(C):
                a, b = dl[name][:, k], dr[name][:, k]
                a, b = a[np.isfinite(a)], b[np.isfinite(b)]
                if len(a) < 200 or np.all(a == 0):
                    continue
                q = np.unique(np.quantile(np.abs(np.r_[a, b]), np.linspace(0, 1, bins//2 + 1)[1:-1]))
                e = np.r_[-np.inf, -q[::-1], q, np.inf] if q[0] > 0 else np.r_[-np.inf, -q[:0:-1], q, np.inf]
                e = np.unique(e)
                nb = len(e) - 1
                ca = np.histogram(a, e)[0] + 0.5
                cb = np.histogram(b, e)[0] + 0.5
                edges[k, :nb + 1] = e
                edges[k, 0] = -np.inf
                llr[k, :nb] = np.log(ca/ca.sum()) - np.log(cb/cb.sum())
            out[(name, lag)] = (edges, llr)
    return out


def value_llr(tables, name, lag, d):
    """Sum over components of the lag-difference LLR (nan components contribute 0)."""
    import numpy as np
    t = tables.get((name, abs(int(lag))))
    if t is None:
        return np.zeros(len(d))
    edges, llr = t
    out = np.zeros(len(d))
    for k in range(min(d.shape[1], edges.shape[0])):
        x = d[:, k]
        ok = np.isfinite(x)
        if not ok.any() or not np.isfinite(edges[k, 1]):
            continue
        e = edges[k][np.isfinite(edges[k])]
        b = np.clip(np.searchsorted(e, x[ok], side='right'), 0, len(e))
        # interior edges e: bin index b in [0, len(e)]
        out[ok] += llr[k, b]
    return out


def train_model(out=WORK/'model.pkl', syn=WORK/'corpus_syn.npz', real=(WORK/'corpus_dev_role0.npz',),
                real_weight=1.0):
    """Fit the FieldModel (marginals: clear synthetic + real role-0 frames; neighbours and
    value scales: consecutive clear synthetic frames) and pickle it."""
    import pickle
    import numpy as np
    cs = load_corpus(syn)
    held = [i for i, src in enumerate(TRAIN_SOURCES) if src['name'] in OWN_ITEM_STREAMS]
    cs = corpus_subset(cs, ~np.isin(cs['stream'], held))
    cr = [load_corpus(r) for r in real]
    fm = FieldModel()
    sites = np.concatenate([cs['e_site']] + [c['e_site'] for c in cr])
    vals = np.concatenate([cs['e_value']] + [c['e_value'] for c in cr])
    w = np.concatenate([np.ones(len(cs['e_site']))] + [np.full(len(c['e_site']), real_weight) for c in cr])
    fm.fit_marginal(sites, vals, w)
    for lag in LAGS:
        st, v, u, _ = corpus_pairs(cs, lag)
        fm.fit_neighbour(lag, st, v, u)
    oi, ov = occurrence_pairs(np.concatenate([cs['e_row']] + [c['e_row'] + 10**8*(k + 1) for k, c in enumerate(cr)]),
                              sites, np.concatenate([cs['e_occ']] + [c['e_occ'] for c in cr]), vals)
    fm.fit_neighbour('occ', sites[oi], vals[oi], ov)
    scales = value_tables(cs)
    with open(out, 'wb') as f:
        pickle.dump(dict(model=fm, scales=scales, syn=str(syn), real=[str(r) for r in real],
                         real_weight=real_weight), f)
    return out



# ---------------------------------------------------------------------------
# prediction driver
# ---------------------------------------------------------------------------
def select_groups(d, groups=None, seed=0, exclude=()):
    """Target groups (labelled, with at least one target, group id not in `exclude`),
    optionally a seeded random subset."""
    import numpy as np
    cand = np.flatnonzero(d['labelled'] & d['target'].any(1) & ~np.isin(d['group_id'], list(exclude)))
    if groups and groups < len(cand):
        rng = np.random.default_rng(seed)
        cand = np.sort(rng.choice(cand, groups, replace=False))
    return cand


def target_order(target_row):
    """(role, j) targets of one group in solving order: roles 0..3, bytes in bitstream order."""
    import numpy as np
    idx = np.flatnonzero(np.asarray(target_row).reshape(-1))
    return [(int(i)//11, int(i) % 11) for i in idx]


def warm_frames(d, g, visible_only=True):
    """(frames, good) of group g with visible bytes removed and every role with an unknown
    visible byte erased (the committed context for the following group)."""
    import numpy as np
    from evs_candidates import unmask_group
    mask, known = visible_mask(d['known'][g])
    fr = unmask_group(d['frames'][g], mask, known)
    gd = d['present'][g].copy()
    for r in range(4):
        if not known[r].all():
            gd[r::4] = False
    return fr, gd


def predict(inputs, out, groups=None, seed=0, model_path=WORK/'model.pkl', weights=None,
            jobs=2, warm=2, features_out=None, log=print, control=None, exclude=(), unerase=False,
            limit=None):
    """Predict every target byte of the selected groups.  Returns the predictions dict.

    unerase: when scoring role r, frames of roles whose bytes are all visible OR already
    estimated (earlier roles of the same group) are decoded instead of erased, so they act as
    decoder context and reference frames (their estimated bytes may be wrong).
    control='wrong-group': every target group is scored with the received frames (and
    present flags) of another target group half the selected list away, keeping its own
    visible mask bytes and decoder warm-up (the signal must disappear)."""
    import pickle
    import numpy as np
    from evs_candidates import role_byte_candidates
    d = np.load(inputs)
    with open(model_path, 'rb') as f:
        mdl = pickle.load(f)
    model, scales = mdl['model'], mdl['scales']
    w = np.asarray(weights if weights is not None else default_weights(), float)
    chosen = select_groups(d, groups, seed, exclude)
    if limit:
        chosen = chosen[:limit]
    swap = {int(g): int(chosen[(i + len(chosen)//2) % len(chosen)]) for i, g in enumerate(chosen)}
    run = d['run_id']
    dec = open_decoder(jobs)
    rec = dict(group=[], role=[], j=[], logp=[], X=[], fam=[])
    t0 = time.time()
    done = 0
    prev_g = None
    for gi, g in enumerate(chosen):
        g = int(g)
        # context: reset, then commit up to `warm` preceding groups of the same run
        start = g
        while start > 0 and run[start - 1] == run[g] and g - start < warm:
            start -= 1
        if prev_g is not None and run[prev_g] == run[g] and start <= prev_g + 1 <= g:
            first = prev_g + 1          # continue from the committed state
        else:
            dec.reset(RATE)
            first = start
        for h in range(first, g):
            fr, gd = warm_frames(d, h)
            dec.feed(fr, gd)
        mask, known = visible_mask(d['known'][g])
        est = mask.copy()
        est_known = known.copy()
        erase = [r for r in range(4) if not known[r].all()]
        src = swap[g] if control == 'wrong-group' else g
        for role, j in target_order(d['target'][g]):
            erase_now = [r for r in erase if r != role and not (unerase and est_known[r].all())]
            cands, good = role_byte_candidates(d['frames'][src], est, est_known, role, j,
                                               good=d['present'][src], erase_roles=erase_now)
            N = max(f for f in range(60) if f % 4 == role) + 1
            res = dec.eval(cands[:, :N], good[:, :N])
            unknown_other = [u for u in range(11) if u != j and not est_known[role, u]]
            X = item_features(model, scales, res, good[:, :N], role, j, unknown_other)
            s_ = X @ w
            logp = s_ - np.logaddexp.reduce(s_)
            est[role, j] = int(np.argmax(logp))
            est_known[role, j] = True
            rec['group'].append(str(d['group_id'][g]))
            rec['role'].append(role)
            rec['j'].append(j)
            rec['logp'].append(logp.astype(np.float32))
            rec['X'].append(X.astype(np.float32))
            core0 = res.diag[0, role::4]['core'][good[0, role:N:4]]
            rec['fam'].append([int((core0 == c).sum()) for _, c in FAMILIES])
            done += 1
        fr, gd = warm_frames(d, g)
        dec.feed(fr, gd)
        prev_g = g
        if log and (gi % 10 == 0 or gi == len(chosen) - 1):
            log('%d/%d groups, %d items, %.1f s' % (gi + 1, len(chosen), done, time.time() - t0))
    dec.close()
    arr = dict(group=np.array(rec['group']), role=np.array(rec['role'], np.int64),
               j=np.array(rec['j'], np.int64), logp=np.array(rec['logp']).reshape(-1, 256))
    if out:
        np.savez_compressed(out, **arr)
    if features_out:
        np.savez_compressed(features_out, X=np.array(rec['X']).reshape(-1, 256, len(FEATURES)),
                            names=np.array(FEATURES), fam=np.array(rec['fam'], np.int16).reshape(-1, 3), **arr)
    return arr


def default_weights():
    import numpy as np
    w = np.zeros(len(FEATURES))
    for i, name in enumerate(FEATURES):
        base = name.split('_')[0]
        w[i] = dict(marg=1.0, nb=1.0, unseen=-1.0, flag=-1.0, nbp=-0.5, lsf=0.3, pitch=0.5,
                    igf=0.5, hq=0.5, occ=1.0)[base]
    return w



# ---------------------------------------------------------------------------
# own synthetic items (benchmark format) from held-out training streams
# ---------------------------------------------------------------------------
OWN_ITEM_STREAMS = ('wjs-13-cuckoos', 'librivox-ko-hyun-03')   # never used by the field model
OWN_DIR = WORK/'own'


def make_own_items(seed=20261128, out=OWN_DIR):
    """inputs/truth npz files in the benchmark format for tasks T1 and TH, made from the
    OWN_ITEM_STREAMS clear streams with an independent uniform random 44-byte mask per group."""
    import numpy as np
    from evs_candidates import apply_role_mask
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(seed)
    frames, gid, run = [], [], []
    for sid, name in enumerate(OWN_ITEM_STREAMS):
        fr = np.load(TRAIN_DIR/(name + '.npz'))['frames']
        ng = len(fr)//60
        frames.append(fr[:ng*60].reshape(ng, 60, 33))
        gid += ['own-%s-%04d' % (name, k) for k in range(ng)]
        run += [sid]*ng
    plain = np.concatenate(frames)
    G = len(plain)
    mask = rng.integers(0, 256, (G, 44)).astype(np.int16)
    mask[:, 43] = 0
    cipher = plain.copy()
    for g in range(G):
        for m in range(43):
            cipher[g] = apply_role_mask(cipher[g], m//11, m % 11, mask[g, m])
    tasks = dict(T1=(list(range(11)) + [43], list(range(11, 16))),
                 TH=(list(range(16)) + [43], list(range(16, 43))))
    for task, (vis, tgt) in tasks.items():
        known = -np.ones((G, 44), np.int16)
        known[:, vis] = mask[:, vis]
        target = np.zeros((G, 44), bool)
        target[:, tgt] = True
        common = dict(format='kcbs-mask-task/1', split='own', task=task, group_id=np.array(gid),
                      capture=np.array([OWN_ITEM_STREAMS[r] for r in run]))
        np.savez_compressed(out/('own.%s.inputs.npz' % task), counters=np.arange(G, dtype=np.uint32),
                            run_id=np.array(run, np.int32), frames=cipher, present=np.ones((G, 60), bool),
                            known=known, target=target, labelled=np.ones(G, bool), **common)
        np.savez_compressed(out/('own.%s.truth.npz' % task), target=target, truth=mask,
                            truth_source=np.full((G, 44), 5, np.int8), strict=np.ones(G, bool), **common)
    return out



# ---------------------------------------------------------------------------
# conditional-logit weights (fitted on items with known truth: own synthetic, DEV)
# ---------------------------------------------------------------------------
def load_feature_items(feat_path, truth_path):
    """(X (n, 256, D), y (n,), role, j, group) of a features file joined to its truth."""
    import numpy as np
    fe = np.load(feat_path)
    t = np.load(truth_path)
    gid = {g: i for i, g in enumerate(t['group_id'])}
    y = np.array([t['truth'][gid[g], 11*r + j] for g, r, j in zip(fe['group'], fe['role'], fe['j'])])
    return fe['X'].astype(np.float64), y.astype(np.int64), fe['role'], fe['j'], fe['group']


def fit_logit(X, y, l2=1.0, w0=None):
    """Conditional logit over the 256 candidates of each item: w minimising
    -sum log softmax(X_i w)[y_i] + l2 |w / s|^2 (s = feature scale)."""
    import numpy as np
    from scipy.optimize import minimize
    n, K, D = X.shape
    Xc = X - X.mean(1, keepdims=True)
    s = Xc.reshape(-1, D).std(0)
    s[s == 0] = 1.0
    Z = Xc/s
    Zy = Z[np.arange(n), y]

    def f(v):
        sc = Z @ v
        m = sc.max(1, keepdims=True)
        e = np.exp(sc - m)
        Zs = e.sum(1)
        lse = np.log(Zs) + m[:, 0]
        p = e/Zs[:, None]
        loss = (lse - sc[np.arange(n), y]).sum() + l2*(v @ v)
        grad = np.einsum('nk,nkd->d', p, Z) - Zy.sum(0) + 2*l2*v
        return loss, grad
    v0 = np.zeros(D) if w0 is None else np.asarray(w0)*s
    r = minimize(f, v0, jac=True, method='L-BFGS-B', options=dict(maxiter=500))
    return r.x/s, r.fun/n


WEIGHTS = WORK/'weights.json'


def load_weights(path=WEIGHTS):
    """Frozen conditional-logit weights {feature: weight}; default_weights() if absent."""
    import numpy as np
    path = Path(path)
    if not path.exists():
        return default_weights()
    wd = json.loads(path.read_text())['weights']
    return np.array([wd.get(f, 0.0) for f in FEATURES])


UNUSED_FEATURES = ('unseen',)   # unstable sign between data sets, no effect in DEV ablation


def fit_weights(pairs, out=WEIGHTS, l2=1.0):
    """Fit the conditional-logit weights on feature files with truth and save them.
    pairs: [(features npz, truth npz), ...] (truth is only read here, never when predicting)."""
    import numpy as np
    Xs, ys = [], []
    for fp, tp in pairs:
        X, y, *_ = load_feature_items(fp, tp)
        Xs.append(X)
        ys.append(y)
    X, y = np.concatenate(Xs), np.concatenate(ys)
    use = np.array([f.split('_')[0] not in UNUSED_FEATURES for f in FEATURES])
    w = np.zeros(len(FEATURES))
    w[use], loss = fit_logit(X[:, :, use], y, l2=l2)
    rec = dict(weights={f: float(v) for f, v in zip(FEATURES, w)}, l2=l2, items=int(len(y)),
               mean_nll_nats=float(loss), fitted_on=[dict(features=str(fp), truth=str(tp)) for fp, tp in pairs])
    Path(out).write_text(json.dumps(rec, indent=2))
    return rec


def write_freeze(out=WORK/'freeze.json', extra=None):
    """Freeze record: hashes of this script, the instrumented decoder, model and weights,
    the git HEAD, the parameters and the data each artefact was trained / tuned on."""
    rec = dict(method='params', created=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
               script=str(Path(__file__).relative_to(ROOT)), script_sha256=_sha(__file__),
               git_head=subprocess.run(['git', '-C', str(ROOT), 'rev-parse', 'HEAD'],
                                       capture_output=True, text=True).stdout.strip(),
               decoder=json.loads((BUILD/'build.json').read_text()) if (BUILD/'build.json').exists() else None,
               model=str(WORK/'model.pkl'), model_sha256=_sha(WORK/'model.pkl'),
               weights=str(WEIGHTS), weights_sha256=_sha(WEIGHTS) if WEIGHTS.exists() else None,
               weights_content=json.loads(WEIGHTS.read_text()) if WEIGHTS.exists() else None,
               parameters=dict(rate=RATE, head_bits=HEAD_BITS, small_bits=SMALL_BITS, lags=list(LAGS),
                               beta=FieldModel().beta, beta_nb=FieldModel().beta_nb, warm_groups=2,
                               jobs_default=2, features=list(FEATURES)),
               training_streams=json.loads((TRAIN_DIR/'receipt.json').read_text())
               if (TRAIN_DIR/'receipt.json').exists() else None,
               own_item_streams=list(OWN_ITEM_STREAMS))
    rec.update(extra or {})
    Path(out).write_text(json.dumps(rec, indent=2))
    return rec


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--inputs', help='<split>.<task>.inputs.npz (never a truth file)')
    ap.add_argument('--out', help='predictions npz (group, role, j, logp)')
    ap.add_argument('--groups', type=int, default=None, help='seeded random subset of target groups')
    ap.add_argument('--seed', type=int, default=0)
    ap.add_argument('--jobs', type=int, default=2, help='parallel decoder workers (default 2)')
    ap.add_argument('--model', default=str(WORK/'model.pkl'))
    ap.add_argument('--weights', default=str(WEIGHTS))
    ap.add_argument('--features', default=None, help='also save the per-candidate feature tensors')
    ap.add_argument('--control', choices=['none', 'wrong-group'], default='none')
    ap.add_argument('--exclude', default=None,
                    help='npz/txt of group ids to leave out (e.g. the groups the weights were fitted on)')
    ap.add_argument('--build', action='store_true', help='build the instrumented decoder')
    ap.add_argument('--make-train', action='store_true', help='download + encode the clear training streams')
    ap.add_argument('--make-corpora', action='store_true',
                    help='decode clear corpora (training streams; DEV role-0 frames)')
    ap.add_argument('--train', action='store_true', help='fit the field model (model.pkl)')
    ap.add_argument('--fit-weights', nargs='+', metavar='FEATURES.npz:TRUTH.npz',
                    help='fit the conditional-logit weights (writes --weights)')
    ap.add_argument('--l2', type=float, default=1.0)
    a = ap.parse_args(argv)
    if a.build:
        print(json.dumps(build(), indent=2))
    if a.make_train:
        make_train_streams()
    if a.make_corpora:
        corpus_train_streams()
        corpus_role0(ROOT/'work/benchmark/tasks/dev.T1.inputs.npz', WORK/'corpus_dev_role0.npz')
    if a.train:
        train_model(a.model)
    if a.fit_weights:
        rec = fit_weights([tuple(x.split(':')) for x in a.fit_weights], a.weights, a.l2)
        print(json.dumps({k: rec[k] for k in ('items', 'mean_nll_nats')}))
    if a.inputs:
        if 'truth' in Path(a.inputs).name:
            raise SystemExit('refusing to read a truth file')
        exclude = ()
        if a.exclude:
            import numpy as np
            exclude = (np.load(a.exclude)['group'].tolist() if a.exclude.endswith('.npz')
                       else Path(a.exclude).read_text().split())
        predict(a.inputs, a.out, groups=a.groups, seed=a.seed, model_path=a.model, exclude=exclude,
                weights=load_weights(a.weights), jobs=a.jobs, features_out=a.features,
                control=None if a.control == 'none' else a.control,
                log=lambda m: print(m, flush=True))


if __name__ == '__main__':
    main()
