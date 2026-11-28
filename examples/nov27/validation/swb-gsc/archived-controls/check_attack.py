"""Check early 13.2 kb/s P1 GSC fields using existing public receiver and text evidence."""
from collections import Counter, defaultdict
from hashlib import sha256
import json
from pathlib import Path
import sys

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / 'hq-class'))
from archived import CONTRIB, INPUTS, transport
from parse_text_records import crc
from review_supplied_records import review
from tail_fill_audit import idle_prefixes, read_groups


def column_error_rank(length, columns):
    """CRC syndrome rank with one shared 8-bit change per column and other bytes fixed."""
    basis = {}
    for offsets in columns:
        for bit in range(8):
            change = bytearray(length)
            for offset in offsets:
                change[offset] = 1 << bit
            syndrome = crc(change) ^ crc(bytes(length))
            while syndrome:
                pivot = syndrome.bit_length()
                if pivot not in basis:
                    basis[pivot] = syndrome
                    break
                syndrome ^= basis[pivot]
    return len(basis)


def ordinary_groups():
    units, origins, _, _ = transport()
    labels, records, starts = {}, [], defaultdict(set)
    for tag in sorted(set(INPUTS.values())):
        coords = sorted(k for k, names in origins.items() if any(INPUTS[name] == tag for name in names))
        path = CONTRIB / 'keys' / f'keys_{tag}.npz'
        with np.load(path, allow_pickle=False) as archive:
            counters, prefixes, flags = (archive[k] for k in ('counters', 'ks', 'crc_supported'))
        checked, accepted = review(counters, prefixes, flags, *map(np.array, zip(*coords)),
                                   np.array([units[k] for k in coords]))
        for counter, prefix, reviewed in zip(counters, prefixes, checked, strict=True):
            if not reviewed[:11].all():
                continue
            if int(counter) in labels:
                raise ValueError('capture families overlap')
            labels[int(counter)] = (tag, int(prefix[1]) & 1)
        for row in accepted:
            start = 3 * row['counter'] + row['phase']
            body = bytes.fromhex(row['header_hex']) + row['text'].encode('utf-16le')
            checksum = crc(body)
            signature = sha256(body + checksum.to_bytes(2, 'big')).hexdigest()
            starts[signature].add(start)
            records.append((tag, start, len(body), checksum, signature))

    eligible = {}
    for tag, start, length, checksum, signature in records:
        if len(starts[signature]) < 2:
            continue
        for counter in range(start // 3, (start + (length + 1) // 16) // 3 + 1):
            if counter not in labels or labels[counter][0] != tag:
                continue
            offsets = [[16 * (3 * counter + phase - start) + col for phase in range(3)] for col in range(11)]
            protected = [[i for i in group if 0 <= i < length] for group in offsets]
            if not all(protected) or any(i in (length, length + 1) for group in offsets[8:10] for i in group):
                continue
            if column_error_rank(length, protected[8:10]) == 16:
                bit = labels[counter][1]
                evidence = dict(record_start=divmod(start, 3), crc16=f'{checksum:04x}',
                                repeated_starts=[divmod(t, 3) for t in sorted(starts[signature] - {start})],
                                record_sha256=signature, protected_column_1_offsets=protected[1],
                                stored_crc_column_1_offsets=[i for i in offsets[1] if i in (length, length + 1)],
                                fixed_checksum_column_1_rank=column_error_rank(length, [protected[1]]))
                eligible.setdefault(counter, (bit, evidence))
    for counter in sorted(eligible):
        bit, evidence = eligible[counter]
        yield counter, [units[counter, p] for p in range(3)], bit, evidence


def march_groups():
    path = CONTRIB / 'reference/sf_signon_3205_2026-03-16.bin'
    counters, units, _, conflicts, _ = read_groups([path])
    if conflicts:
        raise ValueError('conflicting March data units')
    labels, accepted = idle_prefixes(units[:, :, 698:714])
    for c, group, label, ok in zip(counters, units, labels, accepted, strict=True):
        if ok:
            yield int(c), group, int(label[1]) & 1, None


def count(groups):
    counts = Counter()
    positive = []
    for counter, phases, column_lsb, witness in groups:
        counts['available_counters'] += 1
        eligible = 0
        for phase, unit in enumerate(phases):
            for cycle in range(5):
                mode = int(unit[2 + cycle])
                if mode >> 3 != 14:
                    continue
                if not mode & 4:
                    raise ValueError('unexpected SWB INACTIVE extension selector')
                start = 7 + 131 * cycle
                attack = (int(unit[start + 3]) & 1) ^ column_lsb
                nibble = int(unit[start + 4]) >> 4
                counts[f'b39_{attack}'] += 1
                counts[f'b40_to_b43_{nibble:04b}'] += 1
                eligible += 1
                if attack:
                    positive.append(dict(counter=counter, phase=phase, cycle=cycle, slot=20 * phase + 4 * cycle,
                                         position=1, mode=f'{mode:02x}', text=witness))
        counts['eligible_words'] += eligible
        counts['eligible_counters'] += bool(eligible)
    counts.setdefault('b39_1', 0)
    return dict(counts=counts, b39_one_observations=positive)


if __name__ == '__main__':
    print(json.dumps(dict(march=count(march_groups()), ordinary=count(ordinary_groups())), indent=2))
