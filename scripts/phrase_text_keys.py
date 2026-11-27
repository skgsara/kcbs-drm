"""Propose per-group text prefixes from earlier bulletins, then check received records.

An eight-character fragment sets one 16-byte mask. Scoring its other text blocks
selects a single proposal before reading any received record CRC. Only complete
records with the expected structure and CRC can contribute mask bytes.
"""
from pathlib import Path
import json

import numpy as np

from parse_text_records import RecordError, parse_record
from tail_fill_audit import text_unit


def bulletin_phrases(directory):
    texts = set()
    for path in sorted(directory.glob('items_*.json')):
        for item in json.loads(path.read_text(encoding='utf-8'))['items']:
            texts.update(row['text'] for row in item if row['ok'])
    if not texts:
        raise ValueError(f'no verified text in {directory}/items_*.json')
    words = {n: {s[i:i+n] for s in texts for i in range(len(s) - n + 1)}
             for n in (1, 2, 3, 4, 8)}
    phrases = np.stack([np.frombuffer(s.encode('utf-16le'), '<u2') for s in sorted(words.pop(8))])
    return phrases, words


def proposal(tails, phrases, words, charset):
    phases = sorted(tails)
    data = np.stack([tails[p] for p in phases]).view('<u2').reshape(len(phases), 8)
    fills = {}
    for phase, row in tails.items():
        key = row ^ 0xbb
        after = tails.get(phase + 1)
        header = False
        if after is not None:
            first, second = (after ^ key)[:2].tolist()
            length = (first & 7) * 16 + (second & 15)
            header = ((first & 0x7f) == 5 and length == 92) or (
                0x20 <= (first & 0x7f) <= 0x27 and 2 <= length <= 92 and length % 2 == 0)
        others = [(v ^ key).tobytes().decode('utf-16le', errors='replace')
                  for p, v in tails.items() if p != phase]
        trigrams = sum(s[i:i+3] in words[3] for s in others for i in range(6))
        if (header and trigrams >= 2) or (phase == 2 and len(tails) == 3 and trigrams >= 4):
            fills[key.tobytes()] = (header, trigrams)
    if fills:
        best = max(fills.values())
        winners = [key for key, score in fills.items() if score == best]
        if len(winners) == 1:
            return np.frombuffer(winners[0], np.uint8)
    candidates = set()
    for row in data:
        possible = phrases ^ row
        clear = possible[:, None, :] ^ data
        good = charset[clear].sum(axis=(1, 2)) >= data.size - 3
        candidates.update(key.tobytes() for key in possible[good])
    best_score = -1
    best = None
    for key in candidates:
        clear = data ^ np.frombuffer(key, '<u2')
        # Ignore the artificial eight Hangul fill syllables in the language score.
        strings = []
        for stretch in np.split(clear, np.flatnonzero(np.diff(phases) > 1) + 1):
            strings.extend(''.join(chr(int(x)) for x in stretch.ravel()).split('\ubbbb' * 8))
        score = sum(s[i:i+n] in gram for s in strings for n, gram in words.items()
                    for i in range(len(s) - n + 1))
        if score > best_score:
            best_score, best = score, key
        elif score == best_score:
            best = None
    if best is None or best_score <= (30 if len(phases) == 3 else 18):
        return None
    return np.frombuffer(best, np.uint8)


def recover_records(tails, counters, keys, supported, corpus=None):
    """Return CRC- and structure-checked records and the masks used to decode them."""
    if corpus is None:
        corpus = Path(__file__).resolve().parents[1] / 'contrib/kcbsdrm/reference'
    phrases, words = bulletin_phrases(corpus)
    charset = np.array([text_unit(i) for i in range(65536)])
    proposals = {}
    for i, counter in enumerate(counters):
        c = int(counter)
        if supported[i].all():
            proposals[c] = keys[i]
            continue
        parts = {p: tails[3 * c + p] for p in range(3) if 3 * c + p in tails}
        if len(parts) < 2:
            continue
        key = proposal(parts, phrases, words, charset)
        if key is not None and np.all(key[supported[i]] == keys[i, supported[i]]):
            proposals[c] = key
    plain = {t: (tail ^ proposals[t // 3]).tobytes()
             for t, tail in tails.items() if t // 3 in proposals}
    records, used = [], {}
    # Each protocol record begins on a block boundary. A missing block cannot
    # silently shorten a record or turn unobserved padding into observed zeroes.
    for start in sorted(plain):
        b0, b1 = plain[start][:2]
        length = (b0 & 7) * 16 + (b1 & 15)
        final = bool(b0 & 0x20)
        if final:
            if not 0x20 <= (b0 & 0x7f) <= 0x27 or not 2 <= length <= 92:
                continue
        elif (b0 & 0x7f) != 5 or length != 92:
            continue
        blocks = (length + 4 + 15) // 16 + int(not final)
        if any(t not in plain for t in range(start, start + blocks)):
            continue
        raw = b''.join(plain[t] for t in range(start, start + blocks))
        try:
            record = parse_record(raw)
        except RecordError:
            continue
        records.append(dict(start=start, header_ok=True, fill_ok=True, crc_ok=True,
                            plaintext_hex=raw.hex(), text=record.text, source='prior_phrases'))
        for tick in range(start, start + blocks):
            used[tick // 3] = proposals[tick // 3]
    return records, used
