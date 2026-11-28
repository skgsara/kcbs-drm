"""Check cross-receiver packet salvage against both physical integrity layers."""
from binascii import crc_hqx
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import struct
import tempfile
import unittest

import numpy as np

from salvage_msc_packets import salvage


def checksum(data):
    return (crc_hqx(data, 0xffff) ^ 0xffff).to_bytes(2, 'big')


def row(phase, counter=100, *, variant=0, wrong_header=None, bad_packet=None, bad_du=False):
    unit = bytearray(716)
    unit[1] = phase << 4
    unit[200] = variant
    if phase == 0:
        unit[664:668] = counter.to_bytes(4, 'big')
    unit[-2:] = checksum(unit[:-2])
    if bad_du:
        unit[-1] ^= 1
    wire = bytearray()
    for q, header in enumerate((0x80, 0x01, 0x02, 0x43)):
        if q == wrong_header:
            header ^= 0x10
        packet = bytes([header]) + unit[q*179:(q+1)*179]
        wire += packet + checksum(packet)
        if q == bad_packet:
            wire[-1] ^= 1
    return struct.pack('<I', len(wire)) + wire


def run_salvage(*sources):
    with tempfile.TemporaryDirectory() as td, redirect_stdout(io.StringIO()):
        root = Path(td)
        inputs = []
        for i, data in enumerate(sources):
            path = root / f'{i}.msc'
            path.write_bytes(data)
            inputs.append(path)
        out = root / 'salvaged'
        salvage(inputs, out, transport_only=True)
        with np.load(out / 'data_units.npz') as archive:
            units = {(int(c), int(p)): u.tobytes() for c, p, u in
                     zip(archive['counters'], archive['phases'], archive['du'], strict=True)}
        return units, json.loads((out / 'report.json').read_text()), json.loads((out / 'provenance.json').read_text())


class PacketIntegrity(unittest.TestCase):
    def test_bad_wire_header_or_invalid_complete_du_cannot_poison_a_good_source(self):
        good = row(0) + row(1) + row(2)
        expected, _, _ = run_salvage(good)
        self.assertEqual(set(expected), {(100, 0), (100, 1), (100, 2)})
        bad_rows = [(row(0, wrong_header=q, variant=5), 'unexpected_packet_header') for q in range(4)]
        bad_rows.append((row(0, bad_du=True, variant=5), 'complete_du_crc'))
        for i, (bad, reason) in enumerate(bad_rows):
            with self.subTest(case=i, reason=reason):
                units, report, provenance = run_salvage(bad, good)
                self.assertEqual(units, expected)
                self.assertEqual(report['rejected_record_observations'], {reason: 1})
                self.assertEqual(report['conflicting_data_units'], [])
                self.assertTrue(all(Path(path).name == '1.msc' for origins in provenance.values()
                                    for path, _index in origins))

    def test_rejected_records_break_brackets_and_preserve_source_indices(self):
        for barrier in (row(1, wrong_header=1), row(1, bad_du=True)):
            # A bad phase-one row cannot anchor any packet of the partial phase two.
            _, _, provenance = run_salvage(row(0) + barrier + row(2, bad_packet=1) + row(0, 101))
            self.assertFalse(any(key.startswith('100,2,') for key in provenance))
            # Removing this row would join the adjacent 0/1/2 into a false complete group.
            units, _, provenance = run_salvage(row(0) + barrier + row(1) + row(2) + row(0, 101))
            self.assertEqual(set(units), {(100, 0), (101, 0)})
            self.assertEqual(provenance['101,0,0'][0][1], 4)

    def test_unchecked_header_does_not_disqualify_complementary_reception(self):
        expected, _, _ = run_salvage(row(0))
        a = row(0, bad_packet=1, wrong_header=1)
        b = row(0, bad_packet=2)
        units, report, provenance = run_salvage(a, b)
        self.assertEqual(units, expected)
        self.assertNotIn('rejected_record_observations', report)
        self.assertEqual([Path(p).name for p, _ in provenance['100,0,1']], ['1.msc'])
        self.assertEqual([Path(p).name for p, _ in provenance['100,0,2']], ['0.msc'])

    def test_valid_disagreement_still_quarantines_the_du(self):
        units, report, _ = run_salvage(row(0) + row(1) + row(2), row(0, variant=5))
        self.assertEqual(set(units), {(100, 1), (100, 2)})
        self.assertEqual(report['conflicting_data_units'], [[100, 0]])
        self.assertNotIn('rejected_record_observations', report)


if __name__ == '__main__':
    unittest.main()
