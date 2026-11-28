"""Check the projected p24 pair on the 56 complete stock narrowband sender controls."""
import argparse
import hashlib
import json
from pathlib import Path
import struct

HERE = Path(__file__).resolve().parent
RECORD = struct.Struct('<266H')


def allowed_p24_pairs(mode, p7, p25):
    """Use three directly carried octets. Each candidate is a two-bit integer."""
    if mode != 0x13:
        raise ValueError("expected the narrowband transition tag 011 in the clear mode octet")
    p_lo = p7 >> 4
    j_lo = p25 >> 3
    smallest_odd_branch = 78 - 2 * p_lo
    result = []
    for high in range(4):
        j = (high << 5) | j_lo
        if j <= 126 and (j % 2 == 0 or j >= smallest_odd_branch):
            result.append(high)
    return result


def check_table():
    # Enumerate stock encoder integer lag domains without using the projected formula.
    domains = {}
    for p in range(64):
        first = 192 - p
        split = 279 - 2 * p
        for lag in range(first, 232):
            j = 2 * (lag - first) if lag < split else lag + split - 2 * first
            key = p & 15, j & 31
            domains.setdefault(key, set()).add(j >> 5)
    for p_lo in range(16):
        for j_lo in range(32):
            actual = set(allowed_p24_pairs(0x13, p_lo << 4, j_lo << 3))
            if actual != domains[p_lo, j_lo]:
                raise ValueError("projected formula disagrees with integer-lag enumeration")


def read_original(path, expected):
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != expected['g192_sha256']:
        raise ValueError(f"full G.192 hash differs for {expected['id']}")
    if len(data) != expected['total_words'] * RECORD.size:
        raise ValueError("unexpected G.192 extent")
    selected = []
    for slot, raw in enumerate(RECORD.iter_unpack(data)):
        if raw[:2] != (0x6b21, 264) or not set(raw[2:]) <= {0x7f, 0x81}:
            raise ValueError(f"invalid stock word at slot {slot}")
        mode = sum((n == 0x81) << (7-i) for i, n in enumerate(raw[2:10]))
        if mode == 0x13:
            integer = 0
            for n in raw[2:]:
                integer = (integer << 1) | (n == 0x81)
            selected.append([slot, integer.to_bytes(33, 'big').hex()])
    if selected != expected['rows']:
        raise ValueError("selected 0x13 words or source slot coordinates differ")


def check(fixture, supplied_originals):
    if fixture['format'] != 'evs-13k2-nb-transition-pitch-v1':
        raise ValueError("unexpected fixture schema")
    check_table()
    by_stream = {}
    distinct = set()
    restrictive = []
    for source in fixture['streams']:
        label = source['id']
        if label in by_stream:
            raise ValueError("duplicate source stream")
        by_stream[label] = source
        seen = set()
        for slot, word_hex in source['rows']:
            word = bytes.fromhex(word_hex)
            if len(word) != 33 or not 0 <= slot < source['total_words'] or slot in seen:
                raise ValueError("malformed sender word or slot")
            seen.add(slot)
            distinct.add(word)
            # Physical byte 0 is the separate mode octet.
            allowed = allowed_p24_pairs(word[0], word[8], word[26])
            held_back = word[25] & 3
            if held_back not in allowed:
                raise ValueError(f"sender pair excluded at {label} slot {slot}")
            if len(allowed) < 4:
                restrictive.append(dict(stimulus=label, slot=slot, position=slot%4+1,
                    p_7_high_nibble=word[8]>>4, p_25_top5=word[26]>>3,
                    allowed=allowed, observed_p24_lowpair=held_back))
        if len(seen) != source['word_count']:
            raise ValueError("wrong stream row count")
    total = sum(v['word_count'] for v in by_stream.values())
    if (total, len(distinct), restrictive) != (fixture['word_count'], fixture['unique_complete_words'],
                                                 fixture['expected_restrictive_vectors']):
        raise ValueError("fixture counts or predeclared vectors differ")
    for label, name in supplied_originals:
        if label not in by_stream:
            raise ValueError(f"unknown stream {label}")
        read_original(Path(name), by_stream[label])
    return dict(complete_words=total, unique_complete_words=len(distinct), streams={s:v['word_count'] for s,v in by_stream.items()},
                visible_fragment_combinations_checked=512, restrictive=restrictive,
                alternatives_excluded=sum(4-len(r['allowed']) for r in restrictive),
                full_originals_verified=[label for label, _ in supplied_originals])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('fixture', nargs='?', type=Path, default=HERE/'nb-fixture.json')
    parser.add_argument('--g192', nargs=2, metavar=('STREAM', 'FILE'), action='append', default=[],
                        help='also check a complete, hash-pinned stock sender stream')
    args = parser.parse_args()
    try:
        result = check(json.loads(args.fixture.read_bytes()), args.g192)
    except (ValueError, OSError, KeyError) as exc:
        parser.exit(2, f"{exc}\n")
    print(json.dumps(result,indent=2))


if __name__ == '__main__':
    main()
