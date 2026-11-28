"""Score the existing within-group EVS rules against independent 6140 kHz packet receipts.

The wire archives contain aligned tick, ordinal, native_row and 182-byte wire arrays.
Run from any directory. Optionally supply either original native MSC dump to verify
the source record indexes and its published whole-file digest.
"""
import argparse
from collections import Counter, defaultdict
from hashlib import sha256
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2] / 'scripts'))
from evs_evidence import bit_evidence, field_sections
from project_evs_group import checked_units, project_group
from salvage_msc_packets import PACKET_HEADERS, records
from tail_fill_audit import crc


def require(ok, message):
    if not ok:
        raise ValueError(message)


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def packets(path, units_path, ids, msc, msc_sha):
    native = None
    if msc:
        require(digest(msc) == msc_sha, 'original MSC digest differs')
        native = list(records(msc))
    result = {}
    with np.load(path, allow_pickle=False) as data:
        ticks, qs, refs, wires = (data[k] for k in ('tick', 'ordinal', 'native_row', 'wire'))
        require(ticks.dtype == np.int64 and qs.dtype == np.uint8 and refs.dtype == np.uint32 and
                wires.dtype == np.uint8 and ticks.ndim == 1 and qs.shape == refs.shape == ticks.shape and
                wires.shape == (len(ticks), 182), 'unexpected packet archive arrays')
        record_ticks = {}
        for tick, q, i, raw in zip(ticks.tolist(), qs.tolist(), refs.tolist(), wires, strict=True):
            c, ph = divmod(tick, 3)
            require(c in ids and 0 <= q < 4 and (tick,q) not in result, 'unexpected packet coordinate')
            require(record_ticks.setdefault(i, tick) == tick, 'native row assigned to two ticks')
            w = raw.tobytes()
            require(w[0] == PACKET_HEADERS[q] and crc(w[:-2]) == int.from_bytes(w[-2:], 'big'), 'packet header or CRC')
            body = w[1:-2]
            if q == 0:
                require(body[1] >> 4 == ph, 'phase disagrees with wire packet')
            if ph == 0 and q == 3:
                require(int.from_bytes(body[127:131], 'big') == c, 'counter disagrees with wire packet')
            if native is not None:
                row = native[i]
                require(row and row['index'] == i and row['packet_ok'][q] and row['payload'][q] == body,
                        'packet differs from its original native row')
            result[tick,q] = (body,i)
    require({t // 3 for t,q in result} == ids, 'incomplete counter scope')
    full = {t: b''.join(result[t,i][0] for i in range(4))
            for t,q in result if q == 0 and all((t,i) in result for i in range(4))}
    published = {3*c+ph: du for c,ph,du in checked_units(units_path) if c in ids}
    require(full == published, 'complete data units differ from the published validated archive')
    return result, full


def packet_snapshot(packets, dest):
    ticks = np.array(sorted({t for t,q in packets}), dtype=np.int64)
    bodies = np.zeros((len(ticks),4,179), np.uint8)
    ok = np.zeros((len(ticks),4), np.bool_)
    for j,t in enumerate(ticks.tolist()):
        for q in range(4):
            if (t,q) in packets:
                bodies[j,q] = np.frombuffer(packets[t,q][0], np.uint8)
                ok[j,q] = True
    np.savez(dest, ticks=ticks, packets=bodies, packet_ok=ok)


def stage_member(packet_path, ids):
    stage = []
    for c in sorted(ids):
        group = project_group(packet_path, c, packets=True)
        evidence = bit_evidence(group | field_sections(group['slots']))
        for slot in evidence['slots']:
            rules = []
            for event in slot['events']:
                a, z = event['word_bits']
                if event['kind'] == 'direct_check':
                    require(all(i['slot'] != slot['slot'] or i['word_bits'][1] <= a or z <= i['word_bits'][0]
                                for i in event['inputs']), 'target also used as a predictor')
                rules.append([event['check'], event['kind'], a, z, event['allowed_values'], event['fixed_bits']])
            stage.append([c, slot['slot'], slot['octets'], slot['receipt'] == 'received_du', rules])
    return stage


def wire_offsets(slot):
    # Slots repeat five 4-word cycles per phase. The five P1 modes precede the first payload.
    cycle, role = divmod(slot % 20, 4)
    payload = 7 + 131*cycle + 33*role
    return {0: 2 + cycle if role == 0 else payload-1} | {1+i: payload+i for i in range(32) if i%3}


def score(stage, member, peer, peer_full):
    positions, by_rule = defaultdict(Counter), defaultdict(Counter)
    peer_only = []
    for c, slot, observed, full, rules in stage:
        ph, pos = slot // 20, slot % 4 + 1
        tick, offsets = 3*c+ph, wire_offsets(slot)
        own = observed.split()
        counts = positions[pos]
        counts['slots'] += 1
        on_both_dus = full and tick in peer_full
        peer_bits = {}
        for j, at in offsets.items():
            q, k = divmod(at,179)
            a = None if own[j] == '--' else int(own[j],16)
            b = peer[tick,q][0][k] if (tick,q) in peer else None
            if b is not None:
                peer_bits.update({8*j+i: b >> (7-i) & 1 for i in range(8)})
            if a is not None and b is not None:
                counts['common_direct_bits'] += 8
                counts['differing_direct_bits'] += (a^b).bit_count()
                if not on_both_dus:
                    counts['common_direct_bits_outside_paired_complete_dus'] += 8
            else:
                side = 'member_only' if a is not None else 'peer_only' if b is not None else 'neither'
                counts[side+'_direct_bits'] += 8
        categories = defaultdict(set)
        conditional = defaultdict(set)
        for name, kind, a, z, allowed, fixed in rules:
            report = by_rule[name]
            if kind == 'conditional':
                report['conditional_events'] += 1
                for b, val in fixed.items():
                    b = int(b)
                    require(b//8 not in offsets, 'conditional target mistyped as concealed')
                    conditional[b].add(val)
                continue
            report['applicable'] += 1
            categories['field_bits_eligible'].update(range(a,z))
            categories['exact_bits_eligible'].update(map(int,fixed))
            if any(b not in peer_bits for b in range(a,z)):
                report['peer_unavailable'] += 1
                continue
            val = sum(peer_bits[b] << (z-b-1) for b in range(a,z))
            report['peer_matches' if val in allowed else 'peer_mismatches'] += 1
            categories['field_bits_checked'].update(range(a,z))
            for b, pred in fixed.items():
                b = int(b)
                categories['exact_bits_checked'].add(b)
                if pred != peer_bits[b]:
                    categories['exact_bits_wrong'].add(b)
                if not on_both_dus:
                    categories['exact_bits_checked_outside_paired_complete_dus'].add(b)
            if any(own[b//8] == '--' for b in range(a,z)):
                j = a//8
                require(j == (z-1)//8, 'peer-only field crosses octets')
                q, k = divmod(offsets[j],179)
                mode_q = offsets[0]//179
                peer_only.append(dict(counter=c,slot=slot,phase=ph,cycle=slot%20//4,position=pos,
                                      check=name,word_bits=[a,z],allowed=allowed,observed=val,
                                      member_mode=own[0],member_mode_q=mode_q,member_mode_native_row=member[tick,mode_q][1],
                                      peer_q=q,peer_native_row=peer[tick,q][1],peer_du_offset=offsets[j],
                                      peer_octet=f'{peer[tick,q][0][k]:02x}'))
                categories['peer_only_field_bits'].update(range(a,z))
                categories['peer_only_exact_bits'].update(map(int,fixed))
        for key,bits in categories.items():
            counts[key] += len(bits)
        counts['conditional_fixed_hidden_bits'] += sum(len(v)==1 for v in conditional.values())
        counts['conditional_conflicting_bits'] += sum(len(v)>1 for v in conditional.values())
    for counts in positions.values():
        for key in ('exact_bits_wrong', 'peer_only_exact_bits', 'peer_only_field_bits'):
            counts.setdefault(key, 0)
    for counts in by_rule.values():
        if 'applicable' in counts:
            counts.setdefault('peer_mismatches', 0)
    return positions, by_rule, peer_only


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--member', type=Path, default=HERE/'dual-3205.npz')
    ap.add_argument('--edogawa', type=Path, default=HERE/'dual-6140.npz')
    ap.add_argument('--member-msc', type=Path, help='optional original MLC1 member window 0 native MSC dump')
    ap.add_argument('--edogawa-msc', type=Path, help='optional original Edogawa native MSC dump')
    ap.add_argument('--out', type=Path, help='write JSON output here (default stdout)')
    args = ap.parse_args()
    prior_dir = HERE.parent / 'member-3205-20min'
    prior = json.loads((prior_dir/'cross-frequency.json').read_text())
    sources = prior['sources']
    msc_sha = sources['raw_msc_sha256']
    ids = set(prior['historical_exposure']['member_historical_counter_ids'])
    m_path, p_path = args.member, args.edogawa
    member, m_units = packets(m_path, prior_dir/'member-dus.npz', ids, args.member_msc, msc_sha['member_3205_mlc1_window0'])
    with TemporaryDirectory() as tmp:
        src = Path(tmp)/'packets.npz'
        packet_snapshot(member, src)
        stage = stage_member(src, ids)
    stage_hash = sha256(json.dumps(stage, sort_keys=True, separators=(',',':')).encode()).hexdigest()
    peer, p_units = packets(p_path, HERE.parents[2]/sources['edogawa_6140_du_archive'], ids, args.edogawa_msc, msc_sha['edogawa_6140'])
    pos, rules, peer_only = score(stage, member, peer, p_units)
    totals = Counter()
    for counts in pos.values():
        totals.update(counts)
    label_inventory = prior['historical_labels']
    require(label_inventory['member_matching_label_counters'] == 0, 'review historical label overlaps')
    result = dict(scope='Retrospective within-group rules over all mutually assigned counter IDs. The two receivers capture the same transmitted frames.',
                  coordinate_basis='Previously assigned counter/phase/ordinal. Complete DUs match the published CRC-checked archives. Partial-packet assignments retain their receiver provenance; header and CRC alone do not encode every coordinate.',
                  rule_basis='Exact bits are individually fixed. Field-bit totals also include bits checked only for membership in a set. The INACTIVE upper-nibble rule is empirical.',
                  projection_source_commit='30a3b2fee0f0f1822329a2455814adb958c4f40c',
                  member_projection_sha256=stage_hash,shared_counters=len(ids),counter_list_source='../member-3205-20min/cross-frequency.json#historical_exposure.member_historical_counter_ids',
                  nominal_direct_bits_per_position=15*176*len(ids),member_wire_packets=len(member),
                  edogawa_wire_packets=len(peer),common_complete_dus=len(m_units.keys() & p_units.keys()),
                  inputs_sha256=dict(member_packet_archive=digest(m_path),edogawa_packet_archive=digest(p_path),
                                     member_window0_native_msc=msc_sha['member_3205_mlc1_window0'],edogawa_native_msc=msc_sha['edogawa_6140'],
                                     member_iq=sources['member_iq_sha256'],edogawa_iq=sources['edogawa_6140_flac_sha256']),
                  independent_hidden_labels=dict(coordinates_sha256=label_inventory['coordinate_index_sha256'],
                                                 labelled_bits=0,source='../member-3205-20min/cross-frequency.json#historical_labels'),
                  total=totals,by_position=pos,by_rule=rules,only_peer_crc_accepted_targets=peer_only,
                  unavailable_targets='A missing packet is missing from the CRC-accepted input. It can still have a failed-CRC native row. At counter 43908300 the rejected member q1 also contained C1 at DU byte 273; no byte from it entered the rule.')
    output = json.dumps(result,sort_keys=True,indent=2)+'\n'
    if args.out:
        args.out.write_text(output)
    else:
        print(output,end='')


if __name__ == '__main__':
    main()
