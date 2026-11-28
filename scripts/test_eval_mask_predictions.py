"""Unit tests for the blind mask-recovery evaluator on tiny synthetic inputs."""
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

import eval_mask_predictions as ev


def items_from(values, groups=None, indices=None, captures=None, strict=None):
    values = np.asarray(values, np.int64)
    n = len(values)
    groups = np.arange(n) if groups is None else np.asarray(groups)
    indices = np.full(n, 11) if indices is None else np.asarray(indices)
    return dict(group=groups, index=indices, role=indices // 11, j=indices % 11, value=values,
                group_id=np.array([f'g{g}' for g in groups]),
                capture=np.array(['cap'] * n) if captures is None else np.asarray(captures),
                strict=np.zeros(n, bool) if strict is None else np.asarray(strict, bool))


def one_hot(values, weight=1.0):
    P = np.full((len(values), 256), (1 - weight)/255)
    P[np.arange(len(values)), values] = weight
    return P


class DistributionTest(unittest.TestCase):
    def test_logp_softmax_accepts_minus_infinity(self):
        logp = np.full(256, -np.inf)
        logp[[3, 4]] = [0.0, np.log(3)]
        p = ev.normalise_logp(logp[None])[0]
        self.assertAlmostEqual(p[3], 0.25)
        self.assertAlmostEqual(p[4], 0.75)
        with self.assertRaises(ValueError):
            ev.normalise_logp(np.full((1, 256), np.nan))

    def test_candidates_with_confidence_keep_rank_order(self):
        p = ev.candidates_to_probs([7, 9, 200], confidence=0.6)
        self.assertAlmostEqual(p.sum(), 1.0)
        self.assertAlmostEqual(p[7], 0.6)
        self.assertGreater(p[9], p[200])
        self.assertGreater(p[200], p[0])
        self.assertAlmostEqual(p[0], p[255])

    def test_candidate_probs_leave_uniform_remainder(self):
        p = ev.candidates_to_probs([1, 2], candidate_probs=[0.5, 0.25])
        self.assertAlmostEqual(p[1], 0.5)
        self.assertAlmostEqual(p[2], 0.25)
        self.assertAlmostEqual(p[0], 0.25/254)
        with self.assertRaises(ValueError):
            ev.candidates_to_probs([1, 1], confidence=0.5)
        with self.assertRaises(ValueError):
            ev.candidates_to_probs([1, 2])

    def test_non_finite_probabilities_rejected(self):
        probs = np.ones((1, 256))
        probs[0, 5] = np.inf
        with self.assertRaises(ValueError):
            ev.normalise_probs(probs)
        with self.assertRaises(ValueError):
            ev.candidates_to_probs([1, 2], candidate_probs=[np.inf, 0.1])

    def test_low_confidence_list_is_scored_as_given(self):
        p = ev.candidates_to_probs([7, 9], confidence=0.003)
        self.assertAlmostEqual(p[7], 0.003)
        self.assertGreater(p[9], p[7])          # documented: c below the rank-2 share


class ByteMetricTest(unittest.TestCase):
    def test_uniform_is_tie_aware(self):
        s = ev.byte_scores(ev.uniform_probs(3), np.array([0, 100, 255]))
        np.testing.assert_allclose(s['topk'][1], 1/256)
        np.testing.assert_allclose(s['topk'][16], 16/256)
        np.testing.assert_allclose(s['rank'], 128.5)
        np.testing.assert_allclose(s['log2_loss'], 8.0)

    def test_ranks_of_truth(self):
        P = np.full((2, 256), 0.001)
        P[0, [5, 6, 7]] = [0.5, 0.3, 0.2]   # truth 7 is third
        P[1, [5, 6]] = [0.4, 0.4]           # truth 6 tied first with 5
        P /= P.sum(axis=1, keepdims=True)
        s = ev.byte_scores(P, np.array([7, 6]))
        np.testing.assert_allclose(s['rank'], [3.0, 1.5])
        np.testing.assert_allclose(s['topk'][1], [0.0, 0.5])
        np.testing.assert_allclose(s['topk'][2], [0.0, 1.0])
        np.testing.assert_allclose(s['topk'][4], [1.0, 1.0])

    def test_coverage_curve(self):
        rows = ev.coverage_curve(np.array([0.99, 0.6, 0.2]), np.array([1.0, 0.0, 1.0]), (0.0, 0.5, 0.95))
        self.assertEqual([r['called'] for r in rows], [3, 2, 1])
        self.assertAlmostEqual(rows[1]['accuracy'], 0.5)
        self.assertEqual(rows[2]['accuracy'], 1.0)


class PrecisionTest(unittest.TestCase):
    def test_largest_set_reaching_target(self):
        conf = np.array([0.99, 0.95, 0.9, 0.8])
        correct = np.array([1.0, 1.0, 0.0, 1.0])
        self.assertEqual(ev.at_precision(conf, correct, 0.98)['called'], 2)
        row = ev.at_precision(conf, correct, 0.7)
        self.assertEqual(row['called'], 4)
        self.assertAlmostEqual(row['precision'], 0.75)
        self.assertEqual(row['threshold'], 0.8)

    def test_never_splits_a_confidence_tie(self):
        conf = np.array([0.9, 0.9, 0.9, 0.5])
        correct = np.array([1.0, 1.0, 0.0, 0.0])
        self.assertEqual(ev.at_precision(conf, correct, 0.98)['called'], 0)
        self.assertEqual(ev.at_precision(conf, correct, 0.6)['called'], 3)

    def test_threshold_application(self):
        row = ev.at_threshold(np.array([0.99, 0.97, 0.5]), np.array([1.0, 0.0, 1.0]), 0.97)
        self.assertEqual(row['called'], 2)
        self.assertAlmostEqual(row['precision'], 0.5)


class BitAndRoleTest(unittest.TestCase):
    def test_bit_marginals_of_a_certain_byte(self):
        p1, conf, correct = ev.bit_scores(one_hot(np.array([0b10100001])), np.array([0b10100001]))
        np.testing.assert_allclose(p1[0], [1, 0, 1, 0, 0, 0, 0, 1])
        np.testing.assert_allclose(conf, 1.0)
        np.testing.assert_allclose(correct, 1.0)

    def test_half_known_byte_gives_four_certain_bits(self):
        P = np.zeros((1, 256))
        P[0, 0xA0:0xB0] = 1/16                  # high nibble 1010 certain, low nibble unknown
        p1, conf, correct = ev.bit_scores(P, np.array([0xA7]))
        np.testing.assert_allclose(conf[0, :4], 1.0)
        np.testing.assert_allclose(conf[0, 4:], 0.5)
        np.testing.assert_allclose(correct[0], [1, 1, 1, 1, .5, .5, .5, .5])

    def test_role_consistency_counts_whole_cells(self):
        items = items_from([1, 2, 3, 4], groups=[0, 0, 1, 1], indices=[11, 12, 11, 12])
        top1 = np.array([1.0, 1.0, 1.0, 0.0])
        conf = np.array([0.999, 0.999, 0.999, 0.999])
        row = ev.role_consistency(items, top1, conf)
        self.assertEqual(row['cells'], 2)
        self.assertEqual(row['all_top1_correct'], 1.0)
        self.assertEqual(row['all_called_at_confidence']['0.995'], dict(called=2, all_correct=1.0))


class SummaryTest(unittest.TestCase):
    def test_perfect_and_uniform(self):
        values = np.array([10, 20, 30, 40])
        items = items_from(values, groups=[0, 0, 1, 1], indices=[11, 12, 11, 12])
        perfect = ev.summarize(one_hot(values), items)
        self.assertEqual(perfect['bytes']['top1_accuracy'], 1.0)
        self.assertEqual(perfect['bits']['at_precision']['0.995']['called'], 32)
        self.assertEqual(perfect['bits']['at_precision']['0.995']['bits_per_group'], 16.0)
        self.assertEqual(set(perfect['per_role_j']), {'r1j0', 'r1j1'})
        flat = ev.summarize(ev.uniform_probs(4), items)
        self.assertEqual(flat['bits']['at_precision']['0.98']['called'], 0)
        self.assertAlmostEqual(flat['bytes']['top1_accuracy'], 1/256, places=6)

    def test_frozen_thresholds_are_applied(self):
        values = np.array([1, 2])
        items = items_from(values)
        P = one_hot(values, 0.9)
        out = ev.summarize(P, items, frozen=dict(bytes={'0.98': 0.95}, bits={'0.98': 0.5}))
        self.assertEqual(out['bytes']['frozen']['0.98']['called'], 0)
        self.assertEqual(out['bits']['frozen']['0.98']['called'], 16)

    def test_strict_subset_reported(self):
        values = np.array([1, 2, 3])
        items = items_from(values, strict=[True, False, True])
        out = ev.evaluate(one_hot(values), items)
        self.assertEqual(out['strict_subset']['items'], 2)


class PredictionFileTest(unittest.TestCase):
    def test_json_and_npz_round_trip(self):
        items = items_from([5, 6, 7])
        with tempfile.TemporaryDirectory() as tmp:
            doc = dict(format=ev.PREDICTION_FORMAT, method='toy', split='dev', task='T1', items=[
                dict(group='g0', role=1, j=0, logp=[None]*5 + [0.0] + [None]*250),
                dict(group='g1', role=1, j=0, candidates=[6, 9], confidence=0.8)])
            path = Path(tmp)/'p.json'
            path.write_text(json.dumps(doc))
            table, meta = ev.read_predictions(path)
            self.assertEqual(meta['method'], 'toy')
            P, provided, unused = ev.align(table, items)
            np.testing.assert_array_equal(provided, [True, True, False])
            self.assertEqual(unused, 0)
            self.assertAlmostEqual(P[0, 5], 1.0)
            self.assertAlmostEqual(P[1, 6], 0.8)
            np.testing.assert_allclose(P[2], 1/256)
            npz = Path(tmp)/'p.npz'
            ev.save_predictions(npz, items, P, 'toy', 'dev', 'T1')
            table2, meta2 = ev.read_predictions(npz)
            self.assertEqual(meta2['task'], 'T1')
            P2, provided2, _ = ev.align(table2, items)
            self.assertTrue(provided2.all())
            np.testing.assert_allclose(P2, P, atol=1e-6)

    def test_duplicates_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'p.json'
            entry = dict(group='g0', role=1, j=0, candidates=[1], confidence=0.5)
            path.write_text(json.dumps(dict(items=[entry, entry])))
            with self.assertRaises(ValueError):
                ev.read_predictions(path)


class ModePriorTest(unittest.TestCase):
    def make_labels(self, path, capture, n_groups, rng, mode=0xF8):
        """Role-0 plaintext whose keyed bytes are always 0x0F for this mode."""
        plain = rng.integers(0, 256, (n_groups, 60, 33), dtype=np.uint8)
        plain[:, :, 0] = mode
        plain[:, :, 1 + ev.KEYED] = 0x0F
        mask = rng.integers(0, 256, (n_groups, 44)).astype(np.int16)
        cipher = plain.copy()
        for role in range(4):
            cipher[:, role::4, 1 + ev.KEYED] ^= mask[:, None, 11*role:11*role + 11].astype(np.uint8)
        np.savez(path, capture=capture, frames=cipher, present=np.ones((n_groups, 60), bool),
                 mask_label=mask, labelled=np.ones(n_groups, bool), group_id=np.array([f'{capture}:{i}' for i in range(n_groups)]))
        return mask

    def test_prior_recovers_mask_of_a_constant_plaintext_mode(self):
        rng = np.random.default_rng(1)
        with tempfile.TemporaryDirectory() as tmp:
            a, b = Path(tmp)/'a.npz', Path(tmp)/'b.npz'
            self.make_labels(a, 'A', 4, rng)
            mask_b = self.make_labels(b, 'B', 3, rng)
            prior = ev.ModePrior.fit([a, b])
            self.assertEqual(int(prior.total[0xF8].sum()), (4 + 3)*15*88)
            inputs = ev.load_npz(b)
            items = dict(group_id=inputs['group_id'][[0, 1, 2]], capture=np.array(['B']*3),
                         role=np.array([1, 2, 0]), j=np.array([0, 4, 10]),
                         value=np.array([mask_b[0, 11], mask_b[1, 26], mask_b[2, 10]]))
            P, held_out = prior.predict(inputs, items)
            self.assertEqual(held_out, ['B'])           # capture B scored with B left out
            np.testing.assert_array_equal(P.argmax(axis=1), items['value'])
            self.assertTrue((P.max(axis=1) > 0.99).all())

    def test_single_training_capture_is_held_out(self):
        rng = np.random.default_rng(3)
        with tempfile.TemporaryDirectory() as tmp:
            a = Path(tmp)/'a.npz'
            mask = self.make_labels(a, 'A', 3, rng)
            prior = ev.ModePrior.fit([a])
            inputs = ev.load_npz(a)
            items = dict(group_id=inputs['group_id'][[0]], capture=np.array(['A']), role=np.array([1]),
                         j=np.array([0]), value=np.array([mask[0, 11]]))
            P, held_out = prior.predict(inputs, items)
            self.assertEqual(held_out, ['A'])           # never scored in-sample
            np.testing.assert_allclose(P, 1/256)

    def test_unseen_mode_is_uninformative(self):
        rng = np.random.default_rng(2)
        with tempfile.TemporaryDirectory() as tmp:
            a = Path(tmp)/'a.npz'
            self.make_labels(a, 'A', 2, rng, mode=0xF8)
            prior = ev.ModePrior.fit([a])
            frames = rng.integers(0, 256, (15, 33), dtype=np.uint8)
            frames[:, 0] = 0x50
            p = prior.item_probs(frames, np.ones(15, bool), 0, prior.total)
            np.testing.assert_allclose(p, 1/256)


if __name__ == '__main__':
    unittest.main()
