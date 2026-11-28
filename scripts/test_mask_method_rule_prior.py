"""Tests for scripts/mask_method_rule_prior.py (run: python3 scripts/test_mask_method_rule_prior.py)."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mask_method_rule_prior as M  # noqa: E402


def toy_inputs(n_groups=6, seed=0):
    rng = np.random.default_rng(seed)
    frames = rng.integers(0, 256, (n_groups, 60, 33), dtype=np.uint8)
    # A TCX20 run (mode FE) so the core-history rule fires on every word after the first.
    frames[:, :, 0] = 0xFE
    plain_b0 = frames[:, :, 1].copy()
    plain_b0 |= 0x80            # stock TCX20 after an MDCT word: last-core bit (b8) = 1
    mask = rng.integers(0, 256, (n_groups, 44)).astype(np.int16)
    mask[:, 43] = 0
    frames[:, :, 1] = plain_b0
    for r in range(4):
        for j in range(11):
            frames[:, r::4, 1 + 3*j] ^= mask[:, 11*r + j][:, None].astype(np.uint8)
    known = np.full((n_groups, 44), -1, np.int16)
    known[:, :11] = mask[:, :11]
    known[:, 43] = 0
    target = np.zeros((n_groups, 44), bool)
    target[:, 11:16] = True
    return dict(split=np.array('toy'), task=np.array('T1'), group_id=np.array([f'g{i}' for i in range(n_groups)]),
                capture=np.array(['toy'] * n_groups), counters=np.arange(n_groups, dtype=np.uint32) + 100,
                run_id=np.zeros(n_groups, np.int32), frames=frames, present=np.ones((n_groups, 60), bool),
                known=known, target=target, labelled=np.ones(n_groups, bool)), mask


class BitChainTest(unittest.TestCase):
    def test_leaf_distribution_normalised(self):
        rng = np.random.default_rng(1)
        p1 = rng.uniform(0.05, 0.95, (4, 256))
        lp = M.leaf_logp(p1)
        np.testing.assert_allclose(np.exp(lp).sum(axis=1), 1.0, rtol=1e-9)

    def test_level_counts_match_values(self):
        vals = np.array([0x80, 0x80, 0x00, 0xff])
        keys = np.zeros(4, np.int64)
        lev = M.Level(keys, vals, np.ones(4), 0)
        c = lev.counts(np.zeros(1, np.int64))[0]
        # root node (index 1): three words with MSB 1, one with MSB 0
        self.assertEqual(tuple(c[1]), (1.0, 3.0))


class RuleTest(unittest.TestCase):
    def test_tcx_rule_constrains_role_mask_msb(self):
        inp, mask = toy_inputs()
        terms = M.role_rule_terms(inp['frames'][0], inp['present'][0], inp['counters'][0])
        self.assertIn(1, terms)
        allowed = terms[1]['logp'] == 0
        self.assertTrue(allowed[mask[0, 11]])
        # every allowed mask value shares the true mask MSB
        self.assertTrue(np.all((np.flatnonzero(allowed) >> 7) == (mask[0, 11] >> 7)))

    def test_rules_skip_missing_words(self):
        inp, _ = toy_inputs()
        present = np.zeros(60, bool)
        self.assertEqual(M.role_rule_terms(inp['frames'][0], present, 100), {})


class PredictTest(unittest.TestCase):
    def test_rules_variant_shapes_and_truth(self):
        inp, mask = toy_inputs()
        pred, info = M.predict(inp, 'rules', corpus_paths=())
        self.assertEqual(pred['logp'].shape, (6*5, 256))
        j0 = pred['j'] == 0
        g = np.array([int(str(x)[1:]) for x in pred['group']])
        truth = mask[g, 11]
        self.assertTrue(np.all(pred['logp'][j0, :][np.arange(j0.sum()), truth[j0]] == 0))
        self.assertEqual(info['rules']['contradiction'], 0)

    def test_full_variant_runs_without_corpus(self):
        inp, _ = toy_inputs()
        pred, _ = M.predict(inp, 'full', corpus_paths=())
        self.assertTrue(np.isfinite(pred['logp']).all())

    def test_cli_refuses_truth(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = subprocess.run([sys.executable, str(Path(M.__file__)), '--inputs', f'{tmp}/x.truth.npz',
                                '--out', f'{tmp}/p.npz'], capture_output=True, text=True)
            self.assertNotEqual(r.returncode, 0)


if __name__ == '__main__':
    unittest.main()
