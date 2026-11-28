"""Synthetic regression tests for the recovery tools; no radio fixtures required."""
import contextlib
import io
import json
from pathlib import Path
import struct
import tempfile
import unittest

import numpy as np

from tail_fill_audit import crc, fill_candidates, read_groups
from exact_frame_key_attack import attack, STARTS, MODES, KEYED
from mode_key_attack import fit, predict


def record(du):
    du = bytearray(du)
    du[714:716] = crc(du[:714]).to_bytes(2, 'big')
    result = b''
    for q, header in enumerate((0x80, 0x01, 0x02, 0x43)):
        packet = bytes([header]) + du[q*179:(q+1)*179]
        result += packet + crc(packet).to_bytes(2, 'big')
    return struct.pack('<I', len(result)) + result


def group(counter, tweak=0):
    result = b''
    for p in range(3):
        du = bytearray(716)
        du[0] = 64
        du[1] = p << 4
        du[2] = tweak
        if p == 0:
            du[664:668] = counter.to_bytes(4, 'big')
        result += record(du)
    return result


class RecoveryTests(unittest.TestCase):
    def test_crc_known_vector(self):
        self.assertEqual(crc(b'123456789'), 0xd64e)

    def test_unaligned_fills(self):
        segment = bytearray(b'\x05\x0c' + ('가나다라'*12)[:46].encode('utf-16le'))
        segment += crc(segment).to_bytes(2, 'big') + b'\xbb'*16
        self.assertEqual(len(segment), 112)
        key = np.arange(16, dtype=np.uint8) * 13
        for off in range(0, 33, 2):
            plain = np.array([segment[(j-off+96) % 112] for j in range(48)], np.uint8)
            cipher = plain ^ np.tile(key, 3)
            matches = [c for c in fill_candidates(cipher) if c['offset'] == off]
            self.assertEqual(len(matches), 1, off)
            np.testing.assert_array_equal(matches[0]['key'], key)

    def test_loop_dedup_and_conflict(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / 'dump.bin'
            p.write_bytes(group(10) + group(11) + group(10) + group(11, 1))
            c, du, origins, conflicts, stats = read_groups([p])
            self.assertEqual(c.tolist(), [10])
            self.assertEqual(conflicts, {11})
            self.assertEqual(len(origins[10]), 2)
            self.assertEqual(stats[0]['crc_good'], 12)

    def test_corrupt_and_malformed_records(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / 'dump.bin'
            b = bytearray(group(10)); b[30] ^= 1
            p.write_bytes(b)
            c, *_ = read_groups([p])
            self.assertEqual(len(c), 0)
            p.write_bytes(struct.pack('<I', 0xffffffff))
            with self.assertRaises(ValueError):
                read_groups([p])

    def test_exact_reuse_positive_control(self):
        rng = np.random.default_rng(7)
        key = rng.integers(0, 256, (8, 44), dtype=np.uint8)
        templates = rng.integers(0, 256, (15, 32), dtype=np.uint8)
        du = np.zeros((8, 3, 716), dtype=np.uint8)
        for g in range(8):
            for f in range(60):
                p, slot = divmod(f, 20)
                role = f % 4
                packet = templates[f//4].copy()
                packet[KEYED] ^= key[g, 11*role:11*role+11]
                du[g, p, STARTS[slot]:STARTS[slot]+32] = packet
                du[g, p, MODES[slot]] = 81
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / 'groups.npz'; out = Path(td) / 'out'
            np.savez(src, du=du, idle_text_crc_ok=np.ones(8, bool), idle_ks=key[:, :16],
                     counters=np.arange(1, 9, dtype=np.uint32))
            with contextlib.redirect_stdout(io.StringIO()):
                attack(src, out)
            report = json.loads((out/'summary.json').read_text())
            self.assertEqual(report['heldout_matches'], 60)
            self.assertEqual(report['heldout_exact'], 60)
            proposals = json.loads((out/'proposals.json').read_text())
            self.assertEqual(len(proposals), 24)
            for item in proposals:
                c, r = item['counter']-1, item['role']
                self.assertEqual(item['candidate_key_hex'], key[c, 11*r:11*r+11].tobytes().hex())

    def test_mode_likelihood_positive_control(self):
        modes = np.full((20, 15), 81, np.uint8)
        plain = np.full((20, 15, 11), 37, np.uint8)
        table = fit(modes, plain)
        keys = np.arange(11, dtype=np.uint8)[None, :].repeat(4, axis=0)
        cipher = plain[:4] ^ keys[:, None, :]
        prediction, _ = predict(table, modes[:4], cipher)
        np.testing.assert_array_equal(prediction, keys)


if __name__ == '__main__':
    unittest.main()
