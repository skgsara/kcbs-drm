"""Unit tests for scripts/mask_method_params.py (no decoder run needed except where noted)."""
from pathlib import Path
import sys
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mask_method_params as M  # noqa: E402


def record(entries, vals=None, trunc=0, nbp=264):
    """One parameter record (960 int16) as the instrumented decoder writes it."""
    b = np.zeros(M.REC_BYTES, np.uint8)
    head = np.array([len(entries), trunc, nbp, 264], '<u2')
    b[:8] = head.view(np.uint8)
    e = np.zeros(len(entries), np.dtype([('site', '<u4'), ('pos', '<u2'), ('value', '<u2')]))
    for i, (addr, kind, nbits, pos, value) in enumerate(entries):
        e[i] = (addr | (nbits << 24) | (kind << 29), pos, value & 0xFFFF)
    b[8:8 + 8*len(entries)] = e.view(np.uint8)
    if vals is not None:
        b[M.REC_BYTES - 4*M.N_VALS:] = np.asarray(vals, '<f4').view(np.uint8)
    return b.view('<i2')


class ParseLogs(unittest.TestCase):
    def test_fields_and_occurrence(self):
        r0 = record([(0x1000, 0, 5, 0, 31), (0x2000, 0, 3, 8, 5), (0x2000, 0, 3, 11, 2),
                     (0x3000, 5, 0, 4, -7)], vals=np.arange(64))
        r1 = record([(0x2000, 0, 3, 8, 1)])
        L = M.parse_logs(np.stack([r0, r1]))
        self.assertEqual(L['row'].tolist(), [0, 0, 0, 0, 1])
        self.assertEqual(L['nbits'].tolist(), [5, 3, 3, 0, 3])
        self.assertEqual(L['kind'].tolist(), [0, 0, 0, 5, 0])
        self.assertEqual(L['occ'].tolist(), [0, 0, 1, 0, 0])
        self.assertEqual(L['value'].tolist(), [31, 5, 2, -7, 1])
        self.assertEqual(L['vals'][0, 10], 10.0)

    def test_keyed_range(self):
        self.assertEqual(M.keyed_range(0), (8, 16))
        self.assertEqual(M.keyed_range(10), (248, 256))


class FieldModelTest(unittest.TestCase):
    def test_marginal_normalised(self):
        rng = np.random.default_rng(0)
        site = np.full(5000, 0x10 | (4 << 24), np.uint32)
        value = rng.choice(16, 5000, p=np.r_[0.5, np.full(15, 0.5/15)])
        fm = M.FieldModel().fit_marginal(site, value)
        lp = fm.marginal_lp(np.full(16, site[0]), np.arange(16))
        self.assertAlmostEqual(float(np.exp(lp).sum()), 1.0, places=6)
        self.assertGreater(lp[0], lp[1])

    def test_wide_field_normalised(self):
        rng = np.random.default_rng(1)
        site = np.full(4000, 0x20 | (12 << 24), np.uint32)
        fm = M.FieldModel().fit_marginal(site, rng.integers(0, 4096, 4000))
        lp = fm.marginal_lp(np.full(4096, site[0]), np.arange(4096))
        self.assertAlmostEqual(float(np.exp(lp).sum()), 1.0, places=6)

    def test_neighbour_prefers_repeat(self):
        rng = np.random.default_rng(2)
        site = np.full(3000, 0x30 | (3 << 24), np.uint32)
        ref = rng.integers(0, 8, 3000)
        cur = np.where(rng.random(3000) < 0.8, ref, rng.integers(0, 8, 3000))
        fm = M.FieldModel().fit_marginal(site, cur)
        fm.fit_neighbour(1, site, cur, ref)
        g = fm.neighbour_llr(1, site[:2], np.array([3, 4]), np.array([3, 3]))
        self.assertGreater(g[0], 0)
        self.assertLess(g[1], 0)


class Patches(unittest.TestCase):
    @unittest.skipUnless((M.REF/'lib_com/bitstream.c').exists(), 'EVS reference not present')
    def test_anchors_unique(self):
        bs = (M.REF/'lib_com/bitstream.c').read_text(encoding='latin1')
        M._patch(bs, M.BITSTREAM_RENAMES, 'bitstream.c')
        hq = (M.REF/'lib_dec/hq_lr_dec.c').read_text(encoding='latin1')
        M._patch(hq, M.HQ_LR_PATCHES, 'hq_lr_dec.c')
        M._patch(M.HARNESS.read_text(encoding='utf-8'), M.HARNESS_PATCHES, 'harness')

    def test_target_order(self):
        t = np.zeros(44, bool)
        t[[30, 16, 17, 43]] = True
        self.assertEqual(M.target_order(t), [(1, 5), (1, 6), (2, 8), (3, 10)])


if __name__ == '__main__':
    unittest.main()
