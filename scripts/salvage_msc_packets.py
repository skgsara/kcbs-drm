"""Salvage CRC-good packet payloads across repeated observations of an MSC group.

Counter assignment requires either a complete CRC-good 0/1/2 group, or a
0/1/2/0 sequence with CRC-good first packets and CRC-good counter-containing
packets at both ends whose counters differ by one. Standalone phase-0 records
may contribute when their first and counter packets pass CRC. Packet alternatives
are never guessed: conflicting payloads are quarantined. A CRC-good packet with
an unexpected header or an intact four-packet record with a bad DU CRC breaks
the coordinate sequence. Reassembled DUs must pass their own CRC.
"""
import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import struct

import numpy as np
from tail_fill_audit import crc, fill_candidates

PACKET_HEADERS = (0x80, 0x01, 0x02, 0x43)


def records(path, *, rejected_records=None):
    with open(path, 'rb') as f:
        index = 0
        while True:
            h = f.read(4)
            if not h:
                return
            if len(h) != 4:
                raise ValueError(f'truncated record header in {path}')
            n, = struct.unpack('<I', h)
            if not 0 < n <= 1024*1024:
                raise ValueError(f'bad record length {n} in {path}')
            raw = f.read(n)
            if len(raw) != n:
                raise ValueError(f'truncated record in {path}')
            if n == 728:
                p = [raw[q*182+1:q*182+180] for q in range(4)]
                good = [crc(raw[q*182:q*182+180]) == int.from_bytes(raw[q*182+180:q*182+182], 'big')
                        for q in range(4)]
                du = b''.join(p)
                complete = all(good)
                reason = None
                if any(ok and raw[q*182] != PACKET_HEADERS[q] for q, ok in enumerate(good)):
                    reason = 'unexpected_packet_header'
                elif complete and crc(du[:714]) != int.from_bytes(du[714:], 'big'):
                    reason = 'complete_du_crc'
                if reason is not None:
                    if rejected_records is not None:
                        rejected_records[reason] += 1
                    yield None
                else:
                    yield dict(index=index, payload=p, packet_ok=good, du=du,
                               phase=du[1] >> 4, counter=int.from_bytes(du[664:668], 'big'),
                               complete=complete)
            else:
                yield None  # preserve barriers between unexpected records
            index += 1


def salvage(paths, out, *, transport_only=False, save_packets=False):
    payloads = defaultdict(set)
    provenance = defaultdict(list)
    baseline = set()
    assignments = 0
    rejected_records = Counter()
    for path in paths:
        recs = list(records(path, rejected_records=rejected_records))
        assigned = defaultdict(set)
        for i, r in enumerate(recs):
            if r and r['phase'] == 0 and r['packet_ok'][0] and r['packet_ok'][3]:
                assigned[i].add((r['counter'], 0))
        for i in range(len(recs)-2):
            group = recs[i:i+3]
            if all(r and r['complete'] for r in group) and [r['phase'] for r in group] == [0, 1, 2]:
                c = group[0]['counter']
                baseline.add(c)
                for p in range(3):
                    assigned[i+p].add((c, p))
        for i in range(len(recs)-3):
            block = recs[i:i+4]
            if not all(r and r['packet_ok'][0] for r in block):
                continue
            if [r['phase'] for r in block] != [0, 1, 2, 0]:
                continue
            if not (block[0]['packet_ok'][3] and block[3]['packet_ok'][3]):
                continue
            c = block[0]['counter']
            if block[3]['counter'] != (c+1) % (1 << 32):
                continue
            for p in range(3):
                assigned[i+p].add((c, p))
        for i, candidates in assigned.items():
            if len(candidates) != 1:
                continue
            counter, phase = next(iter(candidates))
            r = recs[i]
            assignments += 1
            for q, good in enumerate(r['packet_ok']):
                if good:
                    key = (counter, phase, q)
                    payloads[key].add(r['payload'][q])
                    provenance[key].append((str(path), r['index']))
    dus = {}
    conflicts = []
    crc_fail = 0
    ticks, packet_flags = [], []
    packet_bodies = bytearray()
    missing_packet = bytes(179)
    for c, p in sorted({(c, p) for c, p, q in payloads}):
        possibilities = [payloads.get((c, p, q), set()) for q in range(4)]
        if any(len(v) > 1 for v in possibilities):
            conflicts.append((c, p))
            continue
        present = [bool(v) for v in possibilities]
        complete = all(present)
        if not complete and not save_packets:
            continue
        du = b''.join(next(iter(v), missing_packet) for v in possibilities)
        if complete:
            if crc(du[:714]) != int.from_bytes(du[714:], 'big'):
                crc_fail += 1
                continue
            dus[c, p] = du
        if save_packets:
            ticks.append(3*c + p)
            packet_bodies.extend(du)
            packet_flags.append(present)
    counters = np.array([c for c in sorted({c for c, p in dus})
                         if all((c, p) in dus for p in range(3))], dtype=np.uint32)
    du = np.array([list(dus[int(c), p]) for c in counters for p in range(3)],
                  dtype=np.uint8).reshape(-1, 3, 716)
    tails = du[:, :, 698:714]
    keys = np.zeros((len(counters), 16), np.uint8)
    mask = np.zeros_like(keys, bool)
    offsets = np.full(len(counters), -1, dtype=np.int16)
    if not transport_only:
        for i in range(len(counters)):
            candidates = fill_candidates(tails[i])
            if len(candidates) == 1:
                keys[i] = candidates[0]['key']
                mask[i] = True
                offsets[i] = candidates[0]['offset']
    report = dict(files=len(paths), assigned_record_observations=assignments,
                  original_complete_groups=len(baseline), salvaged_complete_groups=len(counters),
                  extra_groups=len(set(map(int, counters)) - baseline),
                  missing_baseline_groups=sorted(baseline - set(map(int, counters))),
                  crc_good_data_units=len(dus), conflicting_data_units=conflicts,
                  reassembly_crc_failures=crc_fail,
                  candidate_key_groups=int(mask.all(axis=1).sum()),
                  verified_text_key_groups=0,
                  note='Packet/DU CRCs verify container integrity, not text or codec keys.')
    if rejected_records:
        report['rejected_record_observations'] = dict(rejected_records)
    if transport_only:
        report['text_candidates_evaluated'] = False
    out = Path(out)
    out.mkdir(parents=True, exist_ok=False)
    np.savez_compressed(out/'groups.npz', counters=counters, du=du, tails=tails,
                        candidate_ks=keys, candidate_mask=mask, fill_offset=offsets,
                        verified=np.zeros_like(mask))
    partial_indices = sorted(dus)
    np.savez_compressed(out/'data_units.npz',
                        counters=np.array([c for c,p in partial_indices], np.uint32),
                        phases=np.array([p for c,p in partial_indices], np.uint8),
                        du=np.array([list(dus[k]) for k in partial_indices], np.uint8).reshape(-1,716))
    if save_packets:
        np.savez_compressed(out/'packets.npz', ticks=np.asarray(ticks, dtype=np.int64),
                            packets=np.frombuffer(packet_bodies, np.uint8).reshape(-1, 4, 179),
                            packet_ok=np.asarray(packet_flags, dtype=bool).reshape(-1, 4))
    (out/'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    (out/'provenance.json').write_text(json.dumps({','.join(map(str,k)): v for k,v in provenance.items()}),
                                       encoding='utf-8')
    print(json.dumps(report, indent=2), flush=True)


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('inputs', nargs='+')
    ap.add_argument('--out', required=True)
    ap.add_argument('--transport-only', action='store_true', help='assemble received data units and skip text candidates')
    ap.add_argument('--save-packets', action='store_true',
                    help='write packets.npz with CRC-good packet bodies and receipt flags for complete and partial phases')
    a = ap.parse_args()
    salvage(a.inputs, a.out, transport_only=a.transport_only, save_packets=a.save_packets)
