"""Score blind mask-byte predictions against the benchmark truth.

Inputs
  --truth   <split>.<task>.truth.npz from scripts/build_mask_benchmark.py tasks
  --inputs  the matching .inputs.npz (default: derived from --truth); needed for
            the mode-conditioned prior baseline
  --predictions  JSON or npz with one entry per (group id, role, byte j):

  JSON  {"format": "kcbs-mask-predictions/1", "method": "...", "split": "dev", "task": "T1",
         "items": [
           {"group": "<group id>", "role": 1, "j": 0, "logp": [256 numbers, null = -inf]},
           {"group": "...", "role": 1, "j": 1, "probs": [256 probabilities]},
           {"group": "...", "role": 1, "j": 2, "candidates": [17, 200], "candidate_probs": [0.7, 0.2]},
           {"group": "...", "role": 1, "j": 3, "candidates": [5, 9, 77], "confidence": 0.9}]}
  npz   arrays group (str), role (int), j (int) plus one of logp (n,256), probs (n,256) or
        candidates (n,K, -1 padded) with candidate_probs (n,K) and/or confidence (n,)

  Every prediction becomes a 256-way distribution. logp is soft-maxed (it need not be
  normalised). candidate_probs leave the remaining mass uniform over unlisted values.
  A ranked list with only a confidence c gets p(first) = c and the other 255 values
  share 1 - c with weight 1 + 1/(k-1) for listed rank k >= 2 and weight 1 for unlisted
  values. Ranks 2.. keep their listed order; the first candidate stays on top only when
  c exceeds the rank-2 share 2(1 - c)/(sum of weights), i.e. c above about 0.8% for a
  short list (a lower c is scored as given). Submit logp vectors for exact bit marginals.
  Target items with no prediction are scored as uniform and counted as missing.

Metrics (per task, per (role, j), per capture and on the strict-label subset)
  bytes  tie-aware top-1 and top-k accuracy, mid-rank of the truth, log2 loss,
         accuracy-vs-coverage at confidence thresholds (confidence = max probability),
         and the largest confidence-ranked set reaching 98% / 99.5% precision
  bits   bit marginals P(bit = 1) summed from the distribution (bit 0 = MSB); bits
         called at >= 98% and >= 99.5% precision (largest confidence-ranked set whose
         empirical precision reaches the target, cut only between distinct confidences),
         bits per group, and calibration at nominal confidence 0.98 / 0.995
  roles  within-role consistency: (group, role) cells whose target bytes are all
         recovered (top-1), and all called and correct at confidence thresholds
  --frozen-thresholds dev_metrics.json applies the DEV-chosen confidence thresholds
  to this set (the pre-registered way to score TEST).

Baselines computed on the same items
  uniform     every byte value equally likely
  mode_prior  per (exact mode byte, keyed payload bit) P(clear bit = 1) learned only from
              DEV clear role-0 plaintext; each mask bit is a log-likelihood vote over the
              received frames of its role (idea of work/understand/evs/p1_prior_vote.py).
              Items from a training capture are scored with that capture left out.
"""
import argparse
from collections import defaultdict
import datetime as dt
import hashlib
import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
FORMAT = 'kcbs-mask-eval/1'
PREDICTION_FORMAT = 'kcbs-mask-predictions/1'
SPLIT_JSON = ROOT/'examples/nov28/blind-mask-benchmark/split.json'
MASK_BYTES = 44
KEYED = np.arange(0, 32, 3)
BITS = ((np.arange(256)[:, None] >> (7 - np.arange(8))) & 1).astype(np.float64)   # (256, 8), MSB first
CONF_THRESHOLDS = (0.0, 0.25, 0.5, 0.75, 0.9, 0.95, 0.98, 0.99, 0.995, 0.999)
PRECISION_TARGETS = (0.98, 0.995)
TOPK = (1, 2, 4, 8, 16)
PROB_FLOOR = 1e-12
PRIOR_ALPHA = 0.5


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


def file_record(path):
    path = Path(path).resolve()
    try:
        shown = str(path.relative_to(ROOT))
    except ValueError:
        shown = str(path)
    return dict(path=shown, sha256=sha256_file(path))


# --------------------------------------------------------------------------- truth and items

def load_npz(path):
    with np.load(path, allow_pickle=False) as d:
        return {k: d[k] for k in d.files}


def truth_items(truth):
    """Flatten target cells into items ordered by (group, mask index)."""
    g, m = np.nonzero(truth['target'])
    value = truth['truth'][g, m].astype(np.int64)
    if np.any((value < 0) | (value > 255)):
        raise ValueError('target cell without a truth byte')
    strict = truth['strict'][g] if 'strict' in truth else np.zeros(len(g), bool)
    return dict(group=g, index=m, role=m // 11, j=m % 11, value=value,
                group_id=truth['group_id'][g], capture=truth['capture'][g], strict=strict.astype(bool))


# --------------------------------------------------------------------------- predictions

def normalise_logp(logp):
    logp = np.asarray(logp, np.float64)
    if logp.shape[-1] != 256 or np.isnan(logp).any() or np.isposinf(logp).any():
        raise ValueError('logp needs 256 finite-or--inf values per item')
    top = logp.max(axis=-1, keepdims=True)
    if np.isneginf(top).any():
        raise ValueError('logp row with no finite value')
    p = np.exp(logp - top)
    return p/p.sum(axis=-1, keepdims=True)


def normalise_probs(probs):
    probs = np.asarray(probs, np.float64)
    if probs.shape[-1] != 256 or not np.isfinite(probs).all() or (probs < 0).any():
        raise ValueError('probs needs 256 finite non-negative values per item')
    total = probs.sum(axis=-1, keepdims=True)
    if (total <= 0).any():
        raise ValueError('probs row sums to zero')
    return probs/total


def candidates_to_probs(candidates, candidate_probs=None, confidence=None):
    """256-way distribution from a ranked candidate list (see module docstring)."""
    cands = [int(c) for c in candidates if int(c) >= 0]
    if not cands or len(set(cands)) != len(cands) or any(c > 255 for c in cands):
        raise ValueError(f'candidates must be distinct bytes, got {list(candidates)}')
    p = np.zeros(256)
    listed = np.zeros(256, bool)
    listed[cands] = True
    if candidate_probs is not None:
        cp = np.asarray([float(x) for x in candidate_probs][:len(cands)], np.float64)
        if len(cp) != len(cands) or not np.isfinite(cp).all() or (cp < 0).any():
            raise ValueError('candidate_probs must give one finite non-negative value per candidate')
        total = cp.sum()
        if total > 1:
            cp, total = cp/total, 1.0
        p[cands] = cp
        rest = 1.0 - total
        if rest > 0:
            if listed.all():
                p /= p.sum()
            else:
                p[~listed] = rest/(~listed).sum()
        return p/p.sum()
    if confidence is None or not 0 <= float(confidence) <= 1:
        raise ValueError('a candidate list needs candidate_probs or a confidence in [0, 1]')
    c = float(confidence)
    weights = np.ones(256)
    for k, value in enumerate(cands[1:], start=2):
        weights[value] = 1 + 1/(k - 1)
    weights[cands[0]] = 0
    p = (1 - c)*weights/weights.sum()
    p[cands[0]] = c
    return p/p.sum()


def read_predictions(path):
    """{(group id, role, j): distribution} and metadata from a JSON or npz predictions file."""
    path = Path(path)
    table, meta = {}, {}

    def put(key, p):
        if key in table:
            raise ValueError(f'duplicate prediction for {key}')
        table[key] = p

    if path.suffix == '.npz':
        d = load_npz(path)
        groups, roles, js = d['group'], d['role'].astype(int), d['j'].astype(int)
        if 'logp' in d:
            dist = normalise_logp(d['logp'])
        elif 'probs' in d:
            dist = normalise_probs(d['probs'])
        elif 'candidates' in d:
            cp = d.get('candidate_probs')
            conf = d.get('confidence')
            dist = np.array([candidates_to_probs(d['candidates'][i], None if cp is None else cp[i],
                                                 None if conf is None else conf[i]) for i in range(len(groups))])
        else:
            raise ValueError('npz predictions need logp, probs or candidates')
        for g, r, j, p in zip(groups, roles, js, dist):
            put((str(g), int(r), int(j)), p)
        for key in ('method', 'split', 'task'):
            if key in d:
                meta[key] = str(d[key])
        return table, meta
    doc = json.loads(path.read_text(encoding='utf-8'))
    items = doc.get('items', doc.get('predictions'))
    if not isinstance(items, list):
        raise ValueError('JSON predictions need an "items" list')
    for item in items:
        key = (str(item['group']), int(item['role']), int(item['j']))
        if 'logp' in item:
            p = normalise_logp([-np.inf if v is None else float(v) for v in item['logp']])
        elif 'probs' in item:
            p = normalise_probs(item['probs'])
        elif 'candidates' in item:
            p = candidates_to_probs(item['candidates'], item.get('candidate_probs'), item.get('confidence'))
        else:
            raise ValueError(f'prediction {key} has no logp, probs or candidates')
        put(key, p)
    meta = {k: doc[k] for k in ('format', 'method', 'split', 'task') if k in doc}
    return table, meta


def align(table, items):
    """Distribution per item (uniform where missing), provided flags, count of unused entries."""
    n = len(items['value'])
    P = np.full((n, 256), 1/256)
    provided = np.zeros(n, bool)
    keys = set()
    for i, (g, r, j) in enumerate(zip(items['group_id'], items['role'], items['j'])):
        key = (str(g), int(r), int(j))
        keys.add(key)
        if key in table:
            P[i] = table[key]
            provided[i] = True
    return P, provided, len(set(table) - keys)


# --------------------------------------------------------------------------- metrics

def byte_scores(P, value):
    """Per item: p(truth), confidence, tie-aware top-k, mid-rank and log2 loss."""
    n = len(value)
    pt = P[np.arange(n), value]
    greater = (P > pt[:, None]).sum(axis=1)
    ties = (P == pt[:, None]).sum(axis=1)            # includes the truth itself
    rank = 1 + greater + 0.5*(ties - 1)
    topk = {k: np.clip((k - greater)/ties, 0, 1) for k in TOPK}
    return dict(p_true=pt, confidence=P.max(axis=1), rank=rank, topk=topk,
                log2_loss=-np.log2(np.maximum(pt, PROB_FLOOR)))


def coverage_curve(conf, correct, thresholds=CONF_THRESHOLDS):
    rows = []
    for t in thresholds:
        called = conf >= t
        rows.append(dict(threshold=t, called=int(called.sum()), coverage=round(float(called.mean()), 6) if len(conf) else 0,
                         accuracy=round(float(correct[called].mean()), 6) if called.any() else None))
    return rows


def at_precision(conf, correct, target):
    """Largest confidence-ranked set with empirical precision >= target (cuts between distinct values)."""
    conf = np.asarray(conf, np.float64).ravel()
    correct = np.asarray(correct, np.float64).ravel()
    if not len(conf):
        return dict(called=0, correct=0.0, precision=None, threshold=None)
    order = np.argsort(-conf, kind='stable')
    c, ok = conf[order], np.cumsum(correct[order])
    count = np.arange(1, len(c) + 1)
    boundary = np.append(c[1:] != c[:-1], True)
    good = boundary & (ok >= target*count - 1e-9)
    if not good.any():
        return dict(called=0, correct=0.0, precision=None, threshold=None)
    i = np.flatnonzero(good)[-1]
    return dict(called=int(count[i]), correct=round(float(ok[i]), 3), precision=round(float(ok[i]/count[i]), 6),
                threshold=float(c[i]))


def at_threshold(conf, correct, threshold):
    called = np.asarray(conf).ravel() >= threshold
    correct = np.asarray(correct, np.float64).ravel()
    return dict(threshold=threshold, called=int(called.sum()), correct=round(float(correct[called].sum()), 3),
                precision=round(float(correct[called].mean()), 6) if called.any() else None)


def bit_scores(P, value):
    p1 = P @ BITS                                         # (n, 8)
    truth = BITS[value]                                   # (n, 8)
    conf = np.maximum(p1, 1 - p1)
    correct = np.where(np.isclose(p1, 0.5), 0.5, ((p1 > 0.5) == (truth > 0.5)).astype(np.float64))
    return p1, conf, correct


def summarize(P, items, frozen=None, detail=True):
    """Metrics for one prediction matrix over one set of items."""
    value = items['value']
    n = len(value)
    groups = len(np.unique(items['group'])) if n else 0
    out = dict(items=int(n), groups=int(groups))
    if not n:
        return out
    s = byte_scores(P, value)
    top1 = s['topk'][1]
    out['bytes'] = dict(
        top1_accuracy=round(float(top1.mean()), 6),
        topk_accuracy={str(k): round(float(v.mean()), 6) for k, v in s['topk'].items()},
        mean_rank=round(float(s['rank'].mean()), 3), median_rank=float(np.median(s['rank'])),
        mean_log2_loss=round(float(s['log2_loss'].mean()), 4),
        mean_confidence=round(float(s['confidence'].mean()), 6),
        coverage=coverage_curve(s['confidence'], top1),
        at_precision={str(t): at_precision(s['confidence'], top1, t) for t in PRECISION_TARGETS})
    _, bconf, bcorrect = bit_scores(P, value)
    out['bits'] = dict(
        bits=int(bconf.size), accuracy=round(float(bcorrect.mean()), 6),
        at_precision={}, at_nominal_confidence={})
    for t in PRECISION_TARGETS:
        row = at_precision(bconf, bcorrect, t)
        row['bits_per_group'] = round(row['called']/groups, 4)
        out['bits']['at_precision'][str(t)] = row
        nominal = at_threshold(bconf, bcorrect, t)
        nominal['bits_per_group'] = round(nominal['called']/groups, 4)
        out['bits']['at_nominal_confidence'][str(t)] = nominal
    if frozen:
        out['bytes']['frozen'] = {}
        out['bits']['frozen'] = {}
        for t in PRECISION_TARGETS:
            tb = frozen.get('bytes', {}).get(str(t))
            if tb is not None:
                out['bytes']['frozen'][str(t)] = at_threshold(s['confidence'], top1, tb)
            tbit = frozen.get('bits', {}).get(str(t))
            if tbit is not None:
                row = at_threshold(bconf, bcorrect, tbit)
                row['bits_per_group'] = round(row['called']/groups, 4)
                out['bits']['frozen'][str(t)] = row
    out['roles'] = role_consistency(items, top1, s['confidence'])
    if detail:
        out['per_role_j'] = {}
        for m in np.unique(items['index']):
            sel = items['index'] == m
            sub = {k: v[sel] for k, v in items.items()}
            out['per_role_j'][f'r{m // 11}j{m % 11}'] = summarize(P[sel], sub, frozen, detail=False)
        out['per_capture'] = {}
        for cap in np.unique(items['capture']):
            sel = items['capture'] == cap
            sub = {k: v[sel] for k, v in items.items()}
            row = summarize(P[sel], sub, frozen, detail=False)
            out['per_capture'][str(cap)] = dict(items=row['items'], groups=row['groups'],
                                                top1_accuracy=row['bytes']['top1_accuracy'],
                                                mean_rank=row['bytes']['mean_rank'],
                                                bits_at_precision=row['bits']['at_precision'])
    return out


def role_consistency(items, top1, conf):
    """(group, role) cells: all target bytes recovered at top-1, and all called and correct."""
    cells = defaultdict(list)
    for i, (g, r) in enumerate(zip(items['group'], items['role'])):
        cells[(int(g), int(r))].append(i)
    exact = np.array([np.prod(top1[ix]) for ix in cells.values()])
    lowest = np.array([conf[ix].min() for ix in cells.values()])
    called = {}
    for t in PRECISION_TARGETS:
        sel = lowest >= t
        called[str(t)] = dict(called=int(sel.sum()), all_correct=round(float(exact[sel].sum()), 3))
    return dict(cells=len(cells), bytes_per_cell=round(len(top1)/max(len(cells), 1), 3),
                all_top1_correct=round(float(exact.sum()), 3), all_top1_rate=round(float(exact.mean()), 6),
                all_called_at_confidence=called)


def evaluate(P, items, frozen=None):
    out = summarize(P, items, frozen)
    if items['strict'].any() and not items['strict'].all():
        sel = items['strict']
        out['strict_subset'] = summarize(P[sel], {k: v[sel] for k, v in items.items()}, frozen, detail=False)
    return out


# --------------------------------------------------------------------------- baselines

def uniform_probs(n):
    return np.full((n, 256), 1/256)


class ModePrior:
    """Per (exact mode byte, keyed payload bit) clear-bit counts from role-0 plaintext."""

    def __init__(self, counts, sources):
        self.counts = counts                       # capture -> (256 modes, 88 bits, 2) counts
        self.sources = sources
        self.total = sum(counts.values())

    @classmethod
    def fit(cls, paths):
        counts, sources = {}, []
        for path in paths:
            d = load_npz(path)
            capture = str(d['capture'])
            c = counts.setdefault(capture, np.zeros((256, 88, 2), np.int64))
            frames0 = d['frames'][:, 0::4]                         # (N, 15, 33) role-0 frames
            present0 = d['present'][:, 0::4]
            mask0 = d['mask_label'][:, :11]
            use = d['labelled'] & (mask0 >= 0).all(axis=1)
            plain = frames0[use][:, :, 1 + KEYED] ^ mask0[use][:, None, :].astype(np.uint8)
            keep = present0[use]
            modes = frames0[use][:, :, 0][keep]
            bits = np.unpackbits(plain[keep], axis=1)              # (frames, 88)
            for b in range(88):
                np.add.at(c[:, b, :], (modes, bits[:, b]), 1)
            sources.append(dict(file_record(path), capture=capture, groups=int(use.sum()), frames=int(keep.sum())))
        return cls(counts, sources)

    def counts_for(self, capture):
        """Counts with `capture` left out when it is a training capture (all zeros, hence an
        uninformative prior, when it was the only one)."""
        if capture in self.counts:
            return self.total - self.counts[capture], True
        return self.total, False

    def item_probs(self, frames, present, j, counts):
        """Distribution of one mask byte from the received frames of its role."""
        frames = frames[present]
        if not len(frames):
            return np.full(256, 1/256)
        n = counts[frames[:, 0], 8*j:8*j + 8, :] + PRIOR_ALPHA                 # (f, 8, 2)
        logit1 = np.log(n[..., 1]) - np.log(n[..., 0])                        # log P(clear 1)/P(clear 0)
        recv = np.unpackbits(frames[:, 1 + 3*j][:, None], axis=1).astype(np.float64)   # (f, 8)
        # mask bit 0 -> clear = recv; mask bit 1 -> clear = 1 - recv
        llr = ((2*recv - 1)*logit1).sum(axis=0)                               # log P(m=0)/P(m=1)
        lp0 = -np.logaddexp(0, -llr)
        lp1 = -np.logaddexp(0, llr)
        logp = BITS @ lp1 + (1 - BITS) @ lp0
        return normalise_logp(logp)

    def predict(self, inputs, items):
        index = {str(g): i for i, g in enumerate(inputs['group_id'])}
        P = np.empty((len(items['value']), 256))
        held_out = set()
        cache = {}
        for i, (gid, cap, r, j) in enumerate(zip(items['group_id'], items['capture'], items['role'], items['j'])):
            cap = str(cap)
            if cap not in cache:
                cache[cap] = self.counts_for(cap)
                if cache[cap][1]:
                    held_out.add(cap)
            g = index[str(gid)]
            P[i] = self.item_probs(inputs['frames'][g, r::4], inputs['present'][g, r::4], int(j), cache[cap][0])
        return P, sorted(held_out)


def default_prior_files():
    if not SPLIT_JSON.exists():
        raise SystemExit(f'--prior-train not given and {SPLIT_JSON} is missing')
    doc = json.loads(SPLIT_JSON.read_text(encoding='utf-8'))
    return [ROOT/c['output']['path'] for c in doc['splits']['dev']['captures']]


def frozen_thresholds(path, key):
    doc = json.loads(Path(path).read_text(encoding='utf-8'))
    node = doc['metrics']
    for part in key.split('.'):
        node = node[part]
    return dict(bytes={t: node['bytes']['at_precision'][t]['threshold'] for t in node['bytes']['at_precision']},
                bits={t: node['bits']['at_precision'][t]['threshold'] for t in node['bits']['at_precision']})


def save_predictions(path, items, P, method, split, task):
    np.savez_compressed(path, format=PREDICTION_FORMAT, method=method, split=split, task=task,
                        group=items['group_id'], role=items['role'].astype(np.int8),
                        j=items['j'].astype(np.int8), logp=np.log(np.maximum(P, 1e-300)))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--truth', required=True, type=Path)
    ap.add_argument('--inputs', type=Path, help='default: the truth path with .truth.npz -> .inputs.npz')
    ap.add_argument('--predictions', type=Path, help='JSON or npz predictions; omit to score baselines only')
    ap.add_argument('--no-baselines', action='store_true', help='skip the uniform and mode-prior baselines')
    ap.add_argument('--prior-train', type=Path, nargs='+',
                    help='DEV label files for the mode prior (default: the dev captures in split.json)')
    ap.add_argument('--frozen-thresholds', type=Path, help='metrics JSON from DEV whose thresholds are applied here')
    ap.add_argument('--frozen-key', default='method',
                    help='which metrics block of --frozen-thresholds supplies them (e.g. baselines.mode_prior)')
    ap.add_argument('--write-baseline-predictions', type=Path,
                    help='directory for <split>.<task>.<baseline>.npz prediction files')
    ap.add_argument('--out', required=True, type=Path)
    a = ap.parse_args()

    truth = load_npz(a.truth)
    split, task = str(truth['split']), str(truth['task'])
    items = truth_items(truth)
    frozen = frozen_thresholds(a.frozen_thresholds, a.frozen_key) if a.frozen_thresholds else None
    report = dict(format=FORMAT, created=dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(),
                  truth=file_record(a.truth), split=split, task=task, items=int(len(items['value'])),
                  groups=int(len(np.unique(items['group']))), metrics={})
    if frozen:
        report['frozen_thresholds'] = dict(file_record(a.frozen_thresholds), key=a.frozen_key, values=frozen)
    if a.predictions:
        table, meta = read_predictions(a.predictions)
        for key in ('split', 'task'):
            if key in meta and meta[key] != report[key]:
                raise SystemExit(f'predictions are for {key} {meta[key]!r}, truth is {report[key]!r}')
        P, provided, unused = align(table, items)
        report['predictions'] = dict(file_record(a.predictions), method=meta.get('method'),
                                     provided=int(provided.sum()), missing=int((~provided).sum()),
                                     unused_entries=unused)
        report['metrics']['method'] = evaluate(P, items, frozen)
    if not a.no_baselines:
        inputs_path = a.inputs or Path(str(a.truth).replace('.truth.npz', '.inputs.npz'))
        inputs = load_npz(inputs_path)
        if not np.array_equal(inputs['group_id'], truth['group_id']):
            raise SystemExit('inputs and truth list different groups')
        prior = ModePrior.fit(a.prior_train or default_prior_files())
        Pu = uniform_probs(len(items['value']))
        Pp, held_out = prior.predict(inputs, items)
        report['inputs'] = file_record(inputs_path)
        report['prior'] = dict(training=prior.sources, alpha=PRIOR_ALPHA, modes_seen=int((prior.total.sum(axis=(1, 2)) > 0).sum()),
                               held_out_captures=held_out,
                               note='trained on DEV labelled role-0 plaintext only; items from a training '
                                    'capture are scored with that capture left out')
        report['metrics']['baselines'] = dict(uniform=evaluate(Pu, items, frozen), mode_prior=evaluate(Pp, items, frozen))
        if a.write_baseline_predictions:
            a.write_baseline_predictions.mkdir(parents=True, exist_ok=True)
            for name, P in (('uniform', Pu), ('mode_prior', Pp)):
                save_predictions(a.write_baseline_predictions/f'{split}.{task}.{name}.npz', items, P, name, split, task)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(report, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    brief = {}
    for name, block in [('method', report['metrics'].get('method'))] + list(report['metrics'].get('baselines', {}).items()):
        if block and 'bytes' in block:
            brief[name] = dict(top1=block['bytes']['top1_accuracy'], mean_rank=block['bytes']['mean_rank'],
                               bits_per_group_98=block['bits']['at_precision']['0.98']['bits_per_group'],
                               bits_per_group_995=block['bits']['at_precision']['0.995']['bits_per_group'])
    print(json.dumps(dict(split=split, task=task, items=report['items'], groups=report['groups'], summary=brief)))


if __name__ == '__main__':
    main()
