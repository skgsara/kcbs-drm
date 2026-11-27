"""Check clock and erasure handling in the two-sided EVS listening render."""
import unittest

import numpy as np

from interpolate_evs_audio import FRAME, interpolate


class InterpolationTests(unittest.TestCase):
    def test_explicit_erasure_remains_silent(self):
        rng = np.random.default_rng(42)
        strict = rng.normal(0, .1, 48*FRAME).astype('f')
        listening = strict.copy()
        gap = slice(8*FRAME, 28*FRAME)
        strict[gap] = listening[gap] = 0
        output = interpolate(strict, listening)
        self.assertEqual(output.shape, strict.shape)
        self.assertTrue(np.isfinite(output).all())
        self.assertFalse(output[gap].any())
        self.assertGreater(np.linalg.norm(output[:8*FRAME]), 0)

    def test_short_complete_frame_and_incomplete_input(self):
        frame = np.zeros(FRAME, dtype='f')
        np.testing.assert_array_equal(interpolate(frame, frame), frame)
        with self.assertRaisesRegex(ValueError, 'whole number'):
            interpolate(frame[:-1], frame[:-1])


if __name__ == '__main__':
    unittest.main()
