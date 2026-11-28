import unittest

from evs_hq_neighbors import eligible, hq_neighbors


def slot(i, mode, count=0, payload="??", receipt="received_du"):
    return dict(slot=i, counter=count, phase=i // 20, cycle=i % 20 // 4, position=1 + i % 4,
                octets=" ".join([mode] + [payload] * 32), receipt=receipt)


class HQNeighborsTest(unittest.TestCase):
    def test_masked_successor_selection_and_unread_payload(self):
        for future, alternatives in [(0xf9, [0]), (0xf8, [0, 1])]:
            self.assertTrue(eligible(0xf9, 0xf8, future >> 1))
            first, last = slot(2, "f9"), slot(4, f"{future:02x}")
            for octet in ("??", "00", "ff"):
                result = hq_neighbors([first, slot(3, "f8", payload=octet), last])
                self.assertEqual(result["slots"][0]["allowed_central_b8"], alternatives)
                self.assertEqual(result["slots"][0]["position"], 4)
                self.assertEqual(result["transient_excluded"], future & 1)

    def test_no_switch_gap_or_cross_counter_pair(self):
        self.assertFalse(eligible(0xf8, 0xf8, 0x7c))
        self.assertFalse(eligible(0xf9, 0xf9, 0x7c))
        for invalid in [slot(4, "fa"), slot(4, "f9", count=1), slot(5, "f9"),
                        slot(4, "--", receipt="missing_du")]:
            self.assertEqual(hq_neighbors([slot(2, "f9"), slot(3, "f8"), invalid])["eligible"], 0)


if __name__ == "__main__":
    unittest.main()
