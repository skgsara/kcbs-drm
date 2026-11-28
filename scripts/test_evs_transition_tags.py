import unittest

from evs_transition_tags import allowed_pairs, field, transition_tags


class TransitionTest(unittest.TestCase):
    def test_all_observable_combinations(self):
        for mode in range(0x60, 0x68):
            for p31 in range(256):
                if mode & 3 == 0:
                    expected = [0] if p31 & 3 else [0, 2, 3] if p31 & 63 else [0, 1, 2, 3]
                elif mode & 3 == 1:
                    expected = ([] if p31 & 1 else [1] if p31 & 7 else [0, 1] if p31 & 63
                                else [0, 1, 2, 3])
                else:
                    expected = [0, 1, 2, 3]
                self.assertEqual(allowed_pairs(mode, p31), expected)
        self.assertIsNone(allowed_pairs(0x68, 4))
        self.assertIsNone(allowed_pairs(0x61, None))
        self.assertEqual(field(0x65, 3)["outcome"], "contradiction")
        self.assertEqual(field(0x65, 3)["fixed_word_bits"], {})
        self.assertEqual(field(0x61, 32)["fixed_word_bits"], {"8": 0})
        self.assertEqual(field(0x60, 4)["fixed_word_bits"], {})

    def test_target_is_withheld_and_a_missing_ending_abstains(self):
        row = dict(slot=1, counter=100, phase=0, cycle=0, position=2, receipt="received_du")
        def check(first, last):
            return transition_tags([dict(row, octets=" ".join(["61", first] + ["??"] * 30 + [last]))])
        a = check("??", "04")
        for first in ("00", "ff"):
            self.assertEqual(check(first, "04"), a)
        self.assertEqual(a["slots"][0]["fixed_word_bits"], {"8": 0, "9": 1})
        self.assertEqual(check("??", "--")["slots"], [])


if __name__ == "__main__":
    unittest.main()
