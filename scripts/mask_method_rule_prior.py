#!/usr/bin/env python3
"""Blind mask-byte predictions from EVS rule consensus plus a context-conditioned plaintext prior.

Method "rule-prior" for the blind mask benchmark (examples/nov28/blind-mask-benchmark/protocol.md).
It reads one <split>.<task>.inputs.npz and writes a standard predictions npz (group, role, j, logp).
It never reads truth files.

Two evidence sources are combined per (group, role, j) cell:

1. Rule consensus (payload byte 0, word bits b8/b9). The five field-rule modules used by
   scripts/project_evs_group.py --evidence (evs_transition_tags, evs_core_history, evs_intra_word,
   evs_gsc_fields, evs_hq_neighbors) are run unchanged on each group's clear octets. Their
   conditional events (TCX previous-core bit, SWB HQ class, HQ neighbour class, ACELP transition
   tag) restrict the clear b8/b9 of single words; scripts/evs_evidence.event_spec translates each
   into an allowed set. Because one mask byte covers all 15 words of a role, every word with a
   rule maps its allowed clear values onto allowed mask values. Mask values that every rule word of
   the role allows are kept (within-role unanimity); the rest get a hard penalty. If the rule
   words of a role contradict each other the role is left unconstrained.

2. A plaintext prior. For every received word of the role, P(clear byte | context) is a bit-chain
   model (MSB first) with hierarchical Dirichlet back-off:
       (j) -> (j, exact mode) per-bit -> 2-bit prefix -> full prefix -> + neighbouring clear bits
       (low 2 bits of payload byte 3j-1, high 2 bits of byte 3j+1) -> + previous word's signalling index
       -> + adjacent word's clear byte at the same position (only where that word's mask byte is visible).
   The mask log-likelihood is tau_j * sum over words of log P(ciphertext XOR m | context).
   Training data: DEV labelled plaintext (role 0 and role-1 j=0..4 from the DEV label files,
   with the item's own capture left out, as the benchmark's mode prior does) pooled with the
   plaintext that the inputs file itself reveals (its visible mask bytes), weighted by --trans-weight.

Variants (--variant): full (default), rules (rules + uniform), modeprior (the evaluator's
ModePrior baseline), rules+modeprior, prior (context prior without rules).
Controls (--control): wrong-group scores each target with the frames, presence flags and
visible bytes of the group half the list away (a cyclic shift), so any skill must vanish.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))

from check_evs_origin import PROJECTED_OCTETS  # noqa: E402
from evs_evidence import event_spec, field_sections  # noqa: E402

FORMAT = 'kcbs-mask-predictions/1'
METHOD = 'rule-prior'
KEYED = np.arange(0, 32, 3)
PROJ = set(PROJECTED_OCTETS)
DEFAULT_CORPUS = ('work/benchmark/real/nov25-0448+0457-3205-hik.npz',
                  'work/benchmark/real/nov25-1246-6140-merged.npz')
HARD_PENALTY = -40.0      # nats; rule-excluded mask values

# Frozen parameters (chosen on DEV / syn-dev; see work/methods/rule-prior/freeze.json).
PARAMS = dict(
    alpha_base=(1.0, 8.0, 16.0, 32.0),   # (j) order0, (j,mode) order0, order2, order8
    alpha_nb=32.0,                      # + neighbouring clear bits
    alpha_pm=32.0,                      # + previous word's signalling index
    alpha_adj=(32.0, 32.0),             # + adjacent word's clear byte (2-bit, 8-bit aligned prefix)
    trans_weight=3.0,                   # weight of inputs-revealed plaintext vs DEV corpus
    eps=0.02,                           # per-word mixture with uniform
    tau=(0.5, 0.3, 0.6, 0.5, 0.4, 0.15, 0.2, 0.45, 0.1, 0.35, 0.5),   # per-j temperature
    use_nb=True, use_pm=True, use_adj=True,
    use_nb2=True, alpha_nb2=64.0,       # wider neighbouring context (low 4 / high 4 bits)
    local_window=0, local_block=8,      # local adaptation: visible plaintext of groups within +-window
    local_orders=(2, 8), alpha_local=(16.0, 16.0),
)

# --------------------------------------------------------------------------- bit-chain model

NODE = np.zeros((8, 256), np.int64)
BIT = np.zeros((8, 256), np.int64)
for _k in range(8):
    NODE[_k] = (256 + np.arange(256)) >> (8 - _k)          # node index 1..255 at depth k
    BIT[_k] = ((256 + np.arange(256)) >> (7 - _k)) & 1
DEPTH = np.array([0] + [n.bit_length() - 1 for n in range(1, 256)], np.int64)


def _node_code(order):
    out = np.zeros(256, np.int64)
    for n in range(1, 256):
        d = int(DEPTH[n])
        o = min(order, d)
        out[n] = d*1024 + o*256 + ((n - (1 << d)) & ((1 << o) - 1))
    return out


CODES = {o: _node_code(o) for o in range(9)}


def _extra_code(extra, nextra, depth):
    """Aligned prefix of a neighbouring byte: its bits up to `depth`, last `nextra` of them."""
    if not nextra:
        return np.zeros(np.broadcast(extra, depth).shape, np.int64)
    width = np.minimum(depth + 1, nextra)
    return (extra >> (7 - depth)) & ((1 << width) - 1)


class Level:
    """Bit counts per (context key, reduced prefix node[, aligned neighbour prefix])."""

    def __init__(self, keys, values, weights, order, extra=None, nextra=0):
        self.order, self.nextra = order, nextra
        ks, bs, ws = [], [], []
        for k in range(8):
            node = NODE[k][values]
            ex = _extra_code(extra, nextra, k) if nextra else 0
            ks.append((keys*8192 + CODES[order][node])*256 + ex)
            bs.append(BIT[k][values])
            ws.append(weights)
        ks = np.concatenate(ks)
        self.u, inv = np.unique(ks, return_inverse=True)
        self.c = np.zeros((len(self.u), 2))
        np.add.at(self.c, (inv, np.concatenate(bs)), np.concatenate(ws))

    def counts(self, keys, extra=None):
        ex = _extra_code(extra[:, None], self.nextra, DEPTH[None, :]) if self.nextra else 0
        q = (keys[:, None]*8192 + CODES[self.order][None, :])*256 + ex
        i = np.clip(np.searchsorted(self.u, q), 0, len(self.u) - 1)
        ok = self.u[i] == q
        return np.where(ok[..., None], self.c[i], 0.0)


def leaf_logp(p1):
    lp = np.zeros((p1.shape[0], 256))
    for k in range(8):
        q = np.clip(p1[:, NODE[k]], 1e-9, 1 - 1e-9)
        lp += np.where(BIT[k][None, :] == 1, np.log(q), np.log1p(-q))
    return lp


# --------------------------------------------------------------------------- records

def plaintext_view(frames, present, masks):
    """Unmask every visible mask byte. Returns plain (N,60,33) and vis (N,60,11) (visible & present)."""
    plain = frames.copy()
    vis = np.zeros(frames.shape[:2] + (11,), bool)
    for r in range(4):
        for j in range(11):
            m = masks[:, 11*r + j]
            ok = m >= 0
            plain[ok, r::4, 1 + 3*j] ^= m[ok, None].astype(np.uint8)
            vis[ok, r::4, j] = True
    vis &= present[:, :, None]
    return plain, vis


def contiguity(counters, run_id):
    """prev_ok[g]: group g-1 is the immediately preceding counter of the same run."""
    c = counters.astype(np.int64)
    ok = np.zeros(len(c), bool)
    ok[1:] = (c[1:] == c[:-1] + 1) & (run_id[1:] == run_id[:-1])
    return ok


def neighbour(arr, prev_ok, direction):
    """Shift a (N,60,...) array by one slot in air order across contiguous groups.
    direction -1: value of the previous slot; +1: next slot. Invalid positions are zero/False."""
    N = arr.shape[0]
    flat = arr.reshape((N*60,) + arr.shape[2:])
    out = np.zeros_like(flat)
    valid = np.zeros(N*60, bool)
    if direction < 0:
        out[1:] = flat[:-1]
        valid[1:] = True
        starts = np.arange(N)*60
        valid[starts] = np.concatenate([[False], prev_ok[1:]])
    else:
        out[:-1] = flat[1:]
        valid[:-1] = True
        ends = np.arange(N)*60 + 59
        nxt = np.append(prev_ok[1:], False)
        valid[ends] = nxt
    return out.reshape(arr.shape), valid.reshape(N, 60)


def word_features(frames, present, masks, counters, run_id):
    """Per (group, slot) context arrays shared by training and prediction."""
    plain, vis = plaintext_view(frames, present, masks)
    prev_ok = contiguity(counters, run_id)
    pplain, pvalid = neighbour(plain, prev_ok, -1)
    pvis, _ = neighbour(vis, prev_ok, -1)
    ppres, _ = neighbour(present, prev_ok, -1)
    nplain, nvalid = neighbour(plain, prev_ok, +1)
    nvis, _ = neighbour(vis, prev_ok, +1)
    return dict(plain=plain, vis=vis, present=present,
                prev_plain=pplain, prev_vis=pvis & pvalid[..., None], prev_present=ppres & pvalid,
                next_plain=nplain, next_vis=nvis & nvalid[..., None])


def context_keys(F, g, s, j):
    """Context integers for words (g[i], s[i]) at mask position j (scalar)."""
    P = F['plain']
    mode = P[g, s, 0].astype(np.int64)
    p = 3*j
    L = (P[g, s, p] & 3).astype(np.int64) if j > 0 else np.zeros(len(g), np.int64)
    R = (P[g, s, 2 + p] >> 6).astype(np.int64)
    pm = np.where(F['prev_present'][g, s], F['prev_plain'][g, s, 0] >> 3, 32).astype(np.int64)
    pv_ok = F['prev_vis'][g, s, j]
    nv_ok = F['next_vis'][g, s, j]
    pv = F['prev_plain'][g, s, 1 + p].astype(np.int64)
    nv = F['next_plain'][g, s, 1 + p].astype(np.int64)
    pmode = F['prev_plain'][g, s, 0].astype(np.int64)
    nmode = F['next_plain'][g, s, 0].astype(np.int64)
    base = j + 16*mode
    L4 = (P[g, s, p] & 15).astype(np.int64) if j > 0 else np.zeros(len(g), np.int64)
    R4 = (P[g, s, 2 + p] >> 4).astype(np.int64)
    return dict(j=np.full(len(g), j, np.int64), mode=base, nb=base*16 + L*4 + R, nb2=base*256 + L4*16 + R4,
                pm=(base*16 + L*4 + R)*33 + pm,
                prev=(base*256 + pmode)*2, next=(base*256 + nmode)*2 + 1,
                pv=pv, nv=nv, pv_ok=pv_ok, nv_ok=nv_ok)


class ContextPrior:
    """Hierarchical bit-chain plaintext model for one mask position j."""

    def __init__(self, j, keys, values, weights, params):
        a = params
        self.j, self.params = j, params
        self.base = [Level(keys['j'], values, weights, 0), Level(keys['mode'], values, weights, 0),
                     Level(keys['mode'], values, weights, 2), Level(keys['mode'], values, weights, 8)]
        self.alphas = list(a['alpha_base'])
        if a['use_nb']:
            self.base.append(Level(keys['nb'], values, weights, 8))
            self.alphas.append(a['alpha_nb'])
        if a['use_pm']:
            self.base.append(Level(keys['pm'], values, weights, 8))
            self.alphas.append(a['alpha_pm'])
        if a['use_nb2']:
            self.base.append(Level(keys['nb2'], values, weights, 8))
            self.alphas.append(a['alpha_nb2'])
        self.adj = {}
        if a['use_adj']:
            for side, ok, ex in (('prev', keys['pv_ok'], keys['pv']), ('next', keys['nv_ok'], keys['nv'])):
                if ok.sum() < 50:
                    continue
                self.adj[side] = [Level(keys[side][ok], values[ok], weights[ok], 8, ex[ok], 2),
                                  Level(keys[side][ok], values[ok], weights[ok], 8, ex[ok], 8)]

    def logp(self, keys, local=None):
        """Leaf log-probabilities (words, 256). `local`: optional list of (words,256,2) count arrays from
        nearby groups of the same inputs file, applied after the global base chain."""
        n = len(keys['j'])
        p1 = np.full((n, 256), 0.5)
        names = ['j', 'mode', 'mode', 'mode'] + (['nb'] if self.params['use_nb'] else []) + \
                (['pm'] if self.params['use_pm'] else []) + (['nb2'] if self.params['use_nb2'] else [])
        for lev, name, a in zip(self.base, names, self.alphas):
            c = lev.counts(keys[name])
            p1 = (c[..., 1] + a*p1)/(c.sum(-1) + a)
        for c, a in zip(local or (), self.params['alpha_local']):
            p1 = (c[..., 1] + a*p1)/(c.sum(-1) + a)
        if self.adj:
            use_prev = keys['pv_ok'] & ('prev' in self.adj)
            use_next = keys['nv_ok'] & ~use_prev & ('next' in self.adj)
            for side, sel, ex in (('prev', use_prev, keys['pv']), ('next', use_next, keys['nv'])):
                if not sel.any() or side not in self.adj:
                    continue
                q = p1[sel]
                for lev, a in zip(self.adj[side], self.params['alpha_adj']):
                    c = lev.counts(keys[side][sel], ex[sel])
                    q = (c[..., 1] + a*q)/(c.sum(-1) + a)
                p1[sel] = q
        lp = leaf_logp(p1)
        eps = self.params['eps']
        if eps > 0:
            lp = np.logaddexp(np.log1p(-eps) + lp, np.log(eps/256))
        return lp


def local_counts(trans_j, run_id, wg, keys, params):
    """Counts from visible plaintext of groups within +-window of each word's group (same run)."""
    W, B = params['local_window'], params['local_block']
    tk, tv, tw = trans_j
    n = len(wg)
    out = [np.zeros((n, 256, 2)) for _ in params['local_orders']]
    if not W or tk is None:
        return None
    tg = tk['grp']
    for b0 in np.unique(wg // B)*B:
        sel = (wg >= b0) & (wg < b0 + B)
        runs = np.unique(run_id[wg[sel]])
        for run in runs:
            s2 = sel & (run_id[wg] == run)
            rec = (tg >= b0 - W) & (tg < b0 + B + W) & (run_id[tg] == run)
            if rec.sum() < 15:
                continue
            for o, arr in zip(params['local_orders'], out):
                lev = Level(tk['mode'][rec], tv[rec], tw[rec], o)
                arr[s2] = lev.counts(keys['mode'][s2])
    return out


# --------------------------------------------------------------------------- data

def load_npz(path):
    with np.load(path, allow_pickle=False) as d:
        return {k: d[k] for k in d.files}


def corpus_from_labels(path):
    """DEV label file -> (capture, frames, present, masks restricted to labelled groups, counters, run)."""
    d = load_npz(path)
    masks = d['mask_label'].astype(np.int16).copy()
    masks[~d['labelled']] = -1
    masks[:, 43] = 0           # index 43 (role 3, j = 10) is clear by convention in every group
    return dict(capture=str(d['capture']), frames=d['frames'], present=d['present'], masks=masks,
                counters=d['counters'], run_id=d['run_id'])


def training_records(src, weight):
    """(j -> keys dict, values, weights) for every visible plaintext word position."""
    F = word_features(src['frames'], src['present'], src['masks'], src['counters'], src['run_id'])
    out = {}
    for j in range(11):
        g, s = np.nonzero(F['vis'][:, :, j])
        if not len(g):
            continue
        keys = context_keys(F, g, s, j)
        keys['grp'] = g
        vals = F['plain'][g, s, 1 + 3*j].astype(np.int64)
        out[j] = (keys, vals, np.full(len(g), weight, np.float64))
    return out


def merge_records(parts):
    out = {}
    for rec in parts:
        for j, (k, v, w) in rec.items():
            out.setdefault(j, []).append((k, v, w))
    merged = {}
    for j, lst in out.items():
        keys = {name: np.concatenate([k[name] for k, _, _ in lst]) for name in lst[0][0]}
        merged[j] = (keys, np.concatenate([v for _, v, _ in lst]), np.concatenate([w for _, _, w in lst]))
    return merged


# --------------------------------------------------------------------------- rules

def group_slots(frames, present, counter):
    slots = []
    for s in range(60):
        phase, rest = divmod(s, 20)
        cycle, pos = divmod(rest, 4)
        if present[s]:
            toks = [f'{int(b):02x}' if j in PROJ else '??' for j, b in enumerate(frames[s])]
            receipt = 'received_du'
        else:
            toks = ['--']*33
            receipt = 'missing_du'
        slots.append(dict(slot=s, counter=int(counter), phase=phase, cycle=cycle, position=pos + 1,
                          receipt=receipt, octets=' '.join(toks)))
    return slots


def word_rules(frames, present, counter):
    """[(slot, check, allowed clear payload byte 0 values (256,) bool)] for conditional rule events."""
    out = []
    for section, report in field_sections(group_slots(frames, present, counter)).items():
        for row in report['slots']:
            if section == 'core_history' and row['outcome'] == 'abstain':
                continue
            check, kind, (start, end), domain, _ = event_spec(section, row, report)
            if kind != 'conditional':
                continue
            if start != 8 or not 8 < end <= 16:
                raise ValueError(f'unexpected rule target bits [{start},{end}) for {check}')
            allowed = np.isin(np.arange(256) >> (16 - end), sorted(set(domain)))
            out.append((int(row['slot']), check, allowed))
    return out


def role_rule_terms(frames, present, counter):
    """{role: dict(logp (256,), words, status)} for j = 0."""
    by_role = {}
    for s, check, allowed in word_rules(frames, present, counter):
        by_role.setdefault(s % 4, []).append((s, check, allowed))
    out = {}
    m = np.arange(256)
    for r, lst in by_role.items():
        viol = np.zeros(256, np.int64)
        for s, _, allowed in lst:
            viol += ~allowed[frames[s, 1] ^ m]
        ok = viol == 0
        if not ok.any():
            out[r] = dict(logp=np.zeros(256), words=len(lst), status='contradiction',
                          checks=sorted({c for _, c, _ in lst}))
            continue
        out[r] = dict(logp=np.where(ok, 0.0, HARD_PENALTY), words=len(lst),
                      status='constrained' if not ok.all() else 'unrestricted', allowed=int(ok.sum()),
                      checks=sorted({c for _, c, _ in lst}))
    return out


# --------------------------------------------------------------------------- prediction

def target_cells(inp, groups=None, seed=0):
    tg = inp['target'].astype(bool)
    g_all = np.flatnonzero(tg.any(axis=1))
    if groups is not None and groups < len(g_all):
        rng = np.random.default_rng(seed)
        g_all = np.sort(rng.choice(g_all, groups, replace=False))
    keep = np.zeros(len(tg), bool)
    keep[g_all] = True
    g, m = np.nonzero(tg & keep[:, None])
    return g, m


def apply_control(inp, control):
    """Return a copy of the inputs where each group's evidence comes from another group."""
    if control in (None, 'none'):
        return inp
    if control != 'wrong-group':
        raise ValueError(control)
    out = dict(inp)
    N = len(inp['group_id'])
    src = (np.arange(N) + N//2) % N
    for k in ('frames', 'present', 'known', 'counters', 'run_id'):
        out[k] = inp[k][src]
    # keep contiguity meaningful within the shifted copy
    return out


def predict(inp, variant='full', params=None, corpus_paths=DEFAULT_CORPUS, groups=None, seed=0,
            control=None, log=print):
    params = dict(PARAMS, **(params or {}))
    g_items, m_items = target_cells(inp, groups, seed)
    ev = apply_control(inp, control)
    roles, js = m_items // 11, m_items % 11
    n = len(g_items)
    logp = np.zeros((n, 256))
    info = dict(items=int(n), groups=int(len(np.unique(g_items))), variant=variant, control=control or 'none')

    if variant in ('modeprior', 'rules+modeprior'):
        from eval_mask_predictions import ModePrior, default_prior_files
        prior = ModePrior.fit([ROOT/p for p in corpus_paths] if corpus_paths else default_prior_files())
        items = dict(group_id=inp['group_id'][g_items], capture=inp['capture'][g_items], role=roles, j=js,
                     value=np.zeros(n, np.int64))
        P, held = prior.predict(dict(ev, group_id=inp['group_id']), items)
        logp += np.log(np.maximum(P, 1e-300))
        info['modeprior_held_out'] = held

    if variant in ('full', 'prior'):
        F = word_features(ev['frames'], ev['present'], ev['known'].astype(np.int16), ev['counters'], ev['run_id'])
        trans = training_records(dict(frames=ev['frames'], present=ev['present'], masks=ev['known'].astype(np.int16),
                                      counters=ev['counters'], run_id=ev['run_id']), params['trans_weight'])
        corpus = [corpus_from_labels(ROOT/p) for p in corpus_paths]
        caps_in = sorted(set(map(str, inp['capture'][g_items])))
        corpus_caps = [c['capture'] for c in corpus]
        info['corpus'] = corpus_caps
        info['held_out_captures'] = [c for c in caps_in if c in corpus_caps]
        corpus_recs = {c['capture']: training_records(c, 1.0) for c in corpus}
        # one model per held-out capture key ('' = no capture left out)
        hold_key = np.array([c if c in corpus_caps else '' for c in map(str, inp['capture'][g_items])])
        for hk in sorted(set(hold_key)):
            recs = merge_records([corpus_recs[c] for c in corpus_caps if c != hk] + [trans])
            for j in range(11):
                sel_items = np.flatnonzero((hold_key == hk) & (js == j))
                if not len(sel_items) or j not in recs:
                    continue
                model = ContextPrior(j, *recs[j], params)
                # words of these items
                wi, wg, ws = [], [], []
                for it in sel_items:
                    g, r = g_items[it], roles[it]
                    slots = np.arange(r, 60, 4)
                    slots = slots[ev['present'][g, slots]]
                    wi.append(np.full(len(slots), it))
                    wg.append(np.full(len(slots), g))
                    ws.append(slots)
                wi, wg, ws = (np.concatenate(x) for x in (wi, wg, ws))
                if not len(wi):
                    continue
                keys = context_keys(F, wg, ws, j)
                loc = local_counts(trans.get(j, (None, None, None)), ev['run_id'], wg, keys, params)
                lp = model.logp(keys, loc)                              # (words, 256) over clear values
                c = ev['frames'][wg, ws, 1 + 3*j].astype(np.int64)
                lpm = lp[np.arange(len(wi))[:, None], c[:, None] ^ np.arange(256)[None, :]]
                np.add.at(logp, wi, params['tau'][j]*lpm)
        info['params'] = {k: (list(v) if isinstance(v, tuple) else v) for k, v in params.items()}

    if variant in ('full', 'rules', 'rules+modeprior'):
        stats = dict(cells=0, constrained=0, contradiction=0, unrestricted=0, j0_items=0)
        cache = {}
        for it in np.flatnonzero(js == 0):
            g, r = g_items[it], roles[it]
            if g not in cache:
                cache[g] = role_rule_terms(ev['frames'][g], ev['present'][g], ev['counters'][g])
            stats['j0_items'] += 1
            term = cache[g].get(r)
            if term is None:
                continue
            stats['cells'] += 1
            stats[term['status']] += 1
            logp[it] += term['logp']
        info['rules'] = stats

    return dict(group=inp['group_id'][g_items], role=roles.astype(np.int8), j=js.astype(np.int8),
                logp=logp), info


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--inputs', required=True, type=Path)
    ap.add_argument('--out', required=True, type=Path)
    ap.add_argument('--groups', type=int, help='score a deterministic random subset of N target groups')
    ap.add_argument('--seed', type=int, default=0)
    ap.add_argument('--variant', default='full', choices=('full', 'prior', 'rules', 'modeprior', 'rules+modeprior'))
    ap.add_argument('--control', default='none', choices=('none', 'wrong-group'))
    ap.add_argument('--params', type=str, help='JSON overrides of the frozen parameters (development only)')
    ap.add_argument('--corpus', nargs='*', default=list(DEFAULT_CORPUS),
                    help='DEV label files for the fixed corpus (a capture present in the inputs is left out)')
    a = ap.parse_args()
    if 'truth' in a.inputs.name:
        raise SystemExit('refusing to read a truth file')
    inp = load_npz(a.inputs)
    params = json.loads(a.params) if a.params else None
    if params:
        for k, v in params.items():
            if isinstance(v, list):
                params[k] = tuple(v)
    pred, info = predict(inp, a.variant, params, a.corpus, a.groups, a.seed, a.control)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(a.out, format=FORMAT, method=f'{METHOD}:{a.variant}' + ('' if a.control == 'none' else f':{a.control}'),
                        split=str(inp['split']), task=str(inp['task']), **pred)
    info.update(inputs=str(a.inputs), inputs_sha256=sha256_file(a.inputs), script_sha256=sha256_file(__file__))
    a.out.with_suffix('.info.json').write_text(json.dumps(info, indent=1, default=str) + '\n')
    print(json.dumps({k: info[k] for k in ('items', 'groups', 'variant', 'control') if k in info} |
                     {'rules': info.get('rules')}))


if __name__ == '__main__':
    main()
