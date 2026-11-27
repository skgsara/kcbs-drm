"""Synthetic 13.2 kb/s transform transitions and abstention boundaries."""
import unittest

from evs_core_history import core_history


def row(counter, slot, mode, receipt="received_du"):
    return dict(slot=slot, counter=counter, phase=slot // 20, cycle=slot % 20 // 4,
                position=slot % 4 + 1, receipt=receipt, octets=mode + " " + " ".join(["??"] * 32))


class CoreHistoryTest(unittest.TestCase):
    def test_transform_index_boundaries_and_separate_hq_observation(self):
        for transform in (29, 30, 31):
            for predecessor, mdct in ((0, False), (20 << 3, False), (29 << 3, True), (0xff, True)):
                for tcx in (False, True):
                    for low in range(4):
                        current = (transform << 3) | (int(tcx) << 2) | low
                        with self.subTest(previous=predecessor, current=current):
                            slots = [row(3, 3, f"{predecessor:02x}"), row(3, 4, f"{current:02x}")]
                            report = core_history(slots)
                            first, second = report["slots"]
                            self.assertEqual(first["outcome"], "abstain")
                            self.assertEqual(second["target_word_bit"], 8 if tcx else 6)
                            self.assertEqual(second["predicted"], int(mdct if tcx else not mdct))
                            observed = None if tcx else (low >> 1)
                            self.assertEqual(second["observed"], observed)
                            outcome = "tcx_conditional" if tcx else (
                                "hq_match" if observed == int(not mdct) else "hq_mismatch")
                            self.assertEqual(second["outcome"], outcome)
                            self.assertEqual(report["by_position"]["1"][outcome], 1)
                            self.assertEqual(report["total"]["slots"], 2)

    def test_missing_or_excluded_predecessor_abstains(self):
        for first in [row(3, 0, f"{idx << 3:02x}") for idx in range(21, 29)] + [
                row(3, 0, "--", "missing_du"), row(3, 0, "00", "fill"), row(3, 0, "??"),
                row(2, 0, "00"), row(3, 5, "00")]:
            with self.subTest(first=first):
                last = core_history([first, row(3, 1, "fd")])["slots"][-1]
                self.assertEqual(last["outcome"], "abstain")
                self.assertIsNone(last["predicted"])
                self.assertIsNone(last["observed"])

    def test_missing_phase_keeps_clock_and_interrupts_first_next_edge(self):
        slots = [row(9, i, "fc") if i < 20 or i >= 40 else row(9, i, "--", "missing_du")
                 for i in range(60)]
        report = core_history(slots)
        self.assertEqual(report["slots"][40]["reason"], "previous_mode_unavailable")
        self.assertEqual(report["total"], dict(slots=60, abstain=22, tcx_conditional=38, hq_match=0, hq_mismatch=0))
        self.assertTrue(all(p["slots"] == 15 for p in report["by_position"].values()))


if __name__ == "__main__":
    unittest.main()
