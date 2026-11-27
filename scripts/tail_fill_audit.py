"""Audit byte-offset fill cribs without labelling plausible keys verified.

Reads bounded length-prefixed MSC records; checks packet and DU CRCs. Deduplicates
complete groups by counter, rejects conflicting copies, and preserves record
provenance. Candidate keys require a header plus text plausibility (or text only
when the header is outside the group). Neither is a segment CRC verification.
"""
import argparse
import binascii
from collections import Counter
import json
from pathlib import Path
import struct

import numpy as np


def crc(data):
    return binascii.crc_hqx(bytes(data), 0xffff) ^ 0xffff


def idle_prefixes(tails):
    """Derive a prefix from phase 0 and check the exact idle message and its CRC."""
    idle = tails[:, 0] ^ 255
    msg = np.concatenate((tails[:, 1] ^ idle, tails[:, 2] ^ idle), axis=1)
    known = b'\x68\xf0TextMessage is sending...'
    idle_ok = np.array([bytes(m[:27]) == known and
                        crc(m[:27]) == int.from_bytes(bytes(m[27:29]), 'big')
                        for m in msg], dtype=bool)
    return idle, idle_ok


def read_groups(paths):
    groups, origins, conflicts, stats = {}, {}, set(), []
    for path in paths:
        recent = []
        counts = Counter()
        with open(path, 'rb') as f:
            while True:
                head = f.read(4)
                if not head:
                    break
                if len(head) != 4:
                    counts['truncated'] += 1
                    break
                n, = struct.unpack('<I', head)
                if not 0 < n <= 1024 * 1024:
                    raise ValueError(f'{path}: invalid record length {n}')
                record = f.read(n)
                if len(record) != n:
                    counts['truncated'] += 1
                    break
                idx = counts['records']
                counts['records'] += 1
                if n != 728:
                    recent.clear()
                    continue
                du = b''.join(record[q*182+1:q*182+180] for q in range(4))
                good = all(crc(record[q*182:q*182+180]) ==
                           int.from_bytes(record[q*182+180:q*182+182], 'big')
                           for q in range(4)) and crc(du[:714]) == int.from_bytes(du[714:], 'big')
                counts['crc_good'] += good
                recent.append((du, good, idx))
                recent = recent[-3:]
                if len(recent) < 3 or not all(r[1] for r in recent):
                    continue
                if [r[0][1] >> 4 for r in recent] != [0, 1, 2]:
                    continue
                c = int.from_bytes(recent[0][0][664:668], 'big')
                payload = b''.join(r[0] for r in recent)
                counts['group_occurrences'] += 1
                if c in groups and groups[c] != payload:
                    conflicts.add(c)
                else:
                    groups[c] = payload
                    origins.setdefault(c, []).append((str(path), recent[0][2]))
        stats.append(dict(path=str(path), **counts))
    for c in conflicts:
        groups.pop(c, None)
        origins.pop(c, None)
    counters = np.array(sorted(groups), dtype=np.uint32)
    du = np.array([list(groups[int(c)]) for c in counters], dtype=np.uint8).reshape(-1, 3, 716)
    return counters, du, origins, conflicts, stats


def text_unit(c):
    return (0xac00 <= c <= 0xd7a3 or 0x3130 <= c <= 0x318f or
            0x20 <= c <= 0x7e or c in (10, 13, 0x2103, 0xb0, 0x33a7))


def fill_candidates(tails):
    """Full 16-byte fill may start at any code-unit boundary, not just a tail."""
    data = np.asarray(tails, np.uint8).reshape(48)
    found = []
    for offset in range(0, 33, 2):
        key = np.zeros(16, np.uint8)
        for j in range(16):
            key[(offset + j) % 16] = int(data[offset + j]) ^ 0xbb
        plain = data ^ np.tile(key, 3)
        h = offset + 16
        header = h + 2 <= 48
        if header and not (plain[h] in (5, 0x85) and int(plain[h+1]) & 15 == 12):
            continue
        # Relative segment position: fill 96..111; CRC 94..95, header 0..1.
        text_positions = [j for j in range(0, 48, 2)
                          if 2 <= ((j - offset + 96) % 112) < 94]
        score = sum(text_unit(int(plain[j]) | int(plain[j+1]) << 8) for j in text_positions)
        if score < len(text_positions) - 1:
            continue
        found.append(dict(offset=offset, key=key, plain=plain,
                          header_checked=header, text_good=score,
                          text_total=len(text_positions)))
    return found


def audit(paths, out):
    counters, du, origins, conflicts, stats = read_groups(paths)
    tails = du[:, :, 698:714]
    keys = np.zeros((len(counters), 16), np.uint8)
    candidate_mask = np.zeros_like(keys, dtype=bool)
    offsets = np.full(len(counters), -1, dtype=np.int16)
    grids, ambiguous, accepted = Counter(), 0, []
    for i, c in enumerate(counters):
        candidates = fill_candidates(tails[i])
        if len(candidates) != 1:
            ambiguous += len(candidates) > 1
            continue
        cand = candidates[0]
        keys[i] = cand['key']
        candidate_mask[i] = True
        offsets[i] = cand['offset']
        grid = (48 * int(c) + cand['offset'] + 16) % 112
        grids[grid] += 1
        accepted.append(dict(counter=int(c), offset=cand['offset'], grid=grid,
                             header_checked=cand['header_checked'],
                             text_good=cand['text_good'], text_total=cand['text_total'],
                             plaintext_hex=cand['plain'].tobytes().hex()))
    idle, idle_ok = idle_prefixes(tails)
    counts = dict(files=stats, groups=len(counters), conflicts=len(conflicts),
                  counter_min=int(counters.min()) if len(counters) else None,
                  counter_max=int(counters.max()) if len(counters) else None,
                  unique_fill_candidates=len(accepted), ambiguous_groups=int(ambiguous),
                  aligned_fill_candidates=sum(a['offset'] % 16 == 0 for a in accepted),
                  unaligned_fill_candidates=sum(a['offset'] % 16 != 0 for a in accepted),
                  header_grids=dict(grids.most_common()), idle_crc_matches=int(idle_ok.sum()),
                  note='Fill candidates are NOT segment-CRC-verified keys.')
    out = Path(out)
    out.mkdir(parents=True, exist_ok=False)
    np.savez_compressed(out / 'groups.npz', counters=counters, du=du, tails=tails,
                        candidate_ks=keys, candidate_mask=candidate_mask,
                        fill_offset=offsets, verified=np.zeros_like(candidate_mask),
                        idle_ks=idle, idle_text_crc_ok=idle_ok)
    (out / 'audit.json').write_text(json.dumps(counts, indent=2), encoding='utf-8')
    (out / 'candidates.json').write_text(json.dumps(accepted, indent=2), encoding='utf-8')
    (out / 'provenance.json').write_text(json.dumps(origins), encoding='utf-8')
    print(json.dumps(counts, indent=2), flush=True)


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('inputs', nargs='+')
    ap.add_argument('--out', required=True)
    args = ap.parse_args()
    audit(args.inputs, args.out)
