import unittest

import numpy as np

from role1_key_search import mask_trials


class MaskTrialsTest(unittest.TestCase):
    def test_shared_mask_recovers_each_distinct_frame(self):
        original = np.arange(15, dtype=np.uint8) * 17
        planted = 149
        trials = mask_trials(original, planted)
        np.testing.assert_array_equal(trials[planted], original)
        self.assertEqual(trials.shape, (256, 15))
        for index, values in enumerate(trials):
            self.assertEqual(len(np.unique(values)), len(original))
            if index != planted:
                self.assertTrue(np.all(values != original))


if __name__ == '__main__':
    unittest.main()
