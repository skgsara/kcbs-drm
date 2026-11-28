#!/usr/bin/env python3
"""Learned discriminator for blind KCBS-2 mask-byte recovery (method 'learned-disc').

Every target mask byte (group, role r, byte j) is ranked over its 256 candidate values by a
conditional-logit model (softmax over the candidates of one item) on per-candidate features:

decoder features (expensive; variants 'dec' and 'full')
  The 256 candidates are decoded with the exact fork-snapshot EVS decoder (scripts/evs_candidates.py):
  visible mask bytes removed, candidate v XORed into frame byte 1+3j of the role-r frames, other roles
  with unknown bytes erased (role_byte_candidates defaults).  Before each target group the decoder is
  reset and fed the WARM_GROUPS preceding groups of the run in best-known form, so features do not
  depend on which other groups are processed.  Per role frame: bfi, BER, bit-position surplus/deficit,
  clipping, peak, agreement of decoded core / coder type / bandwidth / extension layer / class with the
  across-candidate modal value, and from the 16 kHz PCM: energy, 8-band log spectrum, flatness,
  high-band share, second-difference clicks at frame boundaries, energy / spectral jumps against the
  neighbouring and nearest clear frames.  Summed over the role's received frames separately for
  ACELP, TCX20 and HQ frames (family from the clear mode byte), plus maxima and the ModePrior
  log-probability ('prior_logp', eval_mask_predictions.ModePrior, DEV items use the other capture).

bitstream prior features (cheap; every variant)
  mode_prior         per (exact mode byte, j, bit) marginal of the clear byte (DEV role 0 + role-1 j<5)
  ctx_{L,R}{W}       intra-frame bit context: P(bit | mode byte, j, bit, W preceding (L) / following (R)
                     stream bits, which include the clear neighbouring payload bytes), DEV plaintext
  sctx_*             the same counted on syn-dev plaintext (truth of syn-dev T0+T1+TH)
  ifP_*, ifN_*       inter-frame bit model: P(bit | mode byte, same-mode flag, the same bit of the
                     nearest earlier (P) / later (N) frame within the group whose byte j is visible)
  Tables are counted per cross-fit unit (DEV capture, syn-dev source fold); an item never uses the
  counts of its own unit.

Model: linear terms on item-centred standardised features, item z-scores and within-item ranks of
the prior scores, plus a one-hidden-layer MLP that also sees item context (role, j, mode-class mix,
reference distances).  Decoder features enter the linear part once per byte-position group
(j = 0 | 1-2 | 3-10) and are kept out of the MLP (dec_mode 'jgroup_linear'), because they only carry
evidence at j = 0 and otherwise add noise.  Trained by cross-entropy on DEV (T1, T0) and syn-dev
(TH, T1, T0); temperature-calibrated on held-out groups.  Every DEV / syn-dev item is predicted by a
model whose training set excluded its capture (real) or source fold (synthetic); any other split
uses the model trained on everything.  Predictions never read truth.

Usage
  predict (default):
    mask_method_learned_disc.py --inputs work/benchmark/tasks/dev.T1.inputs.npz --out P.npz
        [--groups N --seed S] [--model M.npz] [--features F.npz (decoder feature cache)]
        [--control wrong-group|shift-role]
  extract decoder features only:
    mask_method_learned_disc.py extract --inputs X --out F.npz [--groups N --seed S] [--control wrong-group]
  train (reads DEV / syn-dev truth, which protocol rule 2 allows):
    mask_method_learned_disc.py train --variant ctx|dec|full --data dev.T1 dev.T0 syn-dev.TH ... \
        [--dec F1.npz F2.npz ...] --out M.npz [--oof-out O.npz] [--importance]
"""
import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))

from evs_candidates import CandidateDecoder, role_byte_candidates, unmask_group   # noqa: E402
import eval_mask_predictions as emp                                                # noqa: E402

METHOD = 'learned-disc'
WORK = ROOT/'work/methods/learned-disc'
DEFAULT_MODEL = WORK/'model.npz'
FEATURE_VERSION = 3
RATE = 16000
WARM_GROUPS = 2
ROLES = 4
NB = 11
GROUP_FRAMES = 60
FAMILIES = ('ACELP', 'TCX', 'HQ')
BAND_EDGES_HZ = (0, 300, 700, 1200, 2000, 3000, 4000, 5500, 8001)
MODE_CLASSES = (10, 11, 12, 13, 14, 19, 20, 'TCX', 'HQ')   # mode-table index or MDCT kind
CONSIST_FIELDS = ('core', 'coder_type', 'bwidth', 'extl', 'codec_mode')
#: synthetic cross-fit folds by source (the three spc160 readers share a fold)
SYN_FOLDS = {
    'librivox-en-spc160-anticipation': 0, 'librivox-en-spc160-duringmusic': 0,
    'librivox-en-spc160-withaflower': 0, 'librosa-brahms': 0, 'nov27-programme': 0,
    'librivox-ko-hyun-01': 1, 'librosa-fishin': 1,
    'wangjaesan-02-seashore': 2, 'librosa-vibeace': 2}


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


def load_npz(path):
    with np.load(path, allow_pickle=False) as d:
        return {k: d[k] for k in d.files}


def cv_unit(capture):
    """Cross-fit unit of a capture: the capture itself (real) or its source fold (synthetic)."""
    capture = str(capture)
    if capture.startswith('syn-'):
        split, source = capture.split(':', 1)
        return f'{split}:fold{SYN_FOLDS.get(source, hash_fold(source))}'
    return capture


def hash_fold(source):
    return int(hashlib.sha256(source.encode()).hexdigest(), 16) % 3


# --------------------------------------------------------------------------- groups and frames

def family_of_modes(modes):
    """0 ACELP, 1 TCX20, 2 HQ for 13.2 kbps mode bytes."""
    modes = np.asarray(modes, np.int64)
    mdct = (modes >> 3) >= 29
    return np.where(mdct, np.where(modes & 4, 1, 2), 0)


def mode_class_onehot(modes):
    modes = np.asarray(modes, np.int64)
    idx = modes >> 3
    out = np.zeros((len(modes), len(MODE_CLASSES) + 1), np.float32)
    for c, cls in enumerate(MODE_CLASSES):
        if cls == 'TCX':
            sel = (idx >= 29) & ((modes & 4) > 0)
        elif cls == 'HQ':
            sel = (idx >= 29) & ((modes & 4) == 0)
        else:
            sel = idx == cls
        out[sel, c] = 1
    out[out.sum(axis=1) == 0, -1] = 1
    return out


def best_known(inputs, g):
    """Group g with its visible mask bytes removed and roles with unknown bytes erased."""
    known = inputs['known'][g].astype(np.int64)
    kn = known >= 0
    frames = unmask_group(inputs['frames'][g], np.where(kn, known, 0).astype(np.uint8), kn)
    good = inputs['present'][g].copy()
    for r in range(ROLES):
        if not kn[NB*r:NB*(r + 1)].all():
            good[r::ROLES] = False
    return frames, good


def select_groups(inputs, n=None, seed=0):
    """Indices of groups with target cells (all, or a seeded sorted subsample of n)."""
    cand = np.flatnonzero(inputs['target'].any(axis=1))
    if n is not None and n < len(cand):
        rng = np.random.default_rng(seed)
        cand = np.sort(rng.choice(cand, size=n, replace=False))
    return cand


def donor_groups(inputs, groups):
    """Wrong-group control: for each group, another target group of the same capture
    half the capture's list of target groups away."""
    out = {}
    lab = np.flatnonzero(inputs['target'].any(axis=1))
    for cap in np.unique(inputs['capture'][lab]):
        L = lab[inputs['capture'][lab] == cap]
        for i, g in enumerate(L):
            out[int(g)] = int(L[(i + len(L)//2) % len(L)]) if len(L) > 1 else int(g)
    return np.array([out[int(g)] for g in groups])


def warm_up(dec, inputs, g):
    """Reset and feed up to WARM_GROUPS preceding groups of g's run in best-known form."""
    dec.reset(RATE)
    run = inputs['run_id'][g]
    prev = [p for p in range(g - WARM_GROUPS, g) if p >= 0 and inputs['run_id'][p] == run]
    for p in prev:
        frames, good = best_known(inputs, p)
        dec.feed(frames, good)
    return len(prev)


# --------------------------------------------------------------------------- features

def frame_descriptors(pcm):
    """Per (candidate, frame): energy, band log-energies, flatness, high-band share, clicks."""
    x = pcm.astype(np.float32)
    K, N, L = x.shape
    E = np.log10(np.mean(x*x, axis=2) + 1.0)
    spec = np.abs(np.fft.rfft(x*np.hanning(L).astype(np.float32), axis=2))**2
    hz = np.fft.rfftfreq(L, 1/RATE)
    B = np.stack([np.log10(spec[..., (hz >= lo) & (hz < hi)].sum(axis=2) + 1.0)
                  for lo, hi in zip(BAND_EDGES_HZ[:-1], BAND_EDGES_HZ[1:])], axis=2)
    sp = spec[..., 2:] + 1.0
    flat = np.mean(np.log(sp), axis=2) - np.log(np.mean(sp, axis=2))
    hf = np.log10((spec[..., hz >= 4000].sum(axis=2) + 1.0)/(spec.sum(axis=2) + 1.0))
    d2 = np.diff(x, n=2, axis=2)
    s = np.sqrt(np.mean(d2*d2, axis=2))
    click = np.zeros((K, N), np.float32)
    jump = x[:, 1:, 0] - 2*x[:, :-1, -1] + x[:, :-1, -2]
    click[:, 1:] = np.log1p(np.abs(jump)/(0.5*(s[:, 1:] + s[:, :-1]) + 1.0))
    return dict(E=E, B=B, flat=flat, hf=hf, click=click)


def clean(X):
    """Finite float32 features (the decoder reports a NaN peak for some garbage frames)."""
    return np.nan_to_num(np.asarray(X, np.float32), nan=0.0, posinf=1e4, neginf=-1e4)


def modal(a):
    """Per-column modal value of an int array (K, n)."""
    out = np.empty(a.shape[1], a.dtype)
    for i in range(a.shape[1]):
        v, c = np.unique(a[:, i], return_counts=True)
        out[i] = v[np.argmax(c)]
    return out


EVIDENCE = ('bfi', 'ber', 'mis', 'surplus', 'abs_surplus', 'clip', 'logpeak', 'dev_core',
            'dev_clas', 'dev_hq', 'clas_prev', 'E', 'dE_prev', 'adE_prev', 'adE_next',
            'SD_prev', 'SD_next', 'click_in', 'click_out', 'flat', 'hf', 'dE_clear', 'adE_clear',
            'devE_nc', 'adevE_nc', 'devB_nc', 'click_nc', 'SD_pc')
MAXED = ('click_in', 'click_out', 'SD_prev', 'SD_next', 'adE_prev', 'clip', 'devB_nc', 'abs_surplus')
FEATURE_NAMES = tuple(f'{e}|{fam}' for e in EVIDENCE for fam in FAMILIES) + \
    tuple(f'max|{e}' for e in MAXED) + ('status_bad', 'prior_logp')
CONTEXT_NAMES = tuple(f'role{r}' for r in range(ROLES)) + tuple(f'j{j}' for j in range(NB)) + \
    tuple(f'mode{c}' for c in MODE_CLASSES) + ('mode_other', 'n_role_frames', 'prev_clear',
                                                'next_clear', 'n_clear_roles')


def item_features(res, good, modes, r, clear_roles):
    """(256, F) features and (C,) context for one target from an EvalResult."""
    diag = res.diag
    K = diag.shape[0]
    R = np.array([f for f in range(r, GROUP_FRAMES, ROLES) if good[f]], np.int64)
    X = np.zeros((K, len(FEATURE_NAMES)), np.float32)
    ctx = np.zeros(len(CONTEXT_NAMES), np.float32)
    ctx[r] = 1
    ctx[len(CONTEXT_NAMES) - 4] = len(R)/15
    clear = np.zeros(GROUP_FRAMES, bool)
    for q in clear_roles:
        clear[q::ROLES] = True
    clear &= good
    ctx[-3] = float(r >= 1 and (r - 1) in clear_roles)
    ctx[-2] = float(((r + 1) % ROLES) in clear_roles)
    ctx[-1] = len(clear_roles)/3
    status_bad = res.status != 0
    X[:, FEATURE_NAMES.index('status_bad')] = status_bad
    if not len(R):
        return X, ctx
    mc = mode_class_onehot(modes[R])
    ctx[ROLES + NB:ROLES + NB + mc.shape[1]] = mc.mean(axis=0)
    fam = family_of_modes(modes[R])
    d = diag[:, R]
    ev = {}
    bfi = d['bfi_out'] > 0
    ev['bfi'] = bfi
    ev['ber'] = d['ber_detect'] > 0
    nb, nbp = d['nbits'].astype(np.float32), d['next_bit_pos'].astype(np.float32)
    ok = ~bfi & (nb > 0)
    ev['mis'] = ok & (nbp != nb)
    sur = np.clip((nbp - nb)/64.0, -2, 2)*ok
    ev['surplus'] = sur
    ev['abs_surplus'] = np.abs(sur)
    ev['clip'] = np.log1p(np.maximum(d['clip_count'], 0).astype(np.float32))
    ev['logpeak'] = np.log10(np.maximum(d['peak'], 0) + 1.0)
    dev_core = np.zeros(d.shape, np.float32)
    for name in CONSIST_FIELDS:
        dev_core += d[name] != modal(d[name])[None]
    ev['dev_core'] = dev_core
    ev['dev_clas'] = d['clas_dec'] != modal(d['clas_dec'])[None]
    ev['dev_hq'] = (d['hq_core_type'] != modal(d['hq_core_type'])[None]).astype(np.float32) + \
        (d['mdct_sw'] != modal(d['mdct_sw'])[None])
    # nearest clear frames before / after each role frame
    pc = np.full(len(R), -1)
    nc = np.full(len(R), -1)
    cl = np.flatnonzero(clear)
    for i, f in enumerate(R):
        before, after = cl[cl < f], cl[cl > f]
        pc[i] = before[-1] if len(before) else -1
        nc[i] = after[0] if len(after) else -1
    has_pc, has_nc = pc >= 0, nc >= 0
    clas = diag['clas_dec']
    ev['clas_prev'] = np.where(has_pc[None], clas[:, R] == clas[:, np.maximum(pc, 0)], 0)
    pcm_ok = res.pcm is not None
    if pcm_ok:
        D = frame_descriptors(res.pcm)
        E, B = D['E'], D['B']
        prev = np.maximum(R - 1, 0)
        nxt = np.minimum(R + 1, GROUP_FRAMES - 1)
        has_prev = (R >= 1).astype(np.float32)[None]
        has_next = (R + 1 <= GROUP_FRAMES - 1).astype(np.float32)[None]
        ev['E'] = E[:, R]
        ev['dE_prev'] = (E[:, R] - E[:, prev])*has_prev
        ev['adE_prev'] = np.abs(ev['dE_prev'])
        ev['adE_next'] = np.abs(E[:, nxt] - E[:, R])*has_next
        ev['SD_prev'] = np.sqrt(np.mean((B[:, R] - B[:, prev])**2, axis=2))*has_prev
        ev['SD_next'] = np.sqrt(np.mean((B[:, nxt] - B[:, R])**2, axis=2))*has_next
        ev['click_in'] = D['click'][:, R]*has_prev
        ev['click_out'] = D['click'][:, nxt]*has_next
        ev['flat'] = D['flat'][:, R]
        ev['hf'] = D['hf'][:, R]
        both = (has_pc & has_nc)[None]
        pcc, ncc = np.maximum(pc, 0), np.maximum(nc, 0)
        mid = 0.5*(E[:, pcc] + E[:, ncc])
        ev['dE_clear'] = np.where(both, E[:, R] - mid, 0)
        ev['adE_clear'] = np.abs(ev['dE_clear'])
        hn = has_nc[None]
        devE = E[:, ncc] - np.median(E[:, ncc], axis=0, keepdims=True)
        ev['devE_nc'] = np.where(hn, devE, 0)
        ev['adevE_nc'] = np.abs(ev['devE_nc'])
        devB = np.sqrt(np.mean((B[:, ncc] - np.median(B[:, ncc], axis=0, keepdims=True))**2, axis=2))
        ev['devB_nc'] = np.where(hn, devB, 0)
        ev['click_nc'] = np.where(hn, D['click'][:, ncc], 0)
        ev['SD_pc'] = np.where(has_pc[None], np.sqrt(np.mean((B[:, R] - B[:, pcc])**2, axis=2)), 0)
    for e in EVIDENCE:
        if e not in ev:
            continue
        v = np.asarray(ev[e], np.float32)
        for fi in range(len(FAMILIES)):
            sel = fam == fi
            if sel.any():
                X[:, FEATURE_NAMES.index(f'{e}|{FAMILIES[fi]}')] = v[:, sel].sum(axis=1)
    for e in MAXED:
        if e in ev:
            X[:, FEATURE_NAMES.index(f'max|{e}')] = np.asarray(ev[e], np.float32).max(axis=1)
    X[status_bad, :-2] = 0
    return clean(X), ctx


class Prior:
    """ModePrior from DEV role-0 plaintext; a DEV item never sees its own capture."""

    def __init__(self):
        self.mp = emp.ModePrior.fit(emp.default_prior_files())
        self.cache = {}

    def logp(self, frames, present, capture, j):
        capture = str(capture)
        if capture not in self.cache:
            self.cache[capture] = self.mp.counts_for(capture)[0]
        p = self.mp.item_probs(frames, present, int(j), self.cache[capture])
        return np.log(np.maximum(p, 1e-300))


def extract(inputs, groups, control=None, jobs=2, log=print):
    """Features for every target of the given groups.  Never reads truth."""
    prior = Prior()
    donors = donor_groups(inputs, groups) if control == 'wrong-group' else groups
    items = dict(group=[], group_id=[], capture=[], run_id=[], role=[], j=[], source_group=[])
    Xs, ctxs = [], []
    t0 = time.time()
    with CandidateDecoder(rate=RATE, jobs=jobs) as dec:
        for gi, (g, src) in enumerate(zip(groups, donors)):
            warm_up(dec, inputs, src)
            frames, present = inputs['frames'][src], inputs['present'][src]
            known = inputs['known'][src].astype(np.int64)
            kn = known >= 0
            mask = np.where(kn, known, 0).astype(np.uint8)
            targets = np.flatnonzero(inputs['target'][g])
            for m in targets:
                r, j = int(m // NB), int(m % NB)
                kn_t = kn.copy()
                kn_t[m] = False          # the donor may know this byte; treat it as unknown
                cands, good = role_byte_candidates(frames, mask, kn_t, r, j, good=present)
                res = dec.eval(cands, good, pcm=True)
                clear_roles = [q for q in range(ROLES) if q != r and kn_t[NB*q:NB*(q + 1)].all()]
                X, ctx = item_features(res, good[0], frames[:, 0], r, clear_roles)
                ctx[ROLES + j] = 1
                X[:, FEATURE_NAMES.index('prior_logp')] = prior.logp(
                    frames[r::ROLES], present[r::ROLES], inputs['capture'][g], j)
                Xs.append(X.astype(np.float32))
                ctxs.append(ctx)
                for k, v in (('group', g), ('group_id', inputs['group_id'][g]), ('capture', inputs['capture'][g]),
                             ('run_id', inputs['run_id'][g]), ('role', r), ('j', j), ('source_group', src)):
                    items[k].append(v)
            if log and (gi + 1) % 10 == 0:
                el = time.time() - t0
                log(f'  {gi + 1}/{len(groups)} groups, {len(Xs)} items, {el:.0f} s '
                    f'({el/len(Xs):.2f} s/item)', flush=True)
    out = {k: np.array(v) for k, v in items.items()}
    out['X'] = np.array(Xs, np.float32).reshape(-1, 256, len(FEATURE_NAMES))
    out['ctx'] = np.array(ctxs, np.float32).reshape(-1, len(CONTEXT_NAMES))
    return out


def features_meta(inputs_path, groups, seed, n, control):
    return dict(feature_version=FEATURE_VERSION, inputs=str(inputs_path), inputs_sha256=sha256_file(inputs_path),
                groups_requested=-1 if n is None else int(n), seed=int(seed), control=control or 'none',
                script_sha256=sha256_file(__file__), rate=RATE, warm_groups=WARM_GROUPS)


def save_features(path, feats, meta, inputs):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(path, **feats, feature_names=np.array(FEATURE_NAMES), context_names=np.array(CONTEXT_NAMES),
                        meta=json.dumps(meta), split=str(inputs['split']), task=str(inputs['task']))


# --------------------------------------------------------------------------- bitstream priors

CTX_CONFIGS = (('L', 2), ('L', 4), ('L', 6), ('L', 8), ('R', 4), ('R', 6))
SYN_CTX_CONFIGS = (('L', 4), ('L', 6), ('R', 4))
IF_DISTANCES = (1, 2, 3)
PRIOR_NAMES = ('mode_prior',) + tuple(f'ctx_{d}{w}' for d, w in CTX_CONFIGS) + \
    tuple(f'sctx_{d}{w}' for d, w in SYN_CTX_CONFIGS) + ('ifP_real', 'ifN_real', 'ifP_syn', 'ifN_syn')
CTX_ALPHA = 2.0      # context counts -> per-mode marginal
CTX_BETA = 2.0       # per-mode marginal -> all-mode marginal of (j, bit)
SYN_TRUTH_TASKS = ('T0', 'T1', 'TH')


def plaintext_sources(kind):
    """Clear groups for the bitstream priors, as dicts (unit, frames (G, 60, 33) with every known
    mask byte removed, known (G, 44), present (G, 60)).
    kind 'real': DEV label files (labelled groups: role 0 and role-1 j = 0..4), one unit per capture.
    kind 'syn' : syn-dev truth (all 43 masked bytes; protocol rule 2), one unit per source fold."""
    out = []
    if kind == 'real':
        for path in emp.default_prior_files():
            d = load_npz(path)
            known = (d['mask_label'] >= 0) & d['labelled'][:, None]
            out.append(dict(unit=cv_unit(str(d['capture'])), source=str(Path(path).resolve().relative_to(ROOT)),
                            frames=_unmask(d['frames'], d['mask_label'], known), known=known, present=d['present']))
        return out
    inputs = load_npz(inputs_path('syn-dev', 'T0'))
    mask = np.full(inputs['known'].shape, -1, np.int64)
    for task in SYN_TRUTH_TASKS:
        T = load_npz(truth_path('syn-dev', task))
        if not np.array_equal(T['group_id'], inputs['group_id']):
            raise SystemExit('syn-dev truth and inputs list different groups')
        mask = np.where(T['target'], T['truth'], mask)
    mask[:, NB*3 + 10] = 0
    known = mask >= 0
    units = np.array([cv_unit(c) for c in inputs['capture']])
    frames = _unmask(inputs['frames'], mask, known)
    for u in np.unique(units):
        sel = units == u
        out.append(dict(unit=u, source='syn-dev truth (T0, T1, TH)', frames=frames[sel], known=known[sel],
                        present=inputs['present'][sel]))
    return out


def _unmask(frames, mask, known):
    out = np.array(frames, np.uint8, copy=True)
    m = np.where(known, mask, 0).astype(np.uint8)
    for r in range(ROLES):
        out[:, r::ROLES, 1 + 3*np.arange(NB)] ^= m[:, None, NB*r:NB*(r + 1)]
    return out


def _ctx_index(dr, W, prev, c, nxt, k):
    if dr == 'L':
        return (((prev << 8) | c) >> (8 - k)) & ((1 << W) - 1)
    return (((c << 8) | nxt) >> (15 - k - W)) & ((1 << W) - 1)


def _role_frames(src):
    """(frames (n, 33), usable (n, 11)) of every present frame with its known bytes."""
    frames, usable = [], []
    for r in range(ROLES):
        fr = src['frames'][:, r::ROLES]
        ok = src['present'][:, r::ROLES][..., None] & src['known'][:, None, NB*r:NB*(r + 1)]
        keep = ok.any(axis=2)
        frames.append(fr[keep])
        usable.append(ok[keep])
    return np.concatenate(frames), np.concatenate(usable)


class ContextPrior:
    """Intra-frame bit-context models of the clear masked byte (payload byte 3j):
    P(bit k | exact mode byte, j, k, W neighbouring stream bits) for left (L, preceding bits,
    including the clear byte before it) and right (R, following bits, including the clear byte
    after it) contexts, Dirichlet-smoothed towards P(bit | mode, j, k) and P(bit | j, k).
    Counts are kept per unit; an item never uses counts of its own cross-fit unit."""

    def __init__(self, sources, configs):
        self.configs = configs
        self.counts = {src['unit']: self._count(*_role_frames(src), configs) for src in sources}
        self._tables = {}

    @staticmethod
    def _count(frames, usable, configs):
        modes = frames[:, 0].astype(np.int64)
        out = []
        for dr, W in configs:
            S = 1 << W
            C = np.zeros(256*NB*8*S*2, np.int64)
            for j in range(NB):
                sel = usable[:, j]
                prev = frames[sel, 3*j].astype(np.int64)
                c = frames[sel, 1 + 3*j].astype(np.int64)
                nxt = frames[sel, 2 + 3*j].astype(np.int64)
                for k in range(8):
                    ctx = _ctx_index(dr, W, prev, c, nxt, k)
                    b = (c >> (7 - k)) & 1
                    idx = (((modes[sel]*NB + j)*8 + k)*S + ctx)*2 + b
                    C += np.bincount(idx, minlength=len(C))
            out.append(C.reshape(256, NB, 8, S, 2).astype(np.int32))
        return out

    def tables(self, unit):
        key = unit if unit in self.counts else '*'
        if key not in self._tables:
            units = [u for u in self.counts if u != unit]
            tabs = []
            for ci in range(len(self.configs)):
                C = sum(self.counts[u][ci].astype(np.float64) for u in units)
                Njk = C.sum(axis=(0, 3)) + 1.0
                p_jk = Njk/Njk.sum(axis=-1, keepdims=True)
                Nm = C.sum(axis=3)
                p_m = (Nm + CTX_BETA*p_jk[None])/(Nm.sum(axis=-1, keepdims=True) + CTX_BETA)
                p = (C + CTX_ALPHA*p_m[:, :, :, None, :])/(C.sum(axis=-1, keepdims=True) + CTX_ALPHA)
                tabs.append(np.log(p).astype(np.float32))
            tabs.insert(0, np.log(p_m).astype(np.float32))          # (256, 11, 8, 2) mode marginal
            self._tables[key] = tabs
        return self._tables[key]

    def scores(self, frames, j, unit, with_marginal=True):
        """(256, [1 +] len(configs)) summed log-probabilities of the clear byte for every candidate
        mask value over the received frames (n, 33) of the byte's role."""
        tabs = self.tables(unit)
        lo = 0 if with_marginal else 1
        out = np.zeros((256, len(self.configs) + 1), np.float64)
        if len(frames):
            v = np.arange(256, dtype=np.int64)[None, :]
            m = frames[:, 0].astype(np.int64)[:, None]
            prev = frames[:, 3*j].astype(np.int64)[:, None]
            c = frames[:, 1 + 3*j].astype(np.int64)[:, None] ^ v
            nxt = frames[:, 2 + 3*j].astype(np.int64)[:, None]
            for k in range(8):
                b = (c >> (7 - k)) & 1
                out[:, 0] += tabs[0][m, j, k, b].sum(axis=0)
                for ci, (dr, W) in enumerate(self.configs):
                    out[:, ci + 1] += tabs[ci + 1][m, j, k, _ctx_index(dr, W, prev, c, nxt, k), b].sum(axis=0)
        return out[:, lo:]


class InterFramePrior:
    """Inter-frame bit model: P(bit k of the clear masked byte j of frame f | exact mode byte of f,
    whether frame f +- d has the same mode byte, bit k of byte j of the clear frame f -+ d) for the
    nearest earlier (P) or later (N) frame within the group whose byte j is visible, d = 1..3.
    Slowly varying parameters (gains, LPC, norms) sit at fixed bit positions, so a clear
    neighbour predicts them.  Counts per unit; an item never uses its own unit."""

    def __init__(self, sources):
        self.counts = {src['unit']: self._count(src) for src in sources}
        self._tables = {}

    @staticmethod
    def _count(src):
        C = np.zeros((2, len(IF_DISTANCES), 256, 2, NB, 8, 2, 2), np.int64)
        fr, known, pres = src['frames'], src['known'], src['present']
        for di, dr in enumerate((-1, 1)):
            for dd, d in enumerate(IF_DISTANCES):
                for r in range(ROLES):
                    rr = (r + dr*d) % ROLES
                    f = np.arange(r, GROUP_FRAMES, ROLES)
                    ref = f + dr*d
                    ok_f = (ref >= 0) & (ref < GROUP_FRAMES)
                    f, ref = f[ok_f], ref[ok_f]
                    for j in range(NB):
                        use = known[:, NB*r + j] & known[:, NB*rr + j]
                        if not use.any():
                            continue
                        ok = pres[use][:, f] & pres[use][:, ref]
                        tf, rf = fr[use][:, f][ok], fr[use][:, ref][ok]
                        mode = tf[:, 0].astype(np.int64)
                        same = (tf[:, 0] == rf[:, 0]).astype(np.int64)
                        c, cr = tf[:, 1 + 3*j].astype(np.int64), rf[:, 1 + 3*j].astype(np.int64)
                        for k in range(8):
                            b, br = (c >> (7 - k)) & 1, (cr >> (7 - k)) & 1
                            np.add.at(C[di, dd], (mode, same, j, k, br, b), 1)
        return C

    def tables(self, unit):
        key = unit if unit in self.counts else '*'
        if key not in self._tables:
            C = sum(self.counts[u].astype(np.float64) for u in self.counts if u != unit)
            Njk = C.sum(axis=(2, 3, 6)) + 1.0                                   # (2, D, 11, 8, 2)
            p_jk = Njk/Njk.sum(axis=-1, keepdims=True)
            Nm = C.sum(axis=(3, 6))                                             # (2, D, 256, 11, 8, 2)
            p_m = (Nm + CTX_BETA*p_jk[:, :, None])/(Nm.sum(axis=-1, keepdims=True) + CTX_BETA)
            p = (C + CTX_ALPHA*p_m[:, :, :, None, :, :, None, :])/(C.sum(axis=-1, keepdims=True) + CTX_ALPHA)
            self._tables[key] = (np.log(p).astype(np.float32), np.log(p_m).astype(np.float32))
        return self._tables[key]

    def scores(self, frames, present, visible, r, j, unit):
        """(256, 2) P / N scores for candidate values of byte (r, j) of one group, and the two
        reference distances (0 = none).  frames (60, 33) with visible bytes removed, present (60,),
        visible (44,) bool."""
        L, Lm = self.tables(unit)
        out = np.zeros((256, 2))
        dists = [0, 0]
        f = np.arange(r, GROUP_FRAMES, ROLES)
        f = f[present[f]]
        if not len(f):
            return out, dists
        v = np.arange(256, dtype=np.int64)[None, :]
        mode = frames[f, 0].astype(np.int64)[:, None]
        c = frames[f, 1 + 3*j].astype(np.int64)[:, None] ^ v                     # (n, 256)
        for di, dr in enumerate((-1, 1)):
            d = next((d for d in IF_DISTANCES if visible[NB*((r + dr*d) % ROLES) + j]), None)
            if d is None:
                continue
            dists[di] = d
            dd = IF_DISTANCES.index(d)
            ref = f + dr*d
            inside = (ref >= 0) & (ref < GROUP_FRAMES)
            has = inside.copy()
            has[inside] = present[ref[inside]]
            refc = np.where(has, ref, 0)
            same = (frames[refc, 0] == frames[f, 0]).astype(np.int64)[:, None]
            cr = frames[refc, 1 + 3*j].astype(np.int64)[:, None]
            for k in range(8):
                b = (c >> (7 - k)) & 1
                br = (cr >> (7 - k)) & 1
                full = L[di, dd, mode, same, j, k, br, b]
                marg = Lm[di, dd, mode, j, k, b]
                out[:, di] += np.where(has[:, None], full, marg).sum(axis=0)
        return out, dists


class BitPriors:
    """All bitstream prior features of an item (PRIOR_NAMES)."""

    def __init__(self):
        real, syn = plaintext_sources('real'), plaintext_sources('syn')
        self.ctx_real = ContextPrior(real, CTX_CONFIGS)
        self.ctx_syn = ContextPrior(syn, SYN_CTX_CONFIGS)
        self.if_real = InterFramePrior(real)
        self.if_syn = InterFramePrior(syn)
        self.sources = [dict(unit=s['unit'], source=s['source'], groups=int(len(s['frames']))) for s in real + syn]

    def item(self, inputs, g, r, j):
        unit = cv_unit(inputs['capture'][g])
        pres = inputs['present'][g]
        role_frames = inputs['frames'][g, r::ROLES][pres[r::ROLES]]
        visible = inputs['known'][g] >= 0
        visible[NB*r + j] = False
        frames = _unmask(inputs['frames'][g][None], inputs['known'][g][None], visible[None])[0]
        a = self.ctx_real.scores(role_frames, j, unit)
        b = self.ctx_syn.scores(role_frames, j, unit, with_marginal=False)
        c, dists = self.if_real.scores(frames, pres, visible, r, j, unit)
        e, _ = self.if_syn.scores(frames, pres, visible, r, j, unit)
        return np.concatenate([a, b, c, e], axis=1), dists


MODEL_CONTEXT_NAMES = CONTEXT_NAMES + ('inv_dP', 'inv_dN', 'has_dec')


def item_context(inputs, g, r, j, dists=(0, 0)):
    """Item context computable from the inputs alone (CONTEXT_NAMES as in item_features, plus the
    inverse distances of the inter-frame reference frames)."""
    ctx = np.zeros(len(MODEL_CONTEXT_NAMES), np.float32)
    kn = inputs['known'][g] >= 0
    kn[NB*r + j] = False
    clear_roles = [q for q in range(ROLES) if q != r and kn[NB*q:NB*(q + 1)].all()]
    pres = inputs['present'][g, r::ROLES]
    ctx[r] = 1
    ctx[ROLES + j] = 1
    if pres.any():
        mc = mode_class_onehot(inputs['frames'][g, r::ROLES, 0][pres])
        ctx[ROLES + NB:ROLES + NB + mc.shape[1]] = mc.mean(axis=0)
    n = len(CONTEXT_NAMES)
    ctx[n - 4] = pres.sum()/15
    ctx[n - 3] = float(r >= 1 and (r - 1) in clear_roles)
    ctx[n - 2] = float(((r + 1) % ROLES) in clear_roles)
    ctx[n - 1] = len(clear_roles)/3
    ctx[n] = 1/dists[0] if dists[0] else 0
    ctx[n + 1] = 1/dists[1] if dists[1] else 0
    return ctx


def prior_block(inputs, groups, roles, js, priors):
    """(n, 256, len(PRIOR_NAMES)) prior features and (n, C) contexts for items (groups[i], roles[i], js[i])."""
    Xc = np.zeros((len(groups), 256, len(PRIOR_NAMES)), np.float32)
    ctx = np.zeros((len(groups), len(MODEL_CONTEXT_NAMES)), np.float32)
    for i, (g, r, j) in enumerate(zip(groups, roles, js)):
        Xc[i], dists = priors.item(inputs, int(g), int(r), int(j))
        ctx[i] = item_context(inputs, int(g), int(r), int(j), dists)
    return Xc, ctx


def target_items(inputs, groups):
    g, m = np.nonzero(inputs['target'][groups])
    g = np.asarray(groups)[g]
    return g, m // NB, m % NB


# --------------------------------------------------------------------------- model

VARIANTS = ('ctx', 'dec', 'full')
RANK_COLS = ('prior_logp', 'mode_prior', 'ctx_L4', 'ctx_L6')
DEC_ONLY = tuple(n for n in FEATURE_NAMES if n != 'prior_logp')


def variant_names(variant):
    """ctx: bitstream priors only; dec: decoder features + ModePrior; full: decoder features + bitstream priors."""
    if variant == 'ctx':
        return PRIOR_NAMES
    if variant == 'dec':
        return FEATURE_NAMES
    return DEC_ONLY + PRIOR_NAMES


class Store:
    """Model inputs X (len(idx), 256, F) assembled on demand from prior features Xc (all items) and
    decoder features Xd (rows dec_index >= 0); items without decoder features get zeros there and
    has_dec = 0 in their context."""

    def __init__(self, variant, Xc, ctx, Xd=None, dec_index=None):
        self.variant = variant
        self.names = list(variant_names(variant))
        self.Xc, self.Xd = Xc, Xd
        self.dec_index = np.full(len(Xc), -1) if dec_index is None else np.asarray(dec_index)
        self.ctx = np.array(ctx, np.float32, copy=True)
        self.ctx[:, MODEL_CONTEXT_NAMES.index('has_dec')] = (self.dec_index >= 0) if variant != 'ctx' else 0
        if variant != 'ctx' and Xd is None:
            raise ValueError('variant needs decoder features')
        if variant == 'dec' and (self.dec_index < 0).any():
            raise ValueError("variant 'dec' needs decoder features for every item")
        self.perm = None
        self.dec_cols = np.array([n in FEATURE_NAMES for n in self.names]) if variant != 'ctx' else np.zeros(len(self.names), bool)

    def __len__(self):
        return len(self.Xc)

    def has_dec(self, idx):
        return (self.dec_index[np.asarray(idx)] >= 0) if self.variant != 'ctx' else np.zeros(len(idx), bool)

    def get_prior(self, idx):
        """Only the prior columns (the trailing PRIOR_NAMES of the 'full' variant) of items idx."""
        assert self.variant == 'full'
        X = np.array(self.Xc[np.asarray(idx)], np.float32)
        if self.perm is not None:
            cols, seed = self.perm
            off = len(DEC_ONLY)
            pc = [c - off for c in cols if c >= off]
            for i, it in enumerate(np.asarray(idx)):
                pm = np.random.default_rng(seed*1000003 + int(it)).permutation(256)
                X[i][:, pc] = X[i][pm][:, pc]
        return X

    def get(self, idx):
        idx = np.asarray(idx)
        if self.variant == 'ctx':
            X = np.array(self.Xc[idx], np.float32)
        else:
            Xd = np.zeros((len(idx), 256, len(FEATURE_NAMES)), np.float32)
            di = self.dec_index[idx]
            ok = di >= 0
            if ok.any():
                Xd[ok] = self.Xd[di[ok]]
            if self.variant == 'dec':
                X = Xd
            else:
                keep = [FEATURE_NAMES.index(n) for n in DEC_ONLY]
                X = np.concatenate([Xd[..., keep], self.Xc[idx]], axis=2)
        if self.perm is not None:
            cols, seed = self.perm
            for i, it in enumerate(idx):
                pm = np.random.default_rng(seed*1000003 + int(it)).permutation(256)
                X[i][:, cols] = X[i][pm][:, cols]
        return X


J_GROUPS = ((0,), (1, 2), tuple(range(3, NB)))
DEC_MODES = ('shared', 'jgroup', 'jgroup_linear')


def design(X, stats, names, ctx=None, dec_mode='shared', dec_cols=None):
    """Model inputs per candidate.  Each column gives an item-centred global z and an item z-score;
    prior scores also give their within-item rank.  Returns (linear inputs, MLP inputs).
    dec_mode 'shared': decoder columns enter both parts as they are; 'jgroup': the linear part gets
    them once per byte-position group (J_GROUPS, from the j one-hot in ctx), so evidence that only
    works at j = 0 cannot add noise at other positions; 'jgroup_linear': as 'jgroup' and the MLP sees
    no decoder columns."""
    Z = (X - stats['mu'])/stats['sd']
    C = np.clip(Z - Z.mean(axis=1, keepdims=True), -20, 20)
    S = np.clip(C/(Z.std(axis=1, keepdims=True) + 0.1), -10, 10)
    ranks = []
    for col in RANK_COLS:
        if col in names:
            v = X[..., names.index(col)]
            ranks.append((np.argsort(np.argsort(-v, axis=1, kind='stable'), axis=1, kind='stable')/255.0)[..., None])
    if dec_mode == 'shared' or dec_cols is None or not np.any(dec_cols):
        lin = np.concatenate([C, S] + ranks, axis=2).astype(np.float32)
        return lin, lin
    pc, dc = ~dec_cols, dec_cols
    base = [C[..., pc], S[..., pc]] + ranks
    jg = ctx[:, ROLES:ROLES + NB]
    parts = list(base)
    for grp in J_GROUPS:
        ind = jg[:, list(grp)].sum(axis=1)[:, None, None]
        parts += [C[..., dc]*ind, S[..., dc]*ind]
    lin = np.concatenate(parts, axis=2).astype(np.float32)
    if dec_mode == 'jgroup':
        mlp = np.concatenate([C, S] + ranks, axis=2).astype(np.float32)
    else:
        mlp = np.concatenate(base, axis=2).astype(np.float32)
    return lin, mlp


def design_dims(names, dec_mode, dec_cols):
    n, nr = len(names), sum(c in names for c in RANK_COLS)
    nd = int(np.sum(dec_cols)) if dec_cols is not None else 0
    if dec_mode == 'shared' or not nd:
        return 2*n + nr, 2*n + nr
    lin = 2*(n - nd) + nr + 2*nd*len(J_GROUPS)
    return lin, (2*n + nr if dec_mode == 'jgroup' else 2*(n - nd) + nr)


def design_names(names, dec_mode='shared', dec_cols=None):
    nr = [f'rank:{c}' for c in RANK_COLS if c in names]
    if dec_mode == 'shared' or dec_cols is None or not np.any(dec_cols):
        return [f'c:{n}' for n in names] + [f'z:{n}' for n in names] + nr
    pn = [n for n, d in zip(names, dec_cols) if not d]
    dn = [n for n, d in zip(names, dec_cols) if d]
    out = [f'c:{n}' for n in pn] + [f'z:{n}' for n in pn] + nr
    for gi, grp in enumerate(J_GROUPS):
        out += [f'c:{n}@j{grp[0]}-{grp[-1]}' for n in dn] + [f'z:{n}@j{grp[0]}-{grp[-1]}' for n in dn]
    return out


class Ranker:
    """Score s(v) = a.lin(v) + w2.relu(W1 [lin(v); ctx] + b1); P(v) = softmax_v(s(v)/T).

    lin(v) = design(X(v)); the standardisation statistics are part of the model."""

    def __init__(self, names, n_ctx, hidden=32, seed=0, dec_mode='shared'):
        self.names = list(names)
        self.dec_mode = dec_mode
        self.dec_cols = np.array([n in FEATURE_NAMES and n != 'prior_logp' for n in self.names])
        n_lin, n_mlp = design_dims(self.names, dec_mode, self.dec_cols)
        rng = np.random.default_rng(seed)
        self.hidden = hidden
        self.p = dict(a=np.zeros(n_lin, np.float32))
        if hidden:
            self.p.update(W1=(rng.standard_normal((n_mlp + n_ctx, hidden))*np.sqrt(1.0/(n_mlp + n_ctx))).astype(np.float32),
                          b1=np.zeros(hidden, np.float32), w2=np.zeros(hidden, np.float32))
        self.T = 1.0
        self.stats = None

    def set_stats(self, store, idx, sample=3000, seed=0):
        """Per-column scale over the candidates of a sample of items (decoder columns: items that have them)."""
        idx = np.asarray(idx)
        if len(idx) > sample:
            idx = np.sort(np.random.default_rng(seed).choice(idx, sample, replace=False))
        X = store.get(idx)
        has = store.dec_index[idx] >= 0
        mu = np.zeros(X.shape[2], np.float32)
        sd = np.ones(X.shape[2], np.float32)
        for c in range(X.shape[2]):
            rows = X[has, :, c] if store.dec_cols[c] else X[:, :, c]
            if rows.size:
                mu[c] = rows.mean()
                sd[c] = rows.std() if rows.std() > 1e-6 else 1.0
        self.stats = dict(mu=mu, sd=sd)

    def _forward(self, X, ctx):
        lin, mlp = design(X, self.stats, self.names, ctx, self.dec_mode, self.dec_cols)
        s = lin @ self.p['a']
        cache = (lin, None, None, None)
        if self.hidden:
            n, K, _ = mlp.shape
            inp = np.concatenate([mlp, np.broadcast_to(ctx[:, None, :], (n, K, ctx.shape[1]))], axis=2)
            pre = inp @ self.p['W1'] + self.p['b1']
            h = np.maximum(pre, 0)
            s = s + h @ self.p['w2']
            cache = (lin, inp, pre, h)
        return s, cache

    def fast_path(self, store):
        """Items without decoder features need only the prior columns ('full' + 'jgroup_linear'):
        their decoder inputs are zero, so the linear part reduces to its leading prior block and the
        MLP never sees decoder columns."""
        return store.variant == 'full' and self.dec_mode == 'jgroup_linear' and bool(self.dec_cols.any())

    def _forward_prior(self, Xp, ctx):
        pc = ~self.dec_cols
        stats = dict(mu=self.stats['mu'][pc], sd=self.stats['sd'][pc])
        lin, _ = design(Xp, stats, [n for n, d in zip(self.names, self.dec_cols) if not d])
        nb = lin.shape[2]
        s = lin @ self.p['a'][:nb]
        cache = (lin, None, None, None)
        if self.hidden:
            n, K, _ = lin.shape
            inp = np.concatenate([lin, np.broadcast_to(ctx[:, None, :], (n, K, ctx.shape[1]))], axis=2)
            pre = inp @ self.p['W1'] + self.p['b1']
            h = np.maximum(pre, 0)
            s = s + h @ self.p['w2']
            cache = (lin, inp, pre, h)
        return s, cache

    def batch_grad(self, store, idx, y, w, l2):
        if self.fast_path(store) and not store.has_dec(idx).any():
            return self.loss_grad(store.get_prior(idx), store.ctx[idx], y, w, l2, prior_only=True)
        return self.loss_grad(store.get(idx), store.ctx[idx], y, w, l2)

    def loss_grad(self, X, ctx, y, w, l2, prior_only=False):
        s, (lin, inp, pre, h) = self._forward_prior(X, ctx) if prior_only else self._forward(X, ctx)
        s = s - s.max(axis=1, keepdims=True)
        lse = np.log(np.exp(s).sum(axis=1))
        n = len(y)
        nll = lse - s[np.arange(n), y]
        loss = float(np.sum(w*nll)/np.sum(w))
        dS = np.exp(s - lse[:, None])
        dS[np.arange(n), y] -= 1
        dS *= (w/np.sum(w))[:, None]
        d1 = dS.reshape(-1).astype(np.float32)
        g = dict(a=np.zeros_like(self.p['a']))
        g['a'][:lin.shape[2]] = d1 @ lin.reshape(-1, lin.shape[2])
        if self.hidden:
            g['w2'] = d1 @ h.reshape(-1, h.shape[2])
            dpre = (d1[:, None]*self.p['w2'][None, :])*(pre.reshape(-1, pre.shape[2]) > 0)
            g['W1'] = inp.reshape(-1, inp.shape[2]).T @ dpre
            g['b1'] = dpre.sum(axis=0)
        for k in g:
            if k != 'b1':
                g[k] = g[k] + l2*self.p[k]
        return loss, g

    def fit(self, store, idx, y, w=None, epochs=30, batch=64, lr=3e-3, l2=1e-3, seed=0, log=None):
        idx = np.asarray(idx)
        if self.stats is None:
            self.set_stats(store, idx)
        w = np.ones(len(idx)) if w is None else np.asarray(w, np.float64)
        rng = np.random.default_rng(seed)
        m = {k: np.zeros_like(v) for k, v in self.p.items()}
        v2 = {k: np.zeros_like(v) for k, v in self.p.items()}
        t = 0
        n = len(idx)
        split = self.fast_path(store)
        hd = store.has_dec(idx)
        for ep in range(epochs):
            order = rng.permutation(n)
            tot = 0.0
            rate = lr*(0.5*(1 + np.cos(np.pi*ep/epochs)))     # cosine schedule
            if split:      # batches that either all have decoder features or all lack them
                batches = [np.sort(part[b:b + batch]) for part in (order[hd[order]], order[~hd[order]])
                           for b in range(0, len(part), batch)]
                batches = [batches[i] for i in rng.permutation(len(batches))]
            else:
                batches = [np.sort(order[b:b + batch]) for b in range(0, n, batch)]
            for sel in batches:
                loss, g = self.batch_grad(store, idx[sel], y[sel], w[sel], l2)
                tot += loss*len(sel)
                t += 1
                for k in self.p:
                    m[k] = 0.9*m[k] + 0.1*g[k]
                    v2[k] = 0.999*v2[k] + 0.001*g[k]**2
                    step = rate*(m[k]/(1 - 0.9**t))/(np.sqrt(v2[k]/(1 - 0.999**t)) + 1e-8)
                    self.p[k] -= step.astype(np.float32)
            if log and (ep % 10 == 9 or ep == epochs - 1):
                log(f'    epoch {ep + 1}/{epochs}: train nll {tot/n:.4f}')
        return self

    def raw_scores(self, store, idx):
        idx = np.asarray(idx)
        out = np.empty((len(idx), 256), np.float64)
        if self.fast_path(store):
            hd = store.has_dec(idx)
            for part in (np.flatnonzero(hd), np.flatnonzero(~hd)):
                for b in range(0, len(part), 256):
                    sel = part[b:b + 256]
                    if hd[sel[0]]:
                        out[sel] = self._forward(store.get(idx[sel]), store.ctx[idx[sel]])[0]
                    else:
                        out[sel] = self._forward_prior(store.get_prior(idx[sel]), store.ctx[idx[sel]])[0]
            return out
        for b in range(0, len(idx), 256):
            out[b:b + 256] = self._forward(store.get(idx[b:b + 256]), store.ctx[idx[b:b + 256]])[0]
        return out

    def logp(self, store, idx, T=None):
        T = self.T if T is None else T
        s = self.raw_scores(store, idx)/T
        s = s - s.max(axis=1, keepdims=True)
        return s - np.log(np.exp(s).sum(axis=1, keepdims=True))

    def to_arrays(self, prefix):
        out = {f'{prefix}/{k}': v for k, v in self.p.items()}
        out.update({f'{prefix}/mu': self.stats['mu'], f'{prefix}/sd': self.stats['sd'],
                    f'{prefix}/T': np.float64(self.T), f'{prefix}/hidden': np.int64(self.hidden),
                    f'{prefix}/names': np.array(self.names), f'{prefix}/dec_mode': np.array(self.dec_mode)})
        return out

    @classmethod
    def from_arrays(cls, d, prefix):
        r = cls.__new__(cls)
        r.hidden = int(d[f'{prefix}/hidden'])
        r.names = [str(x) for x in d[f'{prefix}/names']]
        r.dec_mode = str(d[f'{prefix}/dec_mode']) if f'{prefix}/dec_mode' in d else 'shared'
        r.dec_cols = np.array([n in FEATURE_NAMES and n != 'prior_logp' for n in r.names])
        r.p = {k: d[f'{prefix}/{k}'] for k in ('a', 'W1', 'b1', 'w2') if f'{prefix}/{k}' in d}
        r.stats = dict(mu=d[f'{prefix}/mu'], sd=d[f'{prefix}/sd'])
        r.T = float(d[f'{prefix}/T'])
        return r


def fit_temperature(scores, y):
    """Temperature minimising NLL of held-out raw scores (grid search)."""
    best = (np.inf, 1.0)
    n = len(y)
    for T in np.exp(np.linspace(np.log(0.25), np.log(6), 80)):
        z = scores/T
        z = z - z.max(axis=1, keepdims=True)
        lp = z - np.log(np.exp(z).sum(axis=1, keepdims=True))
        nll = -float(np.mean(lp[np.arange(n), y]))
        if nll < best[0]:
            best = (nll, float(T))
    return best[1], best[0]


# --------------------------------------------------------------------------- data for training / prediction

TRAIN_SPLITS = ('dev', 'syn-dev')
HYPER = dict(hidden=32, epochs=20, batch=64, lr=3e-3, l2=1e-3, calib_fraction=0.15, real_weight=1.0, dec_weight=1.0,
             dec_mode='jgroup_linear')


def inputs_path(split, task):
    return ROOT/f'work/benchmark/tasks/{split}.{task}.inputs.npz'


def truth_path(split, task):
    return ROOT/f'work/benchmark/tasks/{split}.{task}.truth.npz'


def attach_truth(D):
    """y for every item (training only: DEV / syn-dev truth, which protocol rule 2 allows)."""
    y = np.full(len(D['role']), -1, np.int64)
    for sp, tk in sorted(set(zip(D['split'], D['task']))):
        if sp not in TRAIN_SPLITS:
            raise SystemExit(f'{sp}.{tk}: only {TRAIN_SPLITS} may train the model')
        T = load_npz(truth_path(sp, tk))
        index = {str(g): i for i, g in enumerate(T['group_id'])}
        sel = np.flatnonzero((D['split'] == sp) & (D['task'] == tk))
        rows = np.array([index[g] for g in D['group_id'][sel]])
        m = NB*D['role'][sel] + D['j'][sel]
        if not T['target'][rows, m].all():
            raise SystemExit(f'{sp}.{tk}: items that are not target cells')
        y[sel] = T['truth'][rows, m]
    D['y'] = y
    return D


def item_keys(split, task, group_id, role, j):
    return [f'{a}|{b}|{c}|{d}|{e}' for a, b, c, d, e in zip(split, task, group_id, role, j)]


def build_items(specs, priors, log=print):
    """All target items of the (optionally subsampled) groups of each 'split.task[@n[:seed]]' spec,
    with prior features and contexts (no decoder features)."""
    parts = []
    for spec in specs:
        name, _, rest = spec.partition('@')
        n, _, seed = rest.partition(':')
        split, task = name.rsplit('.', 1)
        inputs = load_npz(inputs_path(split, task))
        groups, roles, js = target_items(inputs, select_groups(inputs, int(n) if n else None, int(seed or 0)))
        t0 = time.time()
        Xc, ctx = prior_block(inputs, groups, roles, js, priors)
        if log:
            log(f'  {name}: {len(groups)} items, prior features {time.time() - t0:.0f} s', flush=True)
        k = len(groups)
        parts.append(dict(Xc=Xc, ctx=ctx, group=groups, group_id=inputs['group_id'][groups].astype(str),
                          capture=inputs['capture'][groups].astype(str), role=roles, j=js,
                          split=np.array([split]*k), task=np.array([task]*k)))
    D = {key: np.concatenate([p[key] for p in parts]) for key in parts[0]}
    D['unit'] = np.array([cv_unit(c) for c in D['capture']])
    D['key'] = np.array(item_keys(D['split'], D['task'], D['group_id'], D['role'], D['j']))
    return D


def merge_dec(D, files):
    """Decoder features (clean runs only) for the items of D that have them: (Xd rows, dec_index)."""
    where = {k: i for i, k in enumerate(D['key'])}
    dec_index = np.full(len(D['key']), -1)
    rows = []
    for path in files:
        F = load_npz(path)
        meta = json.loads(str(F['meta']))
        if meta['feature_version'] != FEATURE_VERSION or tuple(F['feature_names']) != FEATURE_NAMES:
            raise SystemExit(f'{path}: feature version mismatch')
        if meta['control'] != 'none':
            raise SystemExit(f'{path}: control features cannot train the model')
        split, task = str(F['split']), str(F['task'])
        keys = item_keys([split]*len(F['role']), [task]*len(F['role']), F['group_id'].astype(str), F['role'], F['j'])
        X = clean(F['X'])
        for i, k in enumerate(keys):
            if k in where and dec_index[where[k]] < 0:
                dec_index[where[k]] = len(rows)
                rows.append(X[i])
    return (np.array(rows, np.float32) if rows else None), dec_index


def calib_split(group_ids, fraction, salt='calib'):
    h = np.array([int(hashlib.sha256((salt + g).encode()).hexdigest()[:8], 16)/2**32 for g in group_ids])
    return h < fraction


def train_one(store, D, idx, hp, seed=0, log=print):
    """Fit a ranker on items idx (a calibration part held out by group) and set its temperature."""
    cal = calib_split(D['group_id'][idx], hp['calib_fraction'])
    fit_idx, cal_idx = idx[~cal], idx[cal]
    w = np.where(D['split'][fit_idx] == 'dev', hp['real_weight'], 1.0)*np.where(store.dec_index[fit_idx] >= 0, hp['dec_weight'], 1.0)
    r = Ranker(store.names, len(MODEL_CONTEXT_NAMES), hidden=hp['hidden'], seed=seed, dec_mode=hp['dec_mode'])
    r.set_stats(store, fit_idx)
    r.fit(store, fit_idx, D['y'][fit_idx], w=w, epochs=hp['epochs'], batch=hp['batch'], lr=hp['lr'], l2=hp['l2'],
          seed=seed, log=log)
    nll = float('nan')
    if len(cal_idx) >= 50:
        r.T, nll = fit_temperature(r.raw_scores(store, cal_idx), D['y'][cal_idx])
    if log:
        log(f'    fit {len(fit_idx)} items, calibration {len(cal_idx)} items: T = {r.T:.3f}, held-out nll {nll:.4f}')
    return r


def summarize_oof(lp, y, label):
    n = len(y)
    if not n:
        return dict(set=label, items=0)
    pt = lp[np.arange(n), y]
    greater = (lp > pt[:, None]).sum(axis=1)
    ties = (lp == pt[:, None]).sum(axis=1)
    top1 = np.clip((1 - greater)/ties, 0, 1)
    rank = 1 + greater + 0.5*(ties - 1)
    return dict(set=label, items=int(n), top1=round(float(top1.mean()), 4), mean_rank=round(float(rank.mean()), 2),
                nll_bits=round(float(-pt.mean()/np.log(2)), 4))


def oof_logp(models, store, D, idx):
    lp = np.empty((len(idx), 256))
    for u in np.unique(D['unit'][idx]):
        sel = D['unit'][idx] == u
        lp[sel] = models[u].logp(store, idx[sel])
    return lp


def permutation_importance(store, D, models, idx, seed=0):
    """OOF NLL increase (bits/item) on items idx when one evidence group's columns are permuted
    across the candidates of each item."""
    groups = {}
    for i, name in enumerate(store.names):
        key = name.split('|')[1] if name.startswith('max|') else name.split('|')[0]
        groups.setdefault(key, []).append(i)
    y = D['y'][idx]
    base = -oof_logp(models, store, D, idx)[np.arange(len(idx)), y].mean()
    out = {}
    for gi, (name, cols) in enumerate(groups.items()):
        store.perm = (cols, seed + gi)
        lp = oof_logp(models, store, D, idx)
        store.perm = None
        out[name] = round(float((-lp[np.arange(len(idx)), y].mean() - base)/np.log(2)), 4)
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))


def cmd_train(a):
    hp = dict(HYPER)
    for k in ('hidden', 'epochs', 'l2', 'lr', 'real_weight', 'dec_weight', 'dec_mode'):
        if getattr(a, k) is not None:
            hp[k] = type(HYPER[k])(getattr(a, k))
    priors = BitPriors()
    D = attach_truth(build_items(a.data, priors))
    Xd, dec_index = merge_dec(D, a.dec or [])
    if a.variant == 'dec':
        keep = np.flatnonzero(dec_index >= 0)
        D = {k: v[keep] for k, v in D.items()}
        dec_index = dec_index[keep]
    store = Store(a.variant, D['Xc'], D['ctx'], Xd, dec_index)
    units = D['unit']
    has = store.dec_index >= 0
    print(f'variant {a.variant}: {len(D["y"])} items ({int(has.sum())} with decoder features), {len(store.names)} features; '
          'units ' + ', '.join(f'{u}={int((units == u).sum())}' for u in np.unique(units)), flush=True)
    arrays, models = {}, {}
    for u in np.unique(units):
        print(f'  model excl:{u}', flush=True)
        models[u] = train_one(store, D, np.flatnonzero(units != u), hp, log=print)
        arrays.update(models[u].to_arrays(f'excl:{u}'))
    allidx = np.arange(len(D['y']))
    lp = oof_logp(models, store, D, allidx)
    report = dict(method=METHOD, variant=a.variant, hyper=hp, data=a.data,
                  dec_features=[dict(path=str(p), sha256=sha256_file(p)) for p in (a.dec or [])],
                  units={u: int((units == u).sum()) for u in np.unique(units)}, oof=[])
    for (sp, tk) in sorted(set(zip(D['split'], D['task']))):
        sel = (D['split'] == sp) & (D['task'] == tk)
        for subset, mask in (('all', sel), ('dec', sel & has)):
            if subset == 'dec' and a.variant == 'ctx':
                continue
            report['oof'].append(summarize_oof(lp[mask], D['y'][mask], f'{sp}.{tk} [{subset}]'))
            mp = D['Xc'][mask][..., 0].astype(np.float64)
            if len(mp):
                mp = mp - mp.max(axis=1, keepdims=True)
                mp = mp - np.log(np.exp(mp).sum(axis=1, keepdims=True))
                report['oof'].append(summarize_oof(mp, D['y'][mask], f'{sp}.{tk} [{subset}] mode_prior-only'))
        mask = sel & has if a.variant != 'ctx' else sel
        for m in np.unique(NB*D['role'][mask] + D['j'][mask]):
            s2 = mask & (NB*D['role'] + D['j'] == m)
            report['oof'].append(summarize_oof(lp[s2], D['y'][s2], f'{sp}.{tk} r{m // NB}j{m % NB}'))
    for row in report['oof']:
        if ' r' not in row['set'] or a.verbose:
            print('  ', row, flush=True)
    if a.importance:
        pool = np.flatnonzero(has) if a.variant != 'ctx' else allidx
        if len(pool) > a.importance_items:
            pool = np.sort(np.random.default_rng(0).choice(pool, a.importance_items, replace=False))
        report['permutation_importance_bits'] = permutation_importance(store, D, models, pool)
        report['permutation_importance_items'] = int(len(pool))
        print('  importance', report['permutation_importance_bits'], flush=True)
    if not a.no_all:
        print('  model all', flush=True)
        arrays.update(train_one(store, D, allidx, hp, log=print).to_arrays('all'))
    if a.oof_out:
        np.savez_compressed(a.oof_out, logp=lp.astype(np.float32), y=D['y'], group_id=D['group_id'], has_dec=has,
                            role=D['role'], j=D['j'], split=D['split'], task=D['task'], capture=D['capture'])
    meta = dict(report, units_list=sorted(set(units)), names=store.names, context_names=MODEL_CONTEXT_NAMES,
                feature_version=FEATURE_VERSION, prior_sources=priors.sources, script_sha256=sha256_file(__file__))
    a.out.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(a.out, meta=json.dumps(meta), **arrays)
    Path(str(a.out) + '.json').write_text(json.dumps(report, indent=1) + '\n')
    print(f'wrote {a.out}', flush=True)


# --------------------------------------------------------------------------- prediction

def load_model(path):
    d = load_npz(path)
    meta = json.loads(str(d['meta']))
    if meta['feature_version'] != FEATURE_VERSION:
        raise SystemExit(f'{path}: model was trained on another feature version')
    names = sorted({k.split('/')[0] for k in d if '/' in k})
    return {n: Ranker.from_arrays(d, n) for n in names}, meta


def apply_model(models, meta, store, captures):
    """logp (n, 256): each item by the model that never saw its cross-fit unit."""
    units = np.array([cv_unit(c) for c in captures])
    lp = np.empty((len(units), 256))
    used = {}
    for u in np.unique(units):
        name = f'excl:{u}' if f'excl:{u}' in models else 'all'
        if name == 'all' and u in meta['units_list']:
            raise SystemExit(f'no held-out model for training unit {u}')
        sel = np.flatnonzero(units == u)
        lp[sel] = models[name].logp(store, sel)
        used[u] = name
    return lp, used


def get_features(a, inputs, groups, control=None):
    meta = features_meta(a.inputs, groups, a.seed, a.groups, control)
    if a.features and Path(a.features).exists():
        F = load_npz(a.features)
        old = json.loads(str(F['meta']))
        same = all(old.get(k) == meta[k] for k in ('feature_version', 'inputs_sha256', 'groups_requested', 'seed', 'control'))
        if same and set(F['group'].tolist()) == set(groups.tolist()):
            print(f'using cached features {a.features}', flush=True)
            F['X'] = clean(F['X'])
            return F
        raise SystemExit(f'{a.features} exists but does not match these inputs / groups / version')
    F = extract(inputs, groups, control=control, jobs=a.jobs)
    if a.features:
        save_features(a.features, F, meta, inputs)
    return F


def cmd_predict(a):
    inputs = load_npz(a.inputs)
    groups = select_groups(inputs, a.groups, a.seed)
    print(f'{a.inputs}: {len(groups)} groups, {int(inputs["target"][groups].sum())} target items', flush=True)
    models, meta = load_model(a.model)
    variant = meta['variant']
    priors = BitPriors()
    feat_roles = None
    if variant == 'ctx':
        g, r, j = target_items(inputs, groups)
        src = donor_groups(inputs, groups) if a.control == 'wrong-group' else groups
        smap = dict(zip(groups.tolist(), src.tolist()))
        feat_groups = np.array([smap[x] for x in g], np.int64)
        if a.control == 'shift-role':          # score the byte on another role's frames
            feat_roles = (r + 2) % ROLES
        Xd, dec_index = None, None
    elif a.control == 'shift-role':
        raise SystemExit('shift-role control is implemented for the ctx variant only')
    else:
        F = get_features(a, inputs, groups, a.control)
        g, r, j = F['group'].astype(np.int64), F['role'].astype(np.int64), F['j'].astype(np.int64)
        feat_groups = F['source_group'].astype(np.int64)
        Xd, dec_index = F['X'], np.arange(len(g))
    Xc, ctx = prior_block(inputs, feat_groups, r if feat_roles is None else feat_roles, j, priors)
    store = Store(variant, Xc, ctx, Xd, dec_index)
    lp, used = apply_model(models, meta, store, inputs['capture'][g])
    a.out.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(a.out, format=emp.PREDICTION_FORMAT, method=METHOD + f'/{variant}' + (f'+{a.control}' if a.control else ''),
                        split=str(inputs['split']), task=str(inputs['task']), group=inputs['group_id'][g].astype(str),
                        role=r.astype(np.int8), j=j.astype(np.int8), logp=lp.astype(np.float64),
                        model=str(a.model), model_sha256=sha256_file(a.model), models_used=json.dumps(used))
    print(f'wrote {a.out}: {len(lp)} items; variant {variant}; models used {used}', flush=True)


# --------------------------------------------------------------------------- CLI

def cmd_extract(a):
    inputs = load_npz(a.inputs)
    groups = select_groups(inputs, a.groups, a.seed)
    print(f'{a.inputs}: {len(groups)} groups, {int(inputs["target"][groups].sum())} items', flush=True)
    feats = extract(inputs, groups, control=a.control, jobs=a.jobs)
    save_features(a.out, feats, features_meta(a.inputs, groups, a.seed, a.groups, a.control), inputs)
    print(f'wrote {a.out}: {len(feats["X"])} items', flush=True)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] == 'extract':
        ap = argparse.ArgumentParser(prog='mask_method_learned_disc.py extract')
        ap.add_argument('--inputs', required=True, type=Path)
        ap.add_argument('--out', required=True, type=Path)
        ap.add_argument('--groups', type=int)
        ap.add_argument('--seed', type=int, default=0)
        ap.add_argument('--control', choices=['wrong-group'])
        ap.add_argument('--jobs', type=int, default=2)
        return cmd_extract(ap.parse_args(argv[1:]))
    if argv and argv[0] == 'train':
        ap = argparse.ArgumentParser(prog='mask_method_learned_disc.py train')
        ap.add_argument('--variant', choices=VARIANTS, default='full')
        ap.add_argument('--data', required=True, nargs='+', help="split.task[@n[:seed]] item sets (DEV / syn-dev only)")
        ap.add_argument('--dec', nargs='+', type=Path, help='decoder feature files (extract) to attach to matching items')
        ap.add_argument('--out', required=True, type=Path)
        ap.add_argument('--oof-out', type=Path)
        ap.add_argument('--importance', action='store_true')
        ap.add_argument('--importance-items', type=int, default=4000)
        ap.add_argument('--no-all', action='store_true')
        ap.add_argument('--verbose', action='store_true')
        for k in ('hidden', 'epochs', 'l2', 'lr', 'real_weight', 'dec_weight', 'dec_mode'):
            ap.add_argument('--' + k.replace('_', '-'), dest=k)
        return cmd_train(ap.parse_args(argv[1:]))
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--inputs', required=True, type=Path)
    ap.add_argument('--out', required=True, type=Path)
    ap.add_argument('--groups', type=int, help='seeded subsample of target groups (default: all)')
    ap.add_argument('--seed', type=int, default=0)
    ap.add_argument('--features', type=Path, help='decoder feature cache (written, or reused when it matches)')
    ap.add_argument('--model', type=Path, default=DEFAULT_MODEL)
    ap.add_argument('--control', choices=['wrong-group', 'shift-role'],
                    help='negative control: features from a different group, or (ctx variant) from another role')
    ap.add_argument('--jobs', type=int, default=2)
    return cmd_predict(ap.parse_args(argv))


if __name__ == '__main__':
    main()
