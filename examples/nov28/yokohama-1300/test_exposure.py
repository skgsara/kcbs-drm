import unittest

from exposure import ORIGINAL_SHA, compare, registries


def projection(counter, packets):
    slots = [dict(counter=counter, slot=i, phase=i // 20, cycle=i % 20 // 4, position=i % 4 + 1)
             for i in range(60)]
    return dict(format="kcbs-evs-packet-projection-v1", counter=counter, total_slots=60,
                slots=slots, received_packet_ordinals=packets, transition_tags={}, core_history={},
                intra_word={}, gsc_fields={}, hq_neighbors={})


def score(ids=()):
    return dict(prior_inventory_sha256=ORIGINAL_SHA, packet_snapshot_sha256="a" * 64,
                assigned_counters=list(ids), prior_overlap=[], complete_groups=0,
                groups_with_partial_packet_rows=0, primary=None, first_partial=None)


class ExposureTest(unittest.TestCase):
    def test_complete_partial_and_assigned_only(self):
        fixture = score([11, 22, 30])
        fixture.update(complete_groups=1, groups_with_partial_packet_rows=1,
                       primary=projection(22, {str(p): list(range(4)) for p in range(3)}),
                       first_partial=projection(11, {"1": [0, 3]}))
        got = compare(fixture, {1}, {1, 22, 30})
        self.assertEqual(got["extended_overlap"], [22, 30])
        self.assertTrue(got["primary"]["previously_observed"])
        self.assertFalse(got["first_partial"]["previously_observed"])
        self.assertEqual(got["absent_from_extended_count"], 1)

    def test_no_reception_and_no_historical_intersection(self):
        original, extended, receipt = registries()
        self.assertEqual(receipt["counter_count"], 14882)
        for ids in ([], [0xffffffff]):
            got = compare(score(ids), original, extended)
            self.assertEqual(got["extended_overlap"], [])
            self.assertEqual(got["assigned_count"], len(ids))
            self.assertEqual(got["primary"]["status"], "no_eligible_group")

    def test_frozen_gate_hides_selection_for_whole_run(self):
        fixture = score([1, 2, 3])
        fixture.update(prior_overlap=[1], complete_groups=1, groups_with_partial_packet_rows=1)
        got = compare(fixture, {1}, {1, 3})
        self.assertEqual(got["additional_prior_exposure"], [3])
        for label in ["primary", "first_partial"]:
            self.assertEqual(got[label]["status"], "suppressed_by_frozen_overlap")
            self.assertIsNone(got[label]["counter"])

    def test_rejects_wrong_original_overlap_and_missing_partial_phase(self):
        fixture = score([1])
        with self.assertRaisesRegex(ValueError, "intersection"):
            compare(fixture, {1}, {1})
        fixture.update(groups_with_partial_packet_rows=1,
                       first_partial=projection(1, {"1": [0, 1, 2, 3]}))
        with self.assertRaisesRegex(ValueError, "partially received"):
            compare(fixture, set(), {1})


if __name__ == "__main__":
    unittest.main()
