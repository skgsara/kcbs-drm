"""Regression checks on the published authored-fixture seal and its scoring boundaries."""
from copy import deepcopy
import gzip
import json
import unittest

from check import CASE, HERE, checked
from scoring import evaluate, score

PIN = "6094f8bda93d80222431c43de73277b23061b757e43909424f92bc782a16a7e9"


class AuthoredFixtureTests(unittest.TestCase):
    def test_original_seal_and_all_sender_counts(self):
        ledger = json.loads(gzip.decompress(checked(HERE / "forecast.json.gz", PIN)))
        sender = CASE / "fixture/sender.192.gz"
        computed = score(ledger, PIN, sender)
        self.assertEqual(computed, json.loads((HERE / "score.json").read_bytes()))
        witness = computed["predecessor_control"]
        self.assertEqual((witness["before"], witness["after"], witness["after_reason"]),
                         ([1], None, "previous_mode_unavailable"))
        self.assertFalse(witness["predecessor_wire_word_complete"])
        altered = deepcopy(ledger)
        altered["groups"][2]["slots"].pop(1)
        with self.assertRaisesRegex(ValueError, "sixty slots"):
            score(altered, PIN, sender)

    def test_shifted_labels_stop_at_each_edge(self):
        slots = [dict(slot=i % 60, position=i % 4 + 1, tcx_previous_core=[0], transition_tag=[0, 2])
                 for i in range(120)]
        words = [bytes(33)] * len(slots)
        for shift in (-1, 1):
            got = evaluate(slots, words, shift)
            for counts in got.values():
                self.assertEqual((counts["compared"], counts["outside_shifted_group"]), (118, 2))


if __name__ == "__main__":
    unittest.main()
