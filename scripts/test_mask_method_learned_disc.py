"""Fast unit tests for scripts/mask_method_learned_disc.py (no decoder runs, no benchmark data)."""
import unittest

import numpy as np

import mask_method_learned_disc as M


def bits(x, n):
    return [(x >> (n - 1 - i)) & 1 for i in range(n)]


class ContextIndexTest(unittest.TestCase):
    def test_left_and_right_contexts_match_the_bit_stream(self):
        rng = np.random.default_rng(1)
        for _ in range(200):
            prev, c, nxt = (int(v) for v in rng.integers(0, 256, 3))
            stream = bits(prev, 8) + bits(c, 8) + bits(nxt, 8)
            for k in range(8):
                pos = 8 + k
                for W in (2, 4, 6, 8):
                    left = stream[pos - W:pos]
                    self.assertEqual(M._ctx_index('L', W, prev, c, nxt, k), int(''.join(map(str, left)), 2))
                    right = stream[pos + 1:pos + 1 + W]
                    self.assertEqual(M._ctx_index('R', W, prev, c, nxt, k), int(''.join(map(str, right)), 2))


class FoldTest(unittest.TestCase):
    def test_units(self):
        self.assertEqual(M.cv_unit('nov25-1246-6140-merged'), 'nov25-1246-6140-merged')
        self.assertEqual(M.cv_unit('syn-dev:librosa-fishin'), 'syn-dev:fold1')
        self.assertEqual(M.cv_unit('syn-dev:librivox-en-spc160-duringmusic'),
                         M.cv_unit('syn-dev:librivox-en-spc160-anticipation'))

    def test_family_of_modes(self):
        np.testing.assert_array_equal(M.family_of_modes([0x50, 0xfc, 0xf8, 0x76]), [0, 1, 2, 0])


class SelectTest(unittest.TestCase):
    def test_subsample_is_seeded_and_sorted(self):
        inputs = dict(target=np.zeros((50, 44), bool), labelled=np.zeros(50, bool))
        inputs['target'][::2, 11] = True
        a = M.select_groups(inputs, 10, seed=3)
        b = M.select_groups(inputs, 10, seed=3)
        np.testing.assert_array_equal(a, b)
        self.assertTrue(np.all(np.diff(a) > 0))
        self.assertTrue(np.all(a % 2 == 0))
        self.assertEqual(len(M.select_groups(inputs)), 25)


class RankerTest(unittest.TestCase):
    def _store(self, n=6, seed=0):
        rng = np.random.default_rng(seed)
        Xc = rng.standard_normal((n, 256, len(M.PRIOR_NAMES))).astype(np.float32)
        ctx = rng.random((n, len(M.MODEL_CONTEXT_NAMES))).astype(np.float32)
        return M.Store('ctx', Xc, ctx), rng.integers(0, 256, n)

    def test_gradient_matches_finite_differences(self):
        store, y = self._store()
        r = M.Ranker(store.names, len(M.MODEL_CONTEXT_NAMES), hidden=4, seed=1)
        r.set_stats(store, np.arange(len(store)))
        for k in r.p:
            r.p[k] = (np.random.default_rng(2).standard_normal(r.p[k].shape)*0.1).astype(np.float32)
        r.p = {k: v.astype(np.float64) for k, v in r.p.items()}
        idx = np.arange(len(store))
        X, ctx, w = store.get(idx).astype(np.float64), store.ctx[idx].astype(np.float64), np.ones(len(idx))
        loss, g = r.loss_grad(X, ctx, y, w, 0.0)
        for key, i in (('a', 3), ('W1', (2, 1)), ('w2', 0), ('b1', 2)):
            old = r.p[key][i]
            r.p[key][i] = old + 1e-5
            up = r.loss_grad(X, ctx, y, w, 0.0)[0]
            r.p[key][i] = old - 1e-5
            down = r.loss_grad(X, ctx, y, w, 0.0)[0]
            r.p[key][i] = old
            self.assertAlmostEqual(g[key][i], (up - down)/2e-5, places=4)

    def test_jgroup_gradient_matches_finite_differences(self):
        rng = np.random.default_rng(4)
        n = 5
        Xc = rng.standard_normal((n, 256, len(M.PRIOR_NAMES))).astype(np.float32)
        Xd = rng.standard_normal((n, 256, len(M.FEATURE_NAMES))).astype(np.float32)
        ctx = np.zeros((n, len(M.MODEL_CONTEXT_NAMES)), np.float32)
        ctx[np.arange(n), M.ROLES + np.array([0, 1, 3, 0, 7])] = 1
        store = M.Store('full', Xc, ctx, Xd, np.arange(n))
        y = rng.integers(0, 256, n)
        for mode in ('jgroup', 'jgroup_linear'):
            r = M.Ranker(store.names, len(M.MODEL_CONTEXT_NAMES), hidden=3, seed=1, dec_mode=mode)
            r.set_stats(store, np.arange(n))
            r.p = {k: np.random.default_rng(5).standard_normal(v.shape)*0.05 for k, v in r.p.items()}
            X, c, w = store.get(np.arange(n)).astype(np.float64), store.ctx.astype(np.float64), np.ones(n)
            _, g = r.loss_grad(X, c, y, w, 0.0)
            for key, i in (('a', len(r.p['a']) - 1), ('a', 5), ('W1', (4, 2)), ('w2', 1)):
                old = r.p[key][i]
                r.p[key][i] = old + 1e-5
                up = r.loss_grad(X, c, y, w, 0.0)[0]
                r.p[key][i] = old - 1e-5
                down = r.loss_grad(X, c, y, w, 0.0)[0]
                r.p[key][i] = old
                self.assertAlmostEqual(g[key][i], (up - down)/2e-5, places=4)
            # decoder evidence of a j = 3..10 item never reaches the j = 0 weights
            lin, _ = M.design(X, r.stats, r.names, c, mode, r.dec_cols)
            names = M.design_names(r.names, mode, r.dec_cols)
            j0 = [i for i, nm in enumerate(names) if nm.endswith('@j0-0')]
            self.assertTrue(np.all(lin[2][:, j0] == 0))
            self.assertEqual(lin.shape[2], len(names))

    def test_fast_path_matches_full_computation(self):
        rng = np.random.default_rng(7)
        n = 6
        Xc = rng.standard_normal((n, 256, len(M.PRIOR_NAMES))).astype(np.float32)
        Xd = rng.standard_normal((2, 256, len(M.FEATURE_NAMES))).astype(np.float32)
        ctx = rng.random((n, len(M.MODEL_CONTEXT_NAMES))).astype(np.float32)
        store = M.Store('full', Xc, ctx, Xd, np.array([-1, 0, -1, -1, 1, -1]))
        y = rng.integers(0, 256, n)
        r = M.Ranker(store.names, len(M.MODEL_CONTEXT_NAMES), hidden=4, seed=2, dec_mode='jgroup_linear')
        r.set_stats(store, np.arange(n))
        r.p = {k: (np.random.default_rng(3).standard_normal(v.shape)*0.1).astype(np.float32) for k, v in r.p.items()}
        self.assertTrue(r.fast_path(store))
        fast = r.raw_scores(store, np.arange(n))
        slow = np.concatenate([r._forward(store.get([i]), store.ctx[[i]])[0] for i in range(n)])
        np.testing.assert_allclose(fast, slow, rtol=1e-5, atol=1e-4)
        nodec = np.array([0, 2, 3])
        _, g_fast = r.batch_grad(store, nodec, y[nodec], np.ones(3), 1e-3)
        _, g_slow = r.loss_grad(store.get(nodec), store.ctx[nodec], y[nodec], np.ones(3), 1e-3)
        for k in g_fast:
            np.testing.assert_allclose(g_fast[k], g_slow[k], rtol=1e-4, atol=1e-6)

    def test_logp_is_normalised_and_roundtrips(self):
        store, y = self._store()
        r = M.Ranker(store.names, len(M.MODEL_CONTEXT_NAMES), hidden=3, seed=0)
        r.fit(store, np.arange(len(store)), y, epochs=2)
        lp = r.logp(store, np.arange(len(store)))
        np.testing.assert_allclose(np.exp(lp).sum(axis=1), 1.0, rtol=1e-9)
        back = M.Ranker.from_arrays(r.to_arrays('m'), 'm')
        np.testing.assert_allclose(back.logp(store, np.arange(len(store))), lp, rtol=1e-6, atol=1e-6)

    def test_full_store_zero_fills_missing_decoder_features(self):
        rng = np.random.default_rng(0)
        Xc = rng.standard_normal((3, 256, len(M.PRIOR_NAMES))).astype(np.float32)
        Xd = rng.standard_normal((1, 256, len(M.FEATURE_NAMES))).astype(np.float32)
        ctx = np.zeros((3, len(M.MODEL_CONTEXT_NAMES)), np.float32)
        store = M.Store('full', Xc, ctx, Xd, np.array([-1, 0, -1]))
        X = store.get(np.arange(3))
        self.assertEqual(X.shape[2], len(M.variant_names('full')))
        nd = len(M.DEC_ONLY)
        self.assertTrue(np.all(X[0, :, :nd] == 0))
        np.testing.assert_array_equal(X[1, :, :nd], Xd[0][:, [M.FEATURE_NAMES.index(n) for n in M.DEC_ONLY]])
        np.testing.assert_array_equal(X[2, :, nd:], Xc[2])
        np.testing.assert_array_equal(store.ctx[:, M.MODEL_CONTEXT_NAMES.index('has_dec')], [0, 1, 0])


if __name__ == '__main__':
    unittest.main()
