#!/usr/bin/env python3
"""Generate KCBS-2 text-tail key labels from the text carousel (a label generator, not a mask method).

Guarded port of KoryoFront/kcbs2-drm-decode scripts/recover_text_keys.py (2fc071b) with the
record grammar of ef30262/71d1aaa (parse_text_records.py, extended=True). Every group (counter c,
phases 0-2) shares one 16-byte text-tail key: tail(3c+p) = du[698:714] = plaintext XOR ks[0..15].
The scrolling text repeats every P 16-byte blocks (the carousel period, e.g. 969 or 700).

  1. proposals, recall only and never output on their own: a mandatory 0xBB fill block (fill), a
     fill block followed by an item-opening header (opening), or an eight-character fragment of a
     decoded-text corpus (phrase; skgsara's method). The corpus never includes texts from sealed
     TEST captures or registered live sources (EXCLUDED_SOURCES, applied to every corpus path).
  2. period: the dominant repeat distance (>= 60 blocks) of records with the same (sequence, final,
     text), confirmed when gate-A recurrence at P beats P+-1..3 (or taken from --period, and still
     confirmed the same way). No confirmed period: no new key.
  3. gate A: a key is confirmed when one of its blocks lies in a CRC-valid record with the full
     structure (header, UTF-16LE text, zero padding, mandatory fill) whose (block offset mod P,
     sequence, final, text) also occurs in another carousel copy, and whose CRC-covered bytes
     span at least two groups. A record inside one group confirms nothing: [fill, R, fill] and
     [R, fill, R] (R a one-block final record) are the same ciphertext under two keys, both
     CRC-valid and recurring. The optional fill block after a final record confirms nothing either.
  4. XOR-link: a confirmed group's plaintext block is the plaintext m*P blocks away (m = +-1..4).
     An unconfirmed group is linked only when exactly one key is produced by two of its phases at
     one displacement (strict), and that key is produced by two phases at a second displacement
     too (default rule strict2; 'strict+second' only asks for any phase at the second displacement).
     Source blocks whose plaintext is ambiguous (0xBB fill, all zero, or a value seen at two
     different carousel positions) are not evidence: a wrong link of the phase-0/phase-2 swap kind
     needs equal blocks 2 or 4 positions apart, and a carousel edit that shifts content by 1-2
     blocks between passes would otherwise reproduce it at every displacement at once.
     Source blocks must also lie in a gate-A record (CRC-valid, recurring, CRC spanning two groups): a trusted key that
     no recurring record backs is not evidence. This is what stops a wrong seed whose error repeats
     in every carousel copy (the supplied archives hold such families, e.g. phases 0 and 1 swapped
     at one carousel position in all four passes) from being copied onto the remaining copies.
     Before any link, each seed is audited the same way against the other seeds: a seed whose own
     strict2 link from record-backed copies gives a different key is dropped from the seeds and
     reported (a CRC-16 collision in a supplied key was found this way on DEV data).
  5. wrong-period controls, mandatory: step 4 is repeated at P+-1..3 with the same trusted set in
     every round. Any control link blocks XOR-link output for the capture, which is then re-run
     without XOR-link (so no gate-A key that needed a linked block survives either).
  6. --evs-check (optional): each new key's role-0 frames are decoded alone with the traced stock
     decoder, and again with another new key (control). A key whose role-0 frames raise any decoder
     flag (bfi or BER_detect) is rejected and the capture re-run without it. This is a necessary
     check of ks[0..10] only: on review data it missed about 20% of wrong keys, and it cannot see
     ks[11..15] at all.

Writes keys.npz (counters u32, ks (N,16) u8, provenance in {seed, fill, opening, phrase, xorlink},
round) and report.json with the content SHA-256 of counters (u32 little-endian) || ks. A key covers
the 16-byte text tail only: ks[0..10] are the role-0 mask bytes and ks[11..15] the role-1 bytes
j = 0..4; nothing here bears on ks[16..42], codec identity, or audio.
"""
import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass
import datetime as dt
import fnmatch
import glob
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

import numpy as np

from parse_text_records import scan_records
from tail_fill_audit import crc, text_unit

ROOT = Path(__file__).resolve().parents[1]
FORMAT = 'kcbs-carousel-keys/1'
BLOCK = 16
TAIL = slice(698, 714)
DU_BYTES = 716
CAROUSEL_SPAN = 4                         # carousel copies searched on each side for XOR-link
MIN_PERIOD_DISTANCE = 60                  # repeat distances below this are not carousel periods
PERIOD_CANDIDATES = 5                     # top repeat distances checked by gate-A recurrence
MIN_CONFIRM_RECORDS = 4                   # recurring records needed to confirm a period
CONTROL_OFFSETS = (-3, -2, -1, 1, 2, 3)   # wrong-period controls, always run
LINK_RULES = ('strict2', 'strict+second', 'strict', 'upstream')
DEFAULT_RULE = 'strict2'
PROVENANCE = ('seed', 'fill', 'opening', 'phrase', 'xorlink')
OPEN_HEADER = (0x45, 0xFC)
AMBIGUOUS_ALWAYS = (b'\xbb' * 16, bytes(16))   # fill and zero blocks never anchor a link
DEFAULT_CORPUS = ('contrib/kcbsdrm/reference/items_*.json', 'contrib/kcbsdrm/reference/titles_*.json')
DEFAULT_SPLIT = 'examples/nov28/blind-mask-benchmark/split.json'
DEFAULT_DECODER = 'work/benchmark/tools/evs_dec_traced/EVS_dec_traced'
SEED_SPLITS = ('dev', 'nov27-dev')        # splits whose cleaned labels may seed without override
# The group counter is a clock (one count per 1.2 s group). Data units whose counters fall in these
# windows are refused whatever the file is called (a renamed copy passes the path patterns below).
SEALED_COUNTER_WINDOWS = (
    (43_730_000, 43_772_000, 'sealed TEST captures nov25-2242 to nov26-1008 (2026-11-25 21:40 to 11-26 11:40 KST)'),
)

# Never a phrase source, and refused as --data-units/--seeds input without --allow-sealed-input.
# Patterns are matched (case-insensitively) against the given and the resolved POSIX path.
EXCLUDED_SOURCES = (
    ('*2242*', 'sealed TEST capture nov25-2242'),
    ('*0500*', 'sealed TEST capture nov26-0500'),
    ('*0642*', 'sealed TEST capture nov26-0642'),
    ('*1008*', 'sealed TEST capture nov26-1008'),
    ('*2026-11-26*', 'every 2026-11-26 capture is in the sealed TEST split'),
    ('*nov26*', 'every 2026-11-26 capture is in the sealed TEST split'),
    ('*titles_2026-11-25*', 'openings solved jointly with the sealed nov25-2242 capture'),
    ('*bulletin_2026-11-25_all*', 'bulletin merged over all 2026-11-25 captures incl. nov25-2242'),
    ('*kcbs2_text_*', 'final plaintext assembled across captures'),
    ('*2026-03-16*', 'March transfer capture'),
    ('*mar16*', 'March transfer capture'),
    ('*signon*', 'March transfer capture'),
    ('*/dumps/*', 'March transfer capture'),
    ('*member-3205*', 'registered live source: member 3205 kHz recording'),
    ('*member-text*', 'registered live source: member 3205 kHz recording'),
    ('*edogawa*', 'registered live source: Edogawa late-payload / swb-gsc'),
    ('*late-payload*', 'registered live source: Edogawa late-payload'),
    ('*swb-gsc*', 'registered live source: Edogawa swb-gsc'),
    ('*gsc-fields*', 'registered live source: gsc-fields'),
    ('*/work/acquire/*', 'prospective acquisition recordings'),
    ('*/work/catchup/next/c', 'held-out catch-up set C'),
    ('*/work/catchup/next/c/*', 'held-out catch-up set C'),
    ('*/quarantine/*', 'quarantined keys for the registered live set'),
    ('*/verify/runs/*', 'sealed verification runs'),
    ('*/benchmark/tasks/test.*', 'sealed benchmark task'),
    ('*/benchmark/tasks/syn-test.*', 'sealed benchmark task'),
    ('*/benchmark/tasks/transfer.*', 'sealed benchmark task'),
)


def excluded_reason(path, extra=()):
    """Why a path may not be read as a phrase source or unsealed input, or None."""
    names = {str(path).replace('\\', '/').lower(), Path(path).resolve().as_posix().lower()}
    for pattern, reason in tuple(EXCLUDED_SOURCES) + tuple((p, 'excluded on the command line') for p in extra):
        if any(fnmatch.fnmatchcase(name, pattern.lower()) for name in names):
            return f'{reason} ({pattern})'
    return None


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


def content_sha256(counters, ks):
    """SHA-256 of counters as u32 little-endian followed by the (N, 16) key bytes."""
    return hashlib.sha256(np.asarray(counters, '<u4').tobytes()
                          + np.ascontiguousarray(ks, np.uint8).tobytes()).hexdigest()


def rel(path):
    path = Path(path).resolve()
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


# --------------------------------------------------------------------------- phrase corpus

@dataclass
class Corpus:
    phrases: np.ndarray        # (n, 8) uint16 eight-unit fragments
    words: dict                # n -> set of n-character substrings, n = 1..4
    files: list
    texts: int


_CHARSET = None


def charset():
    global _CHARSET
    if _CHARSET is None:
        _CHARSET = np.array([text_unit(i) or i in (0, 0x3000) for i in range(65536)])
    return _CHARSET


def resolve_corpus(paths=None, extra_excludes=()):
    """Corpus files after the hard-coded exclusion list. Explicitly named excluded files are an error."""
    used, excluded = [], []
    for spec in (paths or [str(ROOT/p) for p in DEFAULT_CORPUS]):
        explicit = not glob.has_magic(str(spec)) and not Path(spec).is_dir()
        if Path(spec).is_dir():
            matches = sorted(str(p) for p in Path(spec).iterdir() if p.suffix in ('.json', '.txt'))
        else:
            matches = sorted(glob.glob(str(spec))) or ([str(spec)] if explicit else [])
        for name in matches:
            reason = excluded_reason(name, extra_excludes)
            if reason is None:
                used.append(Path(name))
            elif explicit and paths:
                raise ValueError(f'phrase corpus {name} is excluded: {reason}')
            else:
                excluded.append(dict(path=rel(name), reason=reason))
    return sorted(set(used)), excluded


def corpus_texts(path):
    """Decoded texts and item openings from items_*.json, titles_*.json, or one text per line."""
    path = Path(path)
    if path.suffix == '.txt':
        return {line for line in path.read_text(encoding='utf-8').splitlines() if line.strip()}, set()
    data = json.loads(path.read_text(encoding='utf-8'))
    if isinstance(data, dict) and isinstance(data.get('items'), list):
        return {row['text'] for item in data['items'] for row in item if row.get('ok')}, set()
    if isinstance(data, list) and all(isinstance(r, dict) and 'opening' in r for r in data):
        openings = set()
        for row in data:
            o = row['opening']
            openings.update((o, o.replace('\n', '\r'), o.replace('\n', '\r\n')))
        return set(), openings
    raise ValueError(f'{path}: not an items_*.json, titles_*.json or .txt phrase source')


def build_corpus(files):
    texts, openings = set(), set()
    for path in files:
        t, o = corpus_texts(path)
        texts |= t
        openings |= o
    texts |= openings
    words = {n: {s[i:i + n] for s in texts for i in range(len(s) - n + 1)} for n in (1, 2, 3, 4)}
    eight = {s[i:i + 8].encode('utf-16le') for s in texts for i in range(len(s) - 7)}
    for opening in openings:       # opening title blocks: three zero units, then the text
        padded = ('\x00\x00\x00' + opening).ljust(31, '\x00')[:31]
        eight.update(padded[i:i + 8].encode('utf-16le') for i in range(len(padded) - 7))
    eight = {e for e in eight if len(e) == 16}
    phrases = (np.stack([np.frombuffer(b, '<u2') for b in sorted(eight)]) if eight
               else np.zeros((0, 8), np.uint16))
    return Corpus(phrases, words, [rel(f) for f in files], len(texts))


def empty_corpus():
    return Corpus(np.zeros((0, 8), np.uint16), {n: set() for n in (1, 2, 3, 4)}, [], 0)


def corpus_sha256(corpus):
    h = hashlib.sha256(corpus.phrases.tobytes())
    for n in sorted(corpus.words):
        h.update('\x1f'.join(sorted(corpus.words[n])).encode('utf-8'))
    return h.hexdigest()


# --------------------------------------------------------------------------- proposals (recall only)

def _opening_header(first, second):
    return (first & 0x7F) == OPEN_HEADER[0] and second == OPEN_HEADER[1]


def _body_header(first, second):
    length = (first & 7) * 16 + (second & 15)
    return (((first & 0x7F) == 5 and length == 92)
            or (0x20 <= (first & 0x7F) <= 0x27 and 2 <= length <= 92 and length % 2 == 0))


def propose(parts, corpus):
    """One candidate key for a group and its class, or (None, None). Recall only; not a check.

    parts maps phase -> 16-byte tail. Upstream's rule: a fill block whose next block decrypts to a
    record header (with corpus trigrams), or to an item-opening header; otherwise the best-scoring
    phrase fragment, unique and above an n-gram score threshold.
    """
    phases = sorted(parts)
    data = np.stack([parts[p] for p in phases]).view('<u2').reshape(len(phases), 8)
    fills = {}
    for phase, row in parts.items():
        key = row ^ 0xBB
        after = parts.get(phase + 1)
        header = opening = False
        if after is not None:
            first, second = (after ^ key)[:2].tolist()
            opening = _opening_header(first, second)
            header = opening or _body_header(first, second)
        others = [(v ^ key).tobytes().decode('utf-16le', errors='replace')
                  for p, v in parts.items() if p != phase]
        trigrams = sum(s[i:i + 3] in corpus.words[3] for s in others for i in range(6))
        if (header and trigrams >= 2) or opening or (phase == 2 and len(parts) == 3 and trigrams >= 4):
            fills[key.tobytes()] = ((header, trigrams), opening)
    if fills:
        best = max(score for score, _ in fills.values())
        winners = [k for k, (score, _) in fills.items() if score == best]
        if len(winners) == 1:
            return np.frombuffer(winners[0], np.uint8).copy(), ('opening' if fills[winners[0]][1] else 'fill')
    if not len(corpus.phrases):
        return None, None
    table = charset()
    candidates = set()
    for row in data:
        possible = corpus.phrases ^ row
        clear = possible[:, None, :] ^ data
        good = table[clear].sum(axis=(1, 2)) >= data.size - 3
        candidates.update(key.tobytes() for key in possible[good])
    best_score, best = -1, None
    for key in sorted(candidates):
        clear = data ^ np.frombuffer(key, '<u2')
        strings = []
        for stretch in np.split(clear, np.flatnonzero(np.diff(phases) > 1) + 1):
            strings.extend(''.join(chr(int(x)) for x in stretch.ravel()).split('뮻' * 8))
        score = sum(s[i:i + n] in gram for s in strings for n, gram in corpus.words.items()
                    for i in range(len(s) - n + 1))
        if score > best_score:
            best_score, best = score, key
        elif score == best_score:
            best = None
    if best is None or best_score <= (24 if len(phases) == 3 else 16):
        return None, None
    return np.frombuffer(best, np.uint8).copy(), 'phrase'


def tails_sha256(tails):
    h = hashlib.sha256()
    for t in sorted(tails):
        h.update(int(t).to_bytes(8, 'little') + tails[t].tobytes())
    return h.hexdigest()


def all_proposals(tails, corpus, cache=None):
    """Proposals for every received group with >= 2 phases (seed-independent, so cacheable)."""
    data_sha, corp_sha = tails_sha256(tails), corpus_sha256(corpus)
    if cache is not None and Path(cache).exists():
        with np.load(cache, allow_pickle=False) as z:
            if str(z['tails_sha256']) == data_sha and str(z['corpus_sha256']) == corp_sha:
                return {int(c): (k.copy(), str(kind)) for c, k, kind in zip(z['counters'], z['ks'], z['kind'])}, True
    out = {}
    for c in sorted({t // 3 for t in tails}):
        parts = {p: tails[3 * c + p] for p in range(3) if 3 * c + p in tails}
        if len(parts) >= 2:
            key, kind = propose(parts, corpus)
            if key is not None:
                out[c] = (key, kind)
    if cache is not None:
        cs = sorted(out)
        Path(cache).parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(cache, counters=np.array(cs, np.uint32),
                            ks=np.array([out[c][0] for c in cs], np.uint8).reshape(-1, 16),
                            kind=np.array([out[c][1] for c in cs], dtype='<U7'),
                            tails_sha256=data_sha, corpus_sha256=corp_sha)
    return out, False


# --------------------------------------------------------------------------- inputs

def sealed_counter_reason(counters):
    """Why these group counters may not be processed (a sealed capture's time window), or None."""
    counters = np.asarray(counters, np.int64)
    for low, high, reason in SEALED_COUNTER_WINDOWS:
        inside = int(((counters >= low) & (counters <= high)).sum())
        if inside:
            return f'{inside} data units have counters in {low}..{high}: {reason}'
    return None


def load_data_units(paths, allow_sealed=False):
    """Tails and DUs by tick 3c+p. Rows must pass their DU CRC; conflicting copies are dropped.

    Counters inside a sealed capture's window are refused before any payload byte is read.
    """
    units, conflicts = {}, set()
    for path in paths:
        with np.load(path, allow_pickle=False) as d:
            counters = d['counters'].astype(np.int64)
            reason = None if allow_sealed else sealed_counter_reason(counters)
            if reason:
                raise PermissionError(f'{path}: {reason}')
            phases, du = d['phases'].astype(np.int64), d['du']
        if du.ndim != 2 or du.shape[1] != DU_BYTES or du.dtype != np.uint8 or len(du) != len(counters) \
                or phases.shape != counters.shape:
            raise ValueError(f'{path}: expected counters, phases and (N, {DU_BYTES}) uint8 du')
        if np.any((phases < 0) | (phases > 2)) or not np.all(du[:, 1] >> 4 == phases):
            raise ValueError(f'{path}: phase field does not match the data-unit header')
        for n, (c, p, row) in enumerate(zip(counters, phases, du)):
            if crc(bytes(row[:714])) != int.from_bytes(bytes(row[714:]), 'big'):
                raise ValueError(f'{path}: data-unit CRC mismatch at row {n}')
            t = int(3 * c + p)
            if t in units and not np.array_equal(units[t], row):
                conflicts.add(t)
            units.setdefault(t, row.copy())
    for t in conflicts:
        units.pop(t, None)
    tails = {t: row[TAIL].copy() for t, row in units.items()}
    return tails, units, sorted(conflicts)


def dropped_counters(split_json, capture_id, allow_sealed=False):
    """label_check.dropped_counters of one capture in split.json; seeds never include them."""
    split = json.loads(Path(split_json).read_text(encoding='utf-8'))
    for name, entry in split.get('splits', {}).items():
        for capture in entry.get('captures', []) if isinstance(entry, dict) else []:
            if capture.get('id') == capture_id:
                if name not in SEED_SPLITS and not allow_sealed:
                    raise ValueError(f'capture {capture_id} is in the {name!r} split; refusing to seed it')
                return name, sorted(int(c) for c in capture.get('label_check', {}).get('dropped_counters', []))
    raise ValueError(f'capture {capture_id} not found in {split_json}')


def load_seeds(path, *, dropped=()):
    """Benchmark-cleaned seed keys: a benchmark real/<capture>.npz (labelled rows), or a supplied
    archive (fully supported rows) cleaned with split.json's dropped counters."""
    with np.load(path, allow_pickle=False) as k:
        files = set(k.files)
        if {'counters', 'mask_label', 'labelled'} <= files:
            kind = 'benchmark-labels'
            label = k['mask_label'][:, :16]
            ok = k['labelled'] & (label >= 0).all(axis=1)
            seeds = {int(c): label[i].astype(np.uint8) for i, c in enumerate(k['counters']) if ok[i]}
        elif {'counters', 'ks', 'crc_supported'} <= files:
            kind = 'supplied-archive'
            seeds = {int(c): row.astype(np.uint8).copy()
                     for c, row, m in zip(k['counters'], k['ks'], k['crc_supported']) if m.all()}
        else:
            raise ValueError(f'{path}: not a benchmark label file or a supplied key archive')
    removed = sorted(set(seeds) & set(dropped))
    for c in removed:
        del seeds[c]
    return seeds, dict(path=rel(path), sha256=sha256_file(path), kind=kind,
                       dropped_counters_applied=removed, keys=len(seeds))


def holdout_split(seeds, fraction, salt):
    """Deterministically hold out a fraction of the seed groups (to measure precision)."""
    if not fraction:
        return seeds, {}
    held = {c for c in seeds
            if int.from_bytes(hashlib.sha256(f'{salt}:{c}'.encode()).digest()[:8], 'big') < fraction * 2 ** 64}
    return {c: k for c, k in seeds.items() if c not in held}, {c: seeds[c] for c in held}


# --------------------------------------------------------------------------- gate A and period

def scan(keys, tails, first, span):
    """Records in the plaintext the current keys give (extended grammar, known blocks only)."""
    plain = np.zeros((3 * span, BLOCK), np.uint8)
    known = np.zeros((3 * span, BLOCK), np.uint8)
    for t, tail in tails.items():
        key = keys.get(t // 3)
        if key is not None:
            plain[t - 3 * first] = tail ^ key
            known[t - 3 * first] = 1
    return list(scan_records(plain.tobytes(), known_bytes=known.tobytes(), extended=True))


def family(record, period):
    return (record.offset // BLOCK % period, record.sequence, record.final, record.text)


def gate_a(records, period):
    """Records whose (offset mod P, sequence, final, text) occurs at least twice."""
    counts = Counter(family(r, period) for r in records)
    return [r for r in records if counts[family(r, period)] >= 2]


def pinned_blocks(record, first):
    """Block indices whose group keys a record pins (first = first received counter), or [].

    A record whose CRC-covered bytes lie inside one group pins nothing. With plaintext
    [fill, R, fill] (R a one-block item-final record) the key K ^ fill ^ R decrypts the group to
    [R, fill, R]: R is CRC-valid there too, one block early, recurs in every pass, and is the
    reading the fill proposal prefers. A record pins keys only when its CRC ties two groups (whose
    keys are independent): then every block up to the CRC and zero padding is pinned, and so is the
    mandatory fill block of a non-final record. The optional fill block after an item-final record
    is never pinned: the record is valid without it.
    """
    start = record.offset // BLOCK
    last = (record.offset + 2 + record.body_length + 2 - 1) // BLOCK       # block holding the CRC
    if (start + 3 * first) // 3 == (last + 3 * first) // 3:
        return []
    return list(range(start, last + 1 if record.final else last + 2))


def pinning(records, first):
    """The records that pin at least one group key (see pinned_blocks)."""
    return [r for r in records if pinned_blocks(r, first)]


def repeat_distances(records, min_distance=MIN_PERIOD_DISTANCE):
    """Histogram of distances from each record to the next copy of it at least min_distance away."""
    positions = defaultdict(set)
    for r in records:
        positions[(r.sequence, r.final, r.text)].add(r.offset // BLOCK)
    distances = Counter()
    for offsets in positions.values():
        offsets = sorted(offsets)
        for i, a in enumerate(offsets):
            b = next((b for b in offsets[i + 1:] if b - a >= min_distance), None)
            if b is not None:
                distances[b - a] += 1
    return distances


def choose_period(records, manual=None, min_distance=MIN_PERIOD_DISTANCE):
    """Period from repeat distances (or --period), confirmed by gate-A recurrence vs P+-1..3."""
    distances = repeat_distances(records, min_distance)
    if manual is not None:
        candidates = [int(manual)]
    else:
        candidates = [d for d, _ in distances.most_common(PERIOD_CANDIDATES)]
    info = dict(mode='manual' if manual is not None else 'auto', min_distance=min_distance,
                records_scanned=len(records), distance_histogram_top=distances.most_common(8))
    if not candidates:
        return dict(info, period=None, confirmed=False, reason='no record recurs at >= min_distance')
    scores = {p: len(gate_a(records, p)) for p in candidates}
    period = max(candidates, key=lambda p: (scores[p], -p))
    controls = {f'{off:+d}': len(gate_a(records, period + off)) for off in CONTROL_OFFSETS
                if period + off > 0}
    best_control = max(controls.values(), default=0)
    confirmed = scores[period] >= MIN_CONFIRM_RECORDS and scores[period] > 2 * best_control
    if manual is not None:
        # A period that only aligns some copies (2P/3 aligns every second pass) shows recurrence
        # too and its own P+-1..3 controls are clean. Refuse a manual period that is not a multiple
        # of the confirmed detected one (or a divisor of it with at least as many recurring records).
        auto = choose_period(records, None, min_distance)
        info['detected'] = {k: auto.get(k) for k in ('period', 'confirmed', 'gate_a_recurring_records')}
        if auto['confirmed'] and period % auto['period'] and not (
                auto['period'] % period == 0
                and scores[period] >= auto['gate_a_recurring_records'][str(auto['period'])]):
            return dict(info, period=int(period), confirmed=False,
                        gate_a_recurring_records={str(p): s for p, s in scores.items()},
                        gate_a_controls=controls,
                        reason=f'the detected period {auto["period"]} is confirmed and does not divide '
                               f'the manual period')
    return dict(info, period=int(period), confirmed=bool(confirmed),
                gate_a_recurring_records={str(p): s for p, s in scores.items()},
                gate_a_controls=controls,
                rule=f'>= {MIN_CONFIRM_RECORDS} recurring records at P and more than twice the best '
                     f'of P{"/".join(f"{o:+d}" for o in CONTROL_OFFSETS)}')


# --------------------------------------------------------------------------- XOR-link

def ambiguous_blocks(tails, trusted, period, sources=None):
    """Plaintext values that cannot anchor an alignment: fill, zeros, and any value the trusted
    plaintext (restricted to the ticks in `sources` when given) shows at two different positions
    modulo the detected carousel period."""
    positions = defaultdict(set)
    for t, tail in tails.items():
        key = trusted.get(t // 3)
        if key is not None and (sources is None or t in sources):
            positions[(tail ^ key).tobytes()].add(t % period)
    return {v for v, where in positions.items() if len(where) > 1} | set(AMBIGUOUS_ALWAYS)


def record_ticks(records, first):
    """Ticks (3c+p) of every block the given records pin (first = first received counter)."""
    return {b + 3 * first for r in records for b in pinned_blocks(r, first)}


def link_support(tails, trusted, period, span=CAROUSEL_SPAN, exclude=(), ambiguous=(), sources=None,
                 targets=None):
    """For each untrusted received group: key -> displacement -> phases producing it.

    Source blocks whose plaintext is in `ambiguous` contribute no evidence, and when `sources` (a
    set of ticks) is given, neither do trusted blocks outside it. `targets` replaces the default
    target set (every received group that is not trusted); a trusted target is supported by the
    other groups only, since a displacement is never zero.
    """
    expected = defaultdict(list)
    for c, key in trusted.items():
        for p in range(3):
            t = 3 * c + p
            tail = tails.get(t)
            if tail is None or (sources is not None and t not in sources):
                continue
            block = tail ^ key
            if ambiguous and block.tobytes() in ambiguous:
                continue
            for m in range(-span, span + 1):
                if m:
                    expected[t + m * period].append((block, -m * period))
    support = {}
    if targets is None:
        targets = {t // 3 for t in tails} - set(trusted)
    for c in sorted(set(targets) - set(exclude)):
        by_key = defaultdict(lambda: defaultdict(set))
        for p in range(3):
            t = 3 * c + p
            if t in tails and t in expected:
                for block, d in expected[t]:
                    by_key[(tails[t] ^ block).tobytes()][d].add(p)
        if by_key:
            support[c] = by_key
    return support


def decide_link(by_key, rule=DEFAULT_RULE):
    """The single key a group's link support admits under a rule, or None.

    The support comes from link_support, after the ambiguous-source filter when one is given.

    upstream:      exactly one key produced by >= 2 phases (any displacements). Unsafe at P+-1..2.
    strict:        exactly one key produced by >= 2 phases at one displacement. Admits a
                   phase-0/phase-2 swap when blocks 4 apart are equal.
    strict+second: strict, and that key also produced (any phase) at a second displacement.
    strict2:       strict, and that key produced by >= 2 phases at a second displacement too.
    """
    if rule == 'upstream':
        winners = [k for k, by_d in by_key.items() if len(set().union(*by_d.values())) >= 2]
        return winners[0] if len(winners) == 1 else None
    strict = [k for k, by_d in by_key.items() if any(len(ph) >= 2 for ph in by_d.values())]
    if len(strict) != 1:
        return None
    key, by_d = strict[0], by_key[strict[0]]
    if rule == 'strict':
        return key
    if rule == 'strict+second':
        return key if len(by_d) >= 2 else None
    if rule == 'strict2':
        return key if sum(len(ph) >= 2 for ph in by_d.values()) >= 2 else None
    raise ValueError(f'unknown link rule {rule!r}')


def xor_link(tails, trusted, period, rule=DEFAULT_RULE, span=CAROUSEL_SPAN, exclude=(), ambiguous=(),
             sources=None, targets=None):
    """Counter -> key for every untrusted group (or target) the rule links at this period."""
    if rule not in LINK_RULES:
        raise ValueError(f'unknown link rule {rule!r}')
    links = {}
    for c, by_key in link_support(tails, trusted, period, span, exclude, ambiguous, sources, targets).items():
        key = decide_link(by_key, rule)
        if key is not None:
            links[c] = np.frombuffer(key, np.uint8).copy()
    return links


def control_links(tails, trusted, period, rule=DEFAULT_RULE, span=CAROUSEL_SPAN, exclude=(), ambiguous=(),
                  sources=None):
    """Links at P+-1..3 with the same trusted set and the same evidence filters as at P."""
    return {f'{off:+d}': len(xor_link(tails, trusted, period + off, rule, span, exclude, ambiguous, sources))
            for off in CONTROL_OFFSETS if period + off > 0}


def audit_seeds(tails, seeds, period, rule=DEFAULT_RULE, span=CAROUSEL_SPAN):
    """Seeds contradicted by their own carousel copies: counter -> the key the other seeds link.

    Each seed group is treated as a target of the default XOR-link (rule, ambiguous-source filter,
    record-backed sources) from the other seeds. A seed whose link exists and differs is wrong or
    its copies are; either way it is not a label.
    """
    if not seeds:
        return {}, 0
    received = sorted({t // 3 for t in tails})
    first, groups = received[0], received[-1] - received[0] + 1
    sources = record_ticks(pinning(gate_a(scan(seeds, tails, first, groups), period), first), first)
    # Ambiguity from record-backed plaintext only: a seed with two phases swapped shows its copies'
    # blocks at shifted positions, which would otherwise veto the very evidence against it.
    links = xor_link(tails, seeds, period, rule, span,
                     ambiguous=ambiguous_blocks(tails, seeds, period, sources),
                     sources=sources, targets=set(seeds))
    return {c: k for c, k in links.items() if not np.array_equal(k, seeds[c])}, len(links)


# --------------------------------------------------------------------------- recovery

def iterate(tails, seeds, proposals, period, *, rule=DEFAULT_RULE, xorlink=True, rounds=12,
            banned=(), span=CAROUSEL_SPAN, filter_ambiguous=True, record_sources=True):
    """Gate A and XOR-link rounds with wrong-period controls in every XOR-link round.

    With record_sources (default) only trusted blocks inside a gate-A record are link sources.

    Returns confirmed keys with provenance and round, or blocked=True as soon as a control links.
    """
    received = sorted({t // 3 for t in tails})
    first, groups = received[0], received[-1] - received[0] + 1
    banned = set(banned)
    keys = {c: k for c, (k, _) in proposals.items() if c not in banned}
    keys.update(seeds)
    confirmed = dict(seeds)
    provenance = {c: 'seed' for c in seeds}
    when = {c: 0 for c in seeds}
    log, records, verified = [], [], []
    for rnd in range(1, rounds + 1):
        records = scan(keys, tails, first, groups)
        verified = gate_a(records, period)
        pinned = pinning(verified, first)
        gate_added = 0
        for r in pinned:
            for b in pinned_blocks(r, first):
                c = (b + 3 * first) // 3
                if c not in confirmed:
                    confirmed[c] = keys[c]
                    provenance[c] = proposals[c][1]
                    when[c] = rnd
                    gate_added += 1
        entry = dict(round=rnd, records=len(records), recurring_records=len(verified),
                     pinning_records=len(pinned), gate_a_added=gate_added)
        links = {}
        if xorlink:
            ambiguous = ambiguous_blocks(tails, confirmed, period) if filter_ambiguous else ()
            sources = record_ticks(pinned, first) if record_sources else None
            links = xor_link(tails, confirmed, period, rule, span, banned, ambiguous, sources)
            controls = control_links(tails, confirmed, period, rule, span, banned, ambiguous, sources)
            entry.update(trusted=len(confirmed), ambiguous_values=len(ambiguous),
                         source_blocks=None if sources is None else len(sources),
                         xorlink_candidates=len(links), control_links=controls)
            if any(controls.values()):
                log.append(entry)
                return dict(blocked=True, blocked_round=rnd, control_links=controls, log=log)
            for c, key in links.items():
                confirmed[c] = keys[c] = key
                provenance[c] = 'xorlink'
                when[c] = rnd
        entry['xorlink_added'] = len(links)
        log.append(entry)
        if not gate_added and not links:
            break
    return dict(blocked=False, confirmed=confirmed, provenance=provenance, round=when, log=log,
                records=len(records), recurring_records=len(verified))


def default_checker(decoder, workers, workdir):
    """Role-0 decoder-flag check with the benchmark's traced stock decoder (build_mask_benchmark)."""
    import build_mask_benchmark as bench

    def check(counters, ks, units):
        n = len(counters)
        frames = np.zeros((n, bench.SLOTS, bench.FRAME_BYTES), np.uint8)
        present = np.zeros((n, bench.SLOTS), bool)
        for i, c in enumerate(counters):
            for p in range(3):
                row = units.get(3 * int(c) + p)
                if row is not None:
                    f, ok = bench.unit_frames(row, np.ones(4, bool))
                    frames[i, 20 * p:20 * p + 20] = f
                    present[i, 20 * p:20 * p + 20] = ok
        labels = np.full((n, bench.MASK_BYTES), -1, np.int16)
        labels[:, :16] = ks
        s, f, g, control = bench.role0_flag_check(Path(decoder), frames, present, labels, Path(workdir), workers)
        return s, f, g, np.asarray(counters)[control]
    return check


def evs_check(candidates, provenance, units, checker):
    """Decode each candidate's role-0 frames with its key and with another candidate's key."""
    cs = np.array(sorted(candidates), np.int64)
    if not len(cs):
        return set(), dict(candidates=0)
    ks = np.stack([candidates[int(c)] for c in cs])
    supplied, label, control, control_counter = checker(cs, ks, units)
    supplied, label, control = (np.asarray(a, np.int64) for a in (supplied, label, control))
    flagged = {int(c) for c, f in zip(cs, label) if f > 0}
    by = {}
    for kind in PROVENANCE:
        sel = np.array([provenance[int(c)] == kind for c in cs])
        if sel.any():
            by[kind] = dict(groups=int(sel.sum()), label_flagged=int(((label > 0) & sel).sum()),
                            control_flagged=int(((control > 0) & sel).sum()))
    return flagged, dict(candidates=int(len(cs)), role0_frames=int(supplied.sum()),
                         label_flagged_frames=int(label.sum()), control_flagged_frames=int(control.sum()),
                         label_flagged_groups=int((label > 0).sum()),
                         control_flagged_groups=int((control > 0).sum()),
                         flagged=[dict(counter=c, provenance=provenance[c]) for c in sorted(flagged)],
                         by_provenance=by)


def recover(tails, seeds, proposals, *, period=None, rule=DEFAULT_RULE, xorlink=True, rounds=12,
            min_distance=MIN_PERIOD_DISTANCE, checker=None, units=None, evs_iterations=4,
            filter_ambiguous=True, record_sources=True, seed_audit=True):
    """Full pipeline for one capture. Returns (confirmed, provenance, round, report)."""
    received = sorted({t // 3 for t in tails})
    first, groups = received[0], received[-1] - received[0] + 1
    present = set(received)
    seeds = seeds_in = {c: k for c, k in seeds.items() if c in present}
    start = {c: k for c, (k, _) in proposals.items()}
    start.update(seeds)
    # Single-group records are left out here too: a swapped [R, fill, R] reading recurs at P+-1, P+-2.
    period_info = choose_period(pinning(scan(start, tails, first, groups), first), period, min_distance)
    report = dict(received_groups=len(received), seeds=len(seeds), proposals=len(proposals),
                  proposals_by_class=dict(Counter(kind for _, kind in proposals.values())),
                  period=period_info, link_rule=rule, ambiguous_source_filter=bool(filter_ambiguous),
                  record_backed_sources=bool(record_sources),
                  carousel_span=CAROUSEL_SPAN,
                  control_offsets=list(CONTROL_OFFSETS))
    if not period_info['confirmed']:
        report.update(status='no_confirmed_period', xorlink=dict(enabled=False, blocked=None))
        return dict(seeds), {c: 'seed' for c in seeds}, {c: 0 for c in seeds}, report
    P = period_info['period']
    if seed_audit:
        contradicted, audited = audit_seeds(tails, seeds, P)
        seeds = {c: k for c, k in seeds.items() if c not in contradicted}
        report['seed_audit'] = dict(
            seeds_linked=audited, contradicted=len(contradicted),
            dropped=[dict(counter=int(c), seed=seeds_in[c].tobytes().hex(), linked=k.tobytes().hex())
                     for c, k in sorted(contradicted.items())],
            rule='a seed is dropped when the default XOR-link from the other seeds (strict2, ambiguous-'
                 'source filter, record-backed sources) gives its group a different key')
    banned, checked, evs_log, blocked = set(), set(), [], None
    use_xorlink = xorlink
    for iteration in range(evs_iterations if checker else 1):
        result = iterate(tails, seeds, proposals, P, rule=rule, xorlink=use_xorlink, rounds=rounds,
                         banned=banned, filter_ambiguous=filter_ambiguous, record_sources=record_sources)
        if result['blocked']:
            blocked = dict(round=result['blocked_round'], control_links=result['control_links'],
                           log=result['log'], evs_iteration=iteration)
            use_xorlink = False
            result = iterate(tails, seeds, proposals, P, rule=rule, xorlink=False, rounds=rounds,
                             banned=banned, filter_ambiguous=filter_ambiguous, record_sources=record_sources)
        if checker is None:
            break
        new = {c: k for c, k in result['confirmed'].items()
               if result['provenance'][c] != 'seed' and (c, k.tobytes()) not in checked}
        flagged, stats = evs_check(new, result['provenance'], units, checker)
        checked.update((c, k.tobytes()) for c, k in new.items())
        evs_log.append(dict(stats, iteration=iteration))
        if not flagged:
            break
        banned |= flagged
    confirmed, provenance, when = result['confirmed'], result['provenance'], result['round']
    leftover = sorted(c for c in banned if c in confirmed and provenance[c] != 'seed')
    unchecked = []
    if leftover:                    # still flagged after the last allowed re-run: run once more
        # without them, and keep only keys the checker has already seen and passed (a key that
        # appears only in this last run, or that rested on a flagged key, is not output).
        result = iterate(tails, seeds, proposals, P, rule=rule, xorlink=use_xorlink, rounds=rounds,
                         banned=banned, filter_ambiguous=filter_ambiguous, record_sources=record_sources)
        if result['blocked']:
            blocked = dict(round=result['blocked_round'], control_links=result['control_links'],
                           log=result['log'], evs_iteration=evs_iterations)
            result = iterate(tails, seeds, proposals, P, rule=rule, xorlink=False, rounds=rounds,
                             banned=banned, filter_ambiguous=filter_ambiguous, record_sources=record_sources)
        confirmed, provenance, when = result['confirmed'], result['provenance'], result['round']
        unchecked = sorted(c for c, k in confirmed.items()
                           if provenance[c] != 'seed' and (c, k.tobytes()) not in checked)
        for c in unchecked:
            confirmed.pop(c), provenance.pop(c), when.pop(c)
    report.update(
        status='ok', rounds=result['log'], records=result['records'],
        recurring_records=result['recurring_records'],
        xorlink=dict(enabled=bool(xorlink), blocked=blocked is not None, blocked_detail=blocked,
                     rule=rule, links=sum(v == 'xorlink' for v in provenance.values())),
        proposal_overridden=sum(1 for c, (k, _) in proposals.items()
                                if c in confirmed and not np.array_equal(k, confirmed[c])),
        control_panel=control_panel(tails, confirmed, P, banned))
    if checker is not None:
        report['evs_check'] = dict(iterations=evs_log, rejected=sorted(banned),
                                   flagged_in_last_iteration=leftover, removed_unchecked=unchecked,
                                   rule='reject a new key when its role-0 frames, decoded alone, raise any '
                                        'bfi/BER_detect flag; control = another new key (roll by n/2)',
                                   limits='necessary check of ks[0..10] only: misses about 20% of wrong keys '
                                          'on review data and cannot see ks[11..15]')
    return confirmed, provenance, when, report


def control_panel(tails, trusted, period, banned=()):
    """Diagnostic: links at P and at the control periods under every rule, with and without the
    ambiguous-source filter, from the final trusted set (few targets remain, so few links)."""
    panel = {}
    for name, ambiguous in (('filtered', ambiguous_blocks(tails, trusted, period)), ('unfiltered', ())):
        for rule in LINK_RULES:
            panel[f'{rule}|{name}'] = dict(
                at_period=len(xor_link(tails, trusted, period, rule, exclude=banned, ambiguous=ambiguous)),
                controls=control_links(tails, trusted, period, rule, exclude=banned, ambiguous=ambiguous))
    return panel


# --------------------------------------------------------------------------- CLI

def git_head():
    try:
        return subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, capture_output=True, text=True,
                              check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def write_outputs(out, confirmed, provenance, when, period, report):
    counters = np.array(sorted(confirmed), np.uint32)
    ks = np.array([confirmed[int(c)] for c in counters], np.uint8).reshape(-1, 16)
    digest = content_sha256(counters, ks)
    np.savez_compressed(out/'keys.npz', format=FORMAT, counters=counters, ks=ks,
                        provenance=np.array([provenance[int(c)] for c in counters], dtype='<U7'),
                        round=np.array([when[int(c)] for c in counters], np.int16),
                        period=np.int32(period or 0), content_sha256=digest)
    report['output'] = dict(path=rel(out/'keys.npz'), keys=int(len(counters)),
                            by_provenance={k: sum(v == k for v in provenance.values()) for k in PROVENANCE},
                            content_sha256=digest,
                            content_sha256_definition='sha256(counters as u32 little-endian || ks (N,16) u8)')
    (out/'report.json').write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
    return digest


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--data-units', required=True, nargs='+', type=Path,
                    help='data_units.npz from salvage_msc_packets.py (one capture)')
    ap.add_argument('--seeds', type=Path, help='benchmark real/<capture>.npz, or a supplied key archive '
                                               'together with --capture-id')
    ap.add_argument('--capture-id', help='drop this capture\'s label_check.dropped_counters (split.json) '
                                         'from the seeds; required for a supplied archive')
    ap.add_argument('--split-json', type=Path, default=ROOT/DEFAULT_SPLIT)
    ap.add_argument('--holdout', type=float, default=0.0,
                    help='hold out this fraction of seed groups and score recovered keys against them')
    ap.add_argument('--holdout-salt', default='carousel-holdout')
    ap.add_argument('--phrase-corpus', nargs='+',
                    help='items_*.json / titles_*.json / .txt files, directories or globs (default: the '
                         'contrib reference, minus the hard-coded sealed-test and live-source exclusions)')
    ap.add_argument('--phrase-exclude', action='append', default=[],
                    help='additional fnmatch pattern excluded from the corpus (e.g. the target capture)')
    ap.add_argument('--no-phrases', action='store_true', help='fill and opening proposals only')
    ap.add_argument('--proposal-cache', type=Path, help='npz cache of the seed-independent proposals')
    ap.add_argument('--period', type=int, help='carousel period in 16-byte blocks (still confirmed)')
    ap.add_argument('--min-period-distance', type=int, default=MIN_PERIOD_DISTANCE)
    ap.add_argument('--link-rule', choices=LINK_RULES, default=DEFAULT_RULE,
                    help='XOR-link rule; strict and upstream are diagnostics with known false links')
    ap.add_argument('--no-xorlink', action='store_true')
    ap.add_argument('--keep-ambiguous-sources', action='store_true',
                    help='diagnostic: let fill, zero and repeated plaintext blocks anchor XOR-links')
    ap.add_argument('--link-any-trusted-source', action='store_true',
                    help='diagnostic: let trusted blocks outside gate-A records anchor XOR-links (a wrong '
                         'seed repeated in every carousel copy is then copied onto the other copies)')
    ap.add_argument('--no-seed-audit', action='store_true',
                    help='diagnostic: keep seeds that their own carousel copies contradict')
    ap.add_argument('--rounds', type=int, default=12)
    ap.add_argument('--evs-check', action='store_true',
                    help='reject new keys whose role-0 frames raise decoder flags (ks[0..10] only)')
    ap.add_argument('--evs-decoder', type=Path, default=ROOT/DEFAULT_DECODER)
    ap.add_argument('--workers', type=int, default=8)
    ap.add_argument('--allow-sealed-input', action='store_true',
                    help='permit inputs on the exclusion list (registered sealed evaluations only)')
    ap.add_argument('--out', required=True, type=Path)
    a = ap.parse_args(argv)
    if a.period is not None and a.period < a.min_period_distance:
        ap.error('--period must be at least --min-period-distance')
    if not 0 <= a.holdout < 1:
        ap.error('--holdout must be in [0, 1)')
    for path in list(a.data_units) + ([a.seeds] if a.seeds else []):
        reason = excluded_reason(path)
        if reason and not a.allow_sealed_input:
            ap.error(f'{path} is on the exclusion list: {reason}')
    if a.evs_check and not a.evs_decoder.exists():
        ap.error(f'{a.evs_decoder} not found (built by build_mask_benchmark.py real)')

    try:
        tails, units, conflicts = load_data_units(a.data_units, a.allow_sealed_input)
    except PermissionError as exc:
        ap.error(str(exc))
    if not tails:
        ap.error('no data units')
    seeds, seed_info, held = {}, None, {}
    if a.seeds:
        dropped, split_name = (), None
        if a.capture_id:
            split_name, dropped = dropped_counters(a.split_json, a.capture_id, a.allow_sealed_input)
        seeds, seed_info = load_seeds(a.seeds, dropped=dropped)
        if seed_info['kind'] == 'supplied-archive' and not a.capture_id:
            ap.error('a supplied archive seeds only after cleaning: pass --capture-id')
        seed_info.update(capture_id=a.capture_id, split=split_name)
        received = {t // 3 for t in tails}
        seeds = {c: k for c, k in seeds.items() if c in received}
        seeds, held = holdout_split(seeds, a.holdout, a.holdout_salt)
        seed_info.update(received=len(seeds) + len(held), used=len(seeds), held_out=len(held))

    if a.no_phrases:
        files, excluded = [], []
        corpus = empty_corpus()
    else:
        files, excluded = resolve_corpus(a.phrase_corpus, a.phrase_exclude)
        if not files:
            ap.error('phrase corpus is empty after exclusions (use --no-phrases)')
        corpus = build_corpus(files)
    proposals, cached = all_proposals(tails, corpus, a.proposal_cache)
    proposals = {c: v for c, v in proposals.items() if c not in seeds}

    checker, tmp = None, None
    a.out.mkdir(parents=True, exist_ok=False)
    if a.evs_check:
        tmp = tempfile.TemporaryDirectory(dir=a.out)
        checker = default_checker(a.evs_decoder, a.workers, tmp.name)
    try:
        confirmed, provenance, when, report = recover(
            tails, seeds, proposals, period=a.period, rule=a.link_rule, xorlink=not a.no_xorlink,
            rounds=a.rounds, min_distance=a.min_period_distance, checker=checker, units=units,
            filter_ambiguous=not a.keep_ambiguous_sources,
            record_sources=not a.link_any_trusted_source, seed_audit=not a.no_seed_audit)
    finally:
        if tmp is not None:
            tmp.cleanup()
    header = dict(format=FORMAT, created=dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds'),
                  git_head=git_head(), tool=rel(__file__),
                  inputs=[dict(path=rel(p), sha256=sha256_file(p)) for p in a.data_units],
                  received_ticks=len(tails), du_conflicts=conflicts, seeds=seed_info,
                  corpus=dict(files=[dict(path=f, sha256=sha256_file(ROOT/f if not Path(f).is_absolute() else f))
                                     for f in corpus.files],
                              excluded=excluded, texts=corpus.texts, phrases=int(len(corpus.phrases)),
                              disabled=bool(a.no_phrases)),
                  proposal_cache=dict(path=rel(a.proposal_cache), hit=cached) if a.proposal_cache else None)
    report = dict(header, **report)
    if held:
        rows = Counter()
        for c, key in held.items():
            if c not in confirmed:
                rows['not_recovered'] += 1
            else:
                rows[f'{provenance[c]}_{"correct" if np.array_equal(confirmed[c], key) else "wrong"}'] += 1
        report['holdout'] = dict(fraction=a.holdout, salt=a.holdout_salt, groups=len(held), **rows)
    report['note'] = ('Labels for the 16-byte text tail only (ks[0..10] role 0, ks[11..15] role-1 j=0..4). '
                      'Gate-A keys rest on a CRC-valid record recurring at the carousel period; XOR-link keys '
                      'on two-displacement 128-bit agreement with record-backed copies and no link at P+-1..3. '
                      'Seeds are inputs: only the seed audit checks them. Not audio masks.')
    write_outputs(a.out, confirmed, provenance, when, report['period'].get('period'), report)
    print(json.dumps({k: report[k] for k in ('status', 'received_groups', 'seeds', 'proposals', 'output')}
                     | dict(period=report['period'].get('period'), xorlink=report['xorlink']), indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
