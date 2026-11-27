"""Test repeated text segments using key-cancelling byte differences.

Segment hypotheses come from unique fill candidates. Text-only within-group
XOR invariants must agree before segments are linked. XOR constraints are
transactional: a contradictory match is rejected. Keys supported only by fill
or repetition remain candidates; a separate mask marks participation in a
fully reconstructed header/fill/CRC-valid segment. CRC16 is not authentication.
No CRC correction search or language-model completion is performed here.
"""
import argparse
from collections import Counter
import json
from pathlib import Path

import numpy as np
from tail_fill_audit import crc, idle_prefixes


class XorUF:
    def __init__(self):
        self.parent = {}
        self.delta = {}

    def find(self, node):
        if node not in self.parent:
            self.parent[node], self.delta[node] = node, 0
        p = self.parent[node]
        if p != node:
            root, d = self.find(p)
            self.parent[node] = root
            self.delta[node] ^= d
        return self.parent[node], self.delta[node]

    def bind(self, a, b, value):
        ra, da = self.find(a); rb, db = self.find(b)
        if ra == rb:
            return da ^ db == value
        self.parent[ra] = rb
        self.delta[ra] = da ^ db ^ value
        return True

    def value(self, node):
        r, d = self.find(node); r0, d0 = self.find(-1)
        return (d ^ d0) if r == r0 else None

    def copy(self):
        result = XorUF()
        result.parent, result.delta = self.parent.copy(), self.delta.copy()
        return result


def segment(start, tails):
    cipher = np.zeros(112, dtype=np.uint8)
    present = np.zeros(112, dtype=bool)
    groups = np.empty(112, dtype=np.int64)
    for j in range(7):
        t = start+j
        groups[j*16:j*16+16] = t//3
        if t in tails:
            cipher[j*16:j*16+16] = tails[t]
            present[j*16:j*16+16] = True
    features = {}
    for j in range(2, 94, 2):
        for distance in (16, 32):
            k = j+distance
            if k+1 >= 94 or groups[j] != groups[k] or not (present[j] and present[k]):
                continue
            features[j, k] = (int(cipher[j] ^ cipher[k]) |
                              int(cipher[j+1] ^ cipher[k+1]) << 8)
    return dict(start=start, cipher=cipher, present=present, groups=groups, features=features)


def recover(group_path, units_path, out, require_fill=False, phrase_keys=False):
    g, units = np.load(group_path), np.load(units_path)
    tails = {3*int(c)+int(p): du[698:714]
             for c,p,du in zip(units['counters'], units['phases'], units['du'])}
    uf = XorUF()
    starts = set()
    for c, key, mask, offset in zip(g['counters'], g['candidate_ks'], g['candidate_mask'], g['fill_offset']):
        if not mask.all():
            continue
        for j in range(16):
            if not uf.bind(16*int(c)+j, -1, int(key[j])):
                raise ValueError('conflicting seed keys')
        f = 3*int(c) + int(offset)//16
        starts.update((f-6, f+1))
    segments = [segment(s, tails) for s in sorted(starts)]
    matches, rejected, comparisons = [], [], 0
    for i, a in enumerate(segments):
        for b in segments[i+1:]:
            if b['start']-a['start'] < 7:
                continue
            common = a['features'].keys() & b['features'].keys()
            if len(common) < 8 or len({j % 16 for j,k in common}) < 6:
                continue
            comparisons += 1
            if any(a['features'][pair] != b['features'][pair] for pair in common):
                continue
            trial = uf.copy()
            good = True
            # Equal text and fill; headers/CRCs may differ between transmissions.
            for j in list(range(2, 94)) + list(range(96, 112)):
                if not a['present'][j] or not b['present'][j]:
                    continue
                ka = 16*int(a['groups'][j]) + j % 16
                kb = 16*int(b['groups'][j]) + j % 16
                if not trial.bind(ka, kb, int(a['cipher'][j] ^ b['cipher'][j])):
                    good = False
                    break
            item = dict(start_a=a['start'], start_b=b['start'], matching_word_invariants=len(common))
            if good:
                uf = trial
                matches.append(item)
            else:
                rejected.append(item)
    counters = np.array(sorted({t//3 for t in tails}), dtype=np.uint32)
    index = {int(c): i for i,c in enumerate(counters)}
    keys = np.zeros((len(counters), 16), np.uint8)
    candidate = np.zeros_like(keys, dtype=bool)
    crc_supported = np.zeros_like(candidate)
    for i,c in enumerate(counters):
        for j in range(16):
            value = uf.value(16*int(c)+j)
            if value is not None:
                keys[i,j], candidate[i,j] = value, True
    checked, valid = [], []
    for s in segments:
        if not s['present'].all():
            continue
        plain = np.zeros(112, np.uint8)
        complete = True
        for j in range(112):
            value = uf.value(16*int(s['groups'][j])+j % 16)
            if value is None:
                complete = False
                break
            plain[j] = int(s['cipher'][j]) ^ value
        if not complete:
            continue
        header_ok = plain[0] in (5, 0x85) and int(plain[1]) & 15 == 12
        fill_ok = bool(np.all(plain[96:] == 0xbb))
        crc_ok = crc(plain[:94]) == int.from_bytes(plain[94:96].tobytes(), 'big')
        row = dict(start=s['start'], header_ok=bool(header_ok), fill_ok=fill_ok,
                   crc_ok=bool(crc_ok), plaintext_hex=plain.tobytes().hex())
        checked.append(row)
        # CRC is the real test: it covers header+text and a wrong key cannot pass it
        # by chance (1 in 65536). Some message types carry a binary preamble instead
        # of the 0x05/0x85 header or lack the 0xBB fill, so those gates are recorded
        # but must not reject an otherwise CRC-valid segment.
        accepted = crc_ok and (fill_ok if require_fill else True)
        if accepted:
            row['text'] = plain[2:94].tobytes().decode('utf-16le', errors='replace')
            valid.append(row)
            for j in range(96):
                crc_supported[index[int(s['groups'][j])], j % 16] = True
    # Complete groups may carry the fixed idle message in place of scrolling
    # records. Both its exact bytes and its transmitted CRC check the prefix.
    complete = [int(c) for c in g['counters'] if all(3*int(c)+p in tails for p in range(3))]
    full_tails = np.array([[tails[3*c+p] for p in range(3)] for c in complete],
                          dtype=np.uint8).reshape(-1, 3, 16)
    idle, idle_ok = idle_prefixes(full_tails)
    for pos in np.flatnonzero(idle_ok):
        row = index[complete[pos]]
        if np.any(crc_supported[row] & (keys[row] != idle[pos])):
            raise ValueError(f'conflicting CRC-supported prefixes for group {complete[pos]}')
        keys[row] = idle[pos]
        candidate[row] = crc_supported[row] = True
    phrase_records = []
    if phrase_keys:
        from phrase_text_keys import recover_records
        phrase_records, confirmed = recover_records(tails, counters, keys, crc_supported)
        existing = {r['start'] for r in valid}
        for record in phrase_records:
            if record['start'] not in existing:
                valid.append(record)
        for c, key in confirmed.items():
            row = index[c]
            keys[row] = key
            candidate[row] = crc_supported[row] = True
    report = dict(acceptance=('crc + fill trailer' if require_fill else 'crc only'),
                  phrase_crc_records=len(phrase_records),
                  idle_crc_groups=int(idle_ok.sum()),
                  segment_hypotheses=len(segments), invariant_pair_comparisons=comparisons,
                  matched_pairs=matches, conflicting_pairs=rejected,
                  fully_keyed_complete_segments_tested=len(checked), crc_supported_segments=len(valid),
                  initial_full_candidate_groups=int(g['candidate_mask'].all(axis=1).sum()),
                  resulting_full_candidate_groups=int(candidate.all(axis=1).sum()),
                  crc_supported_key_bytes=int(crc_supported.sum()),
                  limitation='Invariants and fills are hypotheses; CRC16 is not authentication. '
                             'No CRC fitting/search was used.')
    out = Path(out)
    out.mkdir(parents=True, exist_ok=False)
    np.savez_compressed(out/'keys.npz', counters=counters, ks=keys,
                        candidate_mask=candidate, crc_supported=crc_supported,
                        verified=crc_supported)
    (out/'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    (out/'segments.json').write_text(json.dumps(checked, indent=2), encoding='utf-8')
    (out/'crc_supported_text.json').write_text(json.dumps(valid, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2), flush=True)


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('groups_npz'); ap.add_argument('units_npz'); ap.add_argument('--out', required=True)
    ap.add_argument('--require-fill', action='store_true',
                    help='also require the 0xBB fill; stricter, rejects message types '
                         'without a fill trailer')
    a = ap.parse_args()
    recover(a.groups_npz, a.units_npz, a.out, a.require_fill)
