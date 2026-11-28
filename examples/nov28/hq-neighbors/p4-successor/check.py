"""Cold-read the five frozen 13:17 first-position words with TS 26.443."""
import argparse
from binascii import crc_hqx
from hashlib import sha256
import json
from pathlib import Path
import struct
import subprocess
import tempfile


BASE = Path(__file__).resolve().parent
FIXTURE_HASH = 'c1aa843ff338c5e92c30b83e7a3e59c5c7b8d6cf031adede4ea30e632be0ce42'
SOURCE_HASH = '1bd289bf0d8cc9143207c4de04fb2561ce848a3c9661306b18371dc4d8f1bd35'


def require(test, message):
    if not test:
        raise ValueError(message)


def digest(path):
    with path.open('rb') as fp:
        return sha256(fp.read()).hexdigest()


def word_frame(word):
    require(len(word) == 33, 'wrong EVS word length')
    bits = [(byte >> shift) & 1 for byte in word for shift in range(7, -1, -1)]
    return struct.pack('<266H', 0x6b21, 264, *(0x81 if bit else 0x7f for bit in bits))


def crc(data):
    return crc_hqx(data, 0xffff) ^ 0xffff


def check_text(group):
    covered = set()
    for row in group['supporting_text']:
        data = bytes.fromhex(row['header_body_crc_hex'])
        require(len(data) == row['body_length'] + 4, 'text record length')
        expected = int(row['crc16'], 16)
        require(crc(data[:-2]) == int.from_bytes(data[-2:], 'big') == expected, 'text CRC')
        start_tick = 3 * row['counter'] + row['phase']
        start_group = 3 * group['counter']
        columns = {col for tick in range(start_group, start_group + 3) for col in range(11)
                   if 0 <= 16 * (tick - start_tick) + col < len(data)}
        require(sorted(columns) == row['header_body_crc_key_columns'], 'text column geometry')
        covered.update(columns)
    require(covered == set(range(11)), 'incomplete text-CRC coverage of first-position columns')


def check_data_units(fixture, received_du):
    checked = {}
    for group in fixture['clean_counters']:
        c = group['counter']
        for row in group['data_units']:
            p = row['phase']
            du = received_du(c, p)
            require(len(du) == 716 and sha256(du).hexdigest() == row['sha256'], 'DU digest')
            require(du[1] >> 4 == p, 'phase in DU')
            if p == 0:
                require(int.from_bytes(du[664:668], 'big') == c, 'counter in DU')
            expected = int(row['crc16'], 16)
            require(crc(du[:-2]) == int.from_bytes(du[-2:], 'big') == expected, 'DU CRC')
            checked[c, p] = du
    for case in fixture['cases']:
        p1, p4 = case['supplied_p1'], case['preceding_p4']
        a = checked[p1['counter'], p1['phase']]
        b = checked[p4['counter'], p4['phase']]
        start = 7 + 131 * p1['cycle']
        projection = bytes([a[2 + p1['cycle']]] + [a[start + j] for j in range(32) if j % 3])
        require(projection.hex() == p1['raw_direct_projection_hex'], 'on-air P1 projection')
        require(b[105 + 131 * p4['cycle']] == 0xf8, 'on-air P4 mode')


def check_included_data_units(fixture):
    info = fixture['included_du_fixture']
    data = (BASE / info['file']).read_bytes()
    require(len(data) == info['bytes'] == 9 * 716, 'bundled DU length')
    require(sha256(data).hexdigest() == info['sha256'], 'bundled DU file hash')
    groups = [g['counter'] for g in fixture['clean_counters']]
    require(len(set(groups)) == len(groups) == 3, 'bundled DU counters')

    def received_du(counter, phase):
        start = 716 * (3 * groups.index(counter) + phase)
        return data[start:start + 716]

    check_data_units(fixture, received_du)


def check_packet_snapshot(path, fixture):
    import numpy as np

    require(digest(path) == fixture['input_sha256']['joined_packet_archive'], 'packet archive hash')
    with np.load(path, allow_pickle=False) as f:
        ticks, units, flags = f['ticks'], f['packets'], f['packet_ok']
    rows = {int(t): i for i, t in enumerate(ticks)}

    def received_du(counter, phase):
        i = rows[3 * counter + phase]
        require(flags[i].all(), 'incomplete DU in original packet archive')
        return units[i].tobytes()

    check_data_units(fixture, received_du)


def check_g192(path, fixture):
    require(digest(path) == fixture['input_sha256']['ordinary_g192'], 'full G.192 hash')
    targets = {r['supplied_p1']['slot']: word_frame(bytes.fromhex(r['supplied_p1']['word_hex']))
               for r in fixture['cases']}
    targets.update({r['preceding_p4']['slot']: struct.pack('<HH', 0x6b20, 0)
                    for r in fixture['cases']})
    seen = set()
    with path.open('rb') as f:
        slot = 0
        while header := f.read(4):
            require(len(header) == 4, 'short G.192 header')
            sync, size = struct.unpack('<HH', header)
            require((sync, size) in ((0x6b20, 0), (0x6b21, 264)), 'G.192 word type')
            body = f.read(2 * size)
            require(len(body) == 2 * size, 'short G.192 word')
            if slot in targets:
                require(header + body == targets[slot], 'G.192 word disagrees with recorded slot')
                seen.add(slot)
            slot += 1
    require(slot == 88880 and seen == targets.keys(), 'wrong timeline extent')


def build(source, tmp):
    original = source / 'lib_dec/hq_lr_dec.c'
    require(digest(original) == SOURCE_HASH, 'use the November 2021 floating reference source')
    text = original.read_text(encoding='latin1')
    anchor = 'spt_shorten_flag[j] = (short)get_next_indice (st, 1 );'
    require(text.count(anchor) == 1, 'reference anchor mismatch')
    observer = 'fprintf(stderr, "SHORTEN,%d,%d,%d\\n",j,st->next_bit_pos-1,spt_shorten_flag[j]);'
    patched = tmp / original.name
    patched.write_text(text.replace(anchor, anchor + '\n            ' + observer), encoding='latin1')
    libs = sorted([*(source/'lib_com').glob('*.c'), *(source/'lib_dec').glob('*.c')])
    require(len(libs) > 2, 'source root must contain lib_com and lib_dec')
    includes = ['-I' + str(source/name) for name in ('lib_com', 'lib_dec', 'lib_enc')]
    exe = tmp / 'EVS_dec'
    subprocess.run(['gcc', '-O0', '-std=gnu99', '-fno-strict-aliasing', *includes,
                    *(patched if p == original else p for p in libs), '-lm', '-o', exe], check=True)
    return exe


def read_case(case, exe, tmp):
    p1, p4 = case['supplied_p1'], case['preceding_p4']
    require(p1['position'] == 1 and p4['position'] == 4 and p1['slot'] == p4['slot'] + 1,
            'adjacent P4 to P1 required')
    require(p1['counter'] == p4['counter'] and p4['mode'] == 'F8', 'pair counter or mode')
    old = 20 * p4['phase'] + 4 * p4['cycle'] + 3
    new = 20 * p1['phase'] + 4 * p1['cycle']
    require(new == old + 1, 'coordinate adjacency')
    word = bytes.fromhex(p1['word_hex'])
    require(word[0] == 0xf8 and sha256(word).hexdigest() == p1['word_sha256'], 'P1 digest or mode')
    projected = word[:1] + bytes(b for i, b in enumerate(word[1:]) if i % 3)
    require(projected.hex() == p1['raw_direct_projection_hex'], 'P1 direct octets')
    input_path = tmp / 'one.192'
    input_path.write_bytes(word_frame(word))
    run = subprocess.run([exe, '-q', '-no_delay_cmp', '16', input_path, tmp/'one.s16'],
                         capture_output=True, check=True)
    observed = []
    for line in run.stderr.splitlines():
        if line.startswith(b'SHORTEN,'):
            band, address, value = map(int, line.split(b',')[1:])
            require(0 <= address < 264 and value == ((word[address//8] >> (7-address%8)) & 1),
                    'native SPT bit mismatch')
            if value:
                observed.append(dict(relative_high_band=band, physical_bit=address,
                                     direct_payload_lane=(address//8-1)%3 != 0))
    require(observed == case['shortening_flags_one'], 'native SPT-flag mismatch')
    return dict(P1_slot=p1['slot'], preceding_P4_slot=p4['slot'], counter=p1['counter'],
                positive_SPT=observed)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True, type=Path, help='stock TS 26.443 c-code directory')
    parser.add_argument('--packets', type=Path, help='optional original, hash-checked packets.npz (NumPy)')
    parser.add_argument('--g192', type=Path, help='optional original, hash-checked ordinary programme.192')
    args = parser.parse_args()
    path = BASE / 'fixtures.json'
    require(digest(path) == FIXTURE_HASH, 'fixture hash differs')
    fixture = json.loads(path.read_text())
    for group in fixture['clean_counters']:
        check_text(group)
    check_included_data_units(fixture)
    if args.packets:
        check_packet_snapshot(args.packets, fixture)
    if args.g192:
        check_g192(args.g192, fixture)
    with tempfile.TemporaryDirectory() as folder:
        tmp = Path(folder)
        exe = build(args.source.resolve(), tmp)
        results = [read_case(case, exe, tmp) for case in fixture['cases']]
    print(json.dumps(dict(included_received_DUs=9, standalone_P1_words=len(results),
                          positive_direct_SPT=sum(w['direct_payload_lane'] for r in results
                                                  for w in r['positive_SPT']),
                          original_packet_file_checked=bool(args.packets),
                          original_g192_file_checked=bool(args.g192), cases=results), indent=2))


if __name__ == '__main__':
    main()
