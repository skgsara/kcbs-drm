"""Unit tests for scripts/mask_method_acoustic.py that need no decoder binary."""
import unittest

import numpy as np

import mask_method_acoustic as M
from evs_candidates import DIAG_DTYPE, EvalResult


def fake_result(K=4, N=64, seed=0, same=False):
    rng = np.random.default_rng(seed)
    base = (rng.standard_normal((1 if same else K, N, M.FRAME))*800).astype(np.int16)
    pcm = np.repeat(base, K, axis=0) if same else base
    diag = np.zeros((K, N), DIAG_DTYPE)
    diag['nbits'] = 264
    diag['next_bit_pos'] = 264
    diag['core'] = 1
    return EvalResult(pcm, diag, np.zeros(K, np.int32), 1)


class FeatureTest(unittest.TestCase):
    def test_mel_bank_covers_both_bands(self):
        self.assertEqual(M.BANK.shape, (M.NFFT//2 + 1, M.NBANDS))
        self.assertTrue((M.BANK.sum(axis=0) > 0).all())
        self.assertTrue(M.HI.any() and M.LO.any())

    def test_feature_shapes(self):
        res = fake_result()
        raw = M.raw_analysis(res)
        ok = np.ones(64, bool)
        anchor = np.zeros(64, bool)
        anchor[0:60:4] = True
        feats, cls = M.candidate_features(raw, 1, ok, anchor)
        self.assertEqual(feats.shape, (4, M.NF))
        self.assertEqual(len(cls), 15)
        self.assertTrue(np.isfinite(feats).all())

    def test_identical_candidates_give_uniform_prediction(self):
        res = fake_result(same=True)
        raw = M.raw_analysis(res)
        ok = np.ones(64, bool)
        anchor = np.zeros(64, bool)
        anchor[0:60:4] = True
        feats, _ = M.candidate_features(raw, 2, ok, anchor)
        model = dict(weights=dict(default=list(np.linspace(-1, 1, M.NF))))
        lp = M.model_logp(feats, model)
        np.testing.assert_allclose(lp, np.log(1/len(lp)))

    def test_model_logp_normalised(self):
        rng = np.random.default_rng(3)
        feats = rng.standard_normal((256, M.NF))
        model = dict(weights=dict(default=list(rng.standard_normal(M.NF)), ref=list(rng.standard_normal(M.NF))))
        for key in (None, 'ref', 'missing'):
            lp = M.model_logp(feats, model, key)
            self.assertAlmostEqual(float(np.exp(lp).sum()), 1.0, places=9)

    def test_erased_role_frames_contribute_nothing(self):
        res = fake_result()
        raw = M.raw_analysis(res)
        ok = np.ones(64, bool)
        ok[1::4] = False
        feats, cls = M.candidate_features(raw, 1, ok, np.zeros(64, bool))
        self.assertFalse(feats[:, :-1].any())
        self.assertEqual(len(cls), 0)


if __name__ == '__main__':
    unittest.main()
