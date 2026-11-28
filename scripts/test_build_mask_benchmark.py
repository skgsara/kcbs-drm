"""Unit tests for the benchmark builder's layout helpers and carousel copy check."""
import unittest

import numpy as np

import build_mask_benchmark as bm
from render_continuous import group_frames


class LayoutTest(unittest.TestCase):
    def test_slot_order_and_mask_match_render_continuous(self):
        rng = np.random.default_rng(5)
        du = rng.integers(0, 256, (3, 716), dtype=np.uint8)
        ok = np.ones(4, bool)
        frames = np.concatenate([bm.unit_frames(du[p], ok)[0] for p in range(3)])
        key = rng.integers(0, 256, 16, dtype=np.uint8)
        modes, flat = group_frames(du, key)
        mask = np.full(bm.MASK_BYTES, -1, np.int16)
        mask[:16] = key                       # role 0 = ks[0..10], role-1 j=0..4 = ks[11..15]
        plain = frames ^ bm.expand_mask(mask)
        np.testing.assert_array_equal(plain[:, 0], modes)
        np.testing.assert_array_equal(plain[:, 1:], flat)

    def test_presence_follows_packet_crc(self):
        du = np.zeros(716, np.uint8)
        ok = np.array([True, False, True, True])          # bytes 179..357 lost
        _, present = bm.unit_frames(du, ok)
        for slot, (mode, start) in enumerate(zip(bm.MODE_POSITIONS, bm.PACKET_STARTS)):
            touched = {mode // 179, *range(start // 179, (start + 31) // 179 + 1)}
            self.assertEqual(present[slot], 1 not in touched)


def carousel(n_groups=40, period=7, seed=0):
    """Phase-tagged data units whose text tails repeat every `period` blocks."""
    rng = np.random.default_rng(seed)
    text = rng.integers(0, 256, (period, 16), dtype=np.uint8)
    text[:, 0] &= 0x7f
    keys = rng.integers(0, 256, (n_groups, 16), dtype=np.uint8)
    counters = np.arange(1000, 1000 + n_groups)
    du_counters, phases, du = [], [], []
    for g, c in enumerate(counters):
        for p in range(3):
            unit = np.zeros(716, np.uint8)
            unit[698:714] = text[(3*g + p) % period] ^ keys[g]
            du_counters.append(c)
            phases.append(p)
            du.append(unit)
    return counters, keys, np.array(du_counters), np.array(phases), np.array(du), text


class CopyCheckTest(unittest.TestCase):
    def run_check(self, counters, keys, supported, du_counters, phases, du, period=7):
        return bm.carousel_copy_check(counters, keys, supported, du_counters, phases, du, period)

    def test_correct_keys_are_confirmed(self):
        counters, keys, dc, ph, du, _ = carousel()
        r = self.run_check(counters, keys, np.ones(keys.shape, bool), dc, ph, du)
        self.assertFalse(r['contradicted'].any())
        self.assertTrue(r['confirmed16'].all())

    def test_one_wrong_key_byte_is_caught_without_blaming_neighbours(self):
        counters, keys, dc, ph, du, _ = carousel()
        bad = keys.copy()
        bad[20, 13] ^= 0x5a                   # garbled role-1 byte of one group
        r = self.run_check(counters, bad, np.ones(keys.shape, bool), dc, ph, du)
        np.testing.assert_array_equal(np.flatnonzero(r['contradicted']), [20])
        self.assertEqual(r['agree'][20, 13], 0)
        self.assertGreater(r['disagree'][20, 13], 2)

    def test_header_toggle_bit_is_not_a_contradiction(self):
        counters, keys, dc, ph, du, _ = carousel()
        du = du.copy()
        du[3*10:3*10 + 3, 698] ^= bm.TOGGLE_BIT     # item toggle flips in one pass
        r = self.run_check(counters, keys, np.ones(keys.shape, bool), dc, ph, du)
        self.assertFalse(r['contradicted'].any())

    def test_unsupported_rows_are_neither_checked_nor_used(self):
        counters, keys, dc, ph, du, _ = carousel()
        bad = keys.copy()
        bad[5, 0] ^= 1
        supported = np.ones(keys.shape, bool)
        supported[5, 3] = False
        r = self.run_check(counters, bad, supported, dc, ph, du)
        self.assertFalse(r['contradicted'].any())
        self.assertFalse(r['compared'][5])


if __name__ == '__main__':
    unittest.main()
