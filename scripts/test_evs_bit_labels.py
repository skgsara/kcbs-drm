"""Sparse human observations retain their declared coordinates, bit values and witnesses."""
import csv
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import numpy as np

from evs_bit_labels import compare_bit_labels
from evs_evidence import field_sections
from project_evs_group import project_group
from render_continuous import MODE_POSITIONS, PACKET_STARTS
from test_compare_evs_evidence import g192
from test_project_evs_group import COUNTER, finish, fixture


HEADER = ["counter", "phase", "cycle", "position", "first_bit", "bits"]


class SparseBitLabels(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.directory = Path(temp.name)
        self.projection = self.directory / "projection.json"
        self.labels = self.directory / "observations.csv"
        self.cli = Path(__file__).with_name("compare_evs_evidence.py")

        complete, words = fixture(0)
        modes = (0xf9, 0xf8, 0xf9, 0xfa, 0x61, 0x61)
        for slot, mode in enumerate(modes):
            complete[MODE_POSITIONS[slot]] = mode
        # Mode 61 and this directly carried suffix allow 00/01. Only b8 is fixed.
        complete[PACKET_STARTS[4] + 31] = 8
        complete[PACKET_STARTS[5] + 31] = 2  # Only 01 is allowed, so b8 and b9 are both fixed.
        self.first_word = bytes([modes[0]]) + words[0][1:]
        partial, _ = fixture(1)
        partial[MODE_POSITIONS[8]] = 0x68  # P1 mode in packet 0; its p4 in absent packet 1.
        snapshot = self.directory / "packets.npz"
        packets = np.array([list(finish(complete)), list(partial)], np.uint8).reshape(2, 4, 179)
        np.savez(snapshot, ticks=np.array([3 * COUNTER, 3 * COUNTER + 1]),
                 packets=packets, packet_ok=np.array([[True] * 4, [True, False, False, False]]))
        projected = project_group(snapshot, COUNTER, packets=True)
        projected.update(field_sections(projected["slots"]))
        self.projection.write_text(json.dumps(projected), encoding="utf-8")

    def compare(self, *observations, witness_column=True):
        """Rows contain a group slot, first word bit, a contiguous bit string and optionally its witness."""
        with self.labels.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.writer(stream)
            writer.writerow(HEADER + (["witness"] if witness_column else []))
            for slot, first_bit, bits, *witness in observations:
                cells = [COUNTER, slot // 20, (slot % 20) // 4, slot % 4 + 1, first_bit, bits]
                writer.writerow(cells + ([witness[0] if witness else ""] if witness_column else []))
        return compare_bit_labels(self.projection, self.labels)

    @staticmethod
    def event(result, slot, check):
        return next(e for e in result["slots"][slot]["predicates"] if e["check"] == check)

    def test_partial_labels_never_complete_a_field_or_a_word(self):
        result = self.compare((3, 8, "1"), witness_column=False)
        row = result["slots"][3]
        self.assertEqual(row["coordinate_agreement"], "coordinates_only")
        self.assertEqual(set(row["labels"]), {"8"})
        self.assertEqual(row["labels"]["8"]["values"], [1])
        obs, = row["labels"]["8"]["observations"]
        self.assertEqual((obs["count"], obs["unattributed_count"], obs["witness_ids"]), (1, 1, []))
        field = self.event(result, 3, "swb_hq_class")
        self.assertEqual(field["allowed_values"], [0, 1, 2])
        self.assertEqual((field["field_coverage"], field["field_outcome"], field["label_value"], field["membership"]),
                         ("partial", "partial", None, None))
        self.assertEqual(field["fixed_bits"], {})
        self.assertEqual(result["slots"][2]["coordinate_agreement"], "no_labels")
        self.assertEqual((result["receiver_word_erasures"], result["new_receiver_words"]), (60, 0))

        for bits, expected, status in [("10", 2, "match"), ("11", 3, "mismatch")]:
            with self.subTest(bits=bits):
                field = self.event(self.compare((3, 8, bits, "reader")), 3, "swb_hq_class")
                self.assertEqual((field["field_coverage"], field["label_value"], field["membership"]),
                                 ("complete", expected, status))

    def test_fixed_bit_requires_the_corresponding_label(self):
        partial = self.event(self.compare((4, 9, "0", "A")), 4, "transition_tag")
        self.assertEqual(partial["allowed_values"], [0, 1])
        self.assertEqual(partial["field_outcome"], "partial")
        self.assertEqual(partial["fixed_bits"]["8"]["relation"], "no_label")
        other = self.event(self.compare((4, 8, "1", "A")), 4, "transition_tag")
        self.assertEqual((other["label_value"], other["membership"], other["fixed_bits"]["8"]["relation"]),
                         (None, None, "mismatch"))

    def test_overlapping_labels_keep_one_coordinate_and_distinct_witnesses(self):
        result = self.compare((3, 8, "10", "record A"), (3, 9, "0", "record B"), (3, 9, "0"))
        self.assertEqual(result["total"]["supplied_bit_observations"], 4)
        self.assertEqual(result["total"]["labelled_bits"], 2)
        self.assertEqual(result["total"]["field_comparisons"], 1)
        row = result["slots"][3]
        self.assertEqual(set(row["labels"]), {"8", "9"})
        label = row["labels"]["9"]
        self.assertEqual(label["values"], [0])
        observation, = label["observations"]
        self.assertEqual(observation["count"], 3)
        self.assertEqual(observation["unattributed_count"], 1)
        self.assertEqual(observation["witness_ids"], ["record A", "record B"])
        self.assertEqual(self.event(result, 3, "swb_hq_class")["membership"], "match")

        result = self.compare((3, 8, "10", "record A"), (3, 9, "1", "record B"))
        row = result["slots"][3]
        self.assertEqual(row["coordinate_agreement"], "coordinates_only")
        self.assertEqual(row["labels"]["9"]["values"], [0, 1])
        field = self.event(result, 3, "swb_hq_class")
        self.assertEqual(field["field_outcome"], "conflicting_labels")
        self.assertEqual(field["quarantined_slots"], [])
        self.assertIsNone(field["membership"])

    def test_disputed_hidden_bit_preserves_other_fixed_bit_and_direct_agreement(self):
        result = self.compare((5, 0, "0", "mode"), (5, 8, "01", "A"), (5, 8, "11", "B"))
        row = result["slots"][5]
        self.assertEqual(row["coordinate_agreement"], "direct_agreement")
        self.assertEqual(row["labels"]["8"]["values"], [0, 1])
        self.assertEqual(row["labels"]["9"]["values"], [1])
        event = self.event(result, 5, "transition_tag")
        self.assertEqual(event["allowed_values"], [1])
        self.assertEqual(event["field_outcome"], "conflicting_labels")
        self.assertEqual(event["quarantined_slots"], [])
        self.assertIsNone(event["membership"])
        self.assertEqual(event["fixed_bits"]["8"]["relation"], "conflict")
        self.assertEqual(event["fixed_bits"]["9"]["relation"], "match")
        total = result["total"]
        self.assertEqual((total["field_comparisons"], total["fixed_bit_comparisons"],
                          total["fixed_bit_matches"], total["fixed_bit_conflicts"]), (0, 1, 1, 1))

    def test_hidden_dispute_in_successor_does_not_quarantine_neighbor(self):
        result = self.compare((1, 8, "0", "central"), (2, 7, "1", "mode"),
                              (2, 8, "0", "A"), (2, 8, "1", "B"))
        self.assertEqual(result["slots"][2]["coordinate_agreement"], "direct_agreement")
        self.assertEqual(self.event(result, 2, "swb_hq_class")["field_outcome"], "conflicting_labels")
        field = self.event(result, 1, "hq_neighbor_class")
        self.assertEqual((field["field_outcome"], field["quarantined_slots"]), ("match", []))

    def test_direct_label_witness_and_absent_packet_remain_distinct(self):
        result = self.compare((28, 40, "1", "field note"))
        row = result["slots"][28]
        self.assertEqual(row["coordinate_agreement"], "coordinates_only")
        self.assertEqual(row["labels"]["40"]["direct_relation"], "not_direct")
        self.assertIsNone(row["labels"]["40"]["direct_value"])

        result = self.compare((28, 40, "1", "field note"), (28, 0, "0", "mode note"))
        row = result["slots"][28]
        self.assertEqual(row["coordinate_agreement"], "direct_agreement")
        self.assertEqual(row["labels"]["0"]["direct_relation"], "match")
        self.assertEqual(row["labels"]["40"]["direct_relation"], "not_direct")
        self.assertEqual(self.event(result, 28, "audio_noisy")["membership"], "match")
        self.assertEqual((result["receiver_word_erasures"], result["new_receiver_words"]), (60, 0))

    def test_wrong_successor_bit_quarantines_adjacent_event(self):
        # The HQ rule's target belongs to the central word. Its held-out witness belongs to the successor.
        result = self.compare((1, 8, "0", "central"), (2, 7, "0", "successor"))
        self.assertEqual(result["slots"][2]["coordinate_agreement"], "direct_disagreement")
        field = self.event(result, 1, "hq_neighbor_class")
        self.assertEqual((field["field_outcome"], field["quarantined_slots"]), ("quarantined", [2]))
        result = self.compare((1, 8, "0", "central"), (2, 7, "0", "A"), (2, 7, "1", "B"))
        successor = result["slots"][2]
        self.assertEqual(successor["labels"]["7"]["direct_relation"], "conflict")
        self.assertEqual(successor["coordinate_agreement"], "conflicting_labels")
        field = self.event(result, 1, "hq_neighbor_class")
        self.assertEqual((field["field_outcome"], field["quarantined_slots"]), ("quarantined", [2]))
        self.assertEqual((result["total"]["direct_compared_bits"], result["total"]["direct_conflicted_bits"]), (0, 1))

    def test_cli_uses_csv_coordinates_and_preserves_g192_mode(self):
        expected = self.compare((3, 8, "10", "A"))
        proc = subprocess.run([sys.executable, "-B", self.cli, self.projection, self.labels, "--bit-labels"],
                              capture_output=True, check=True)
        self.assertEqual(json.loads(proc.stdout), expected)
        self.assertEqual(expected["format"], "kcbs-evs-bit-label-comparison-v1")

        reference = self.directory / "one.192"
        reference.write_bytes(g192(self.first_word))
        out = subprocess.check_output([sys.executable, "-B", self.cli, self.projection, reference, "--start",
                                       str(COUNTER), "0", "0", "1"])
        old = json.loads(out)
        self.assertEqual(old["format"], "kcbs-evs-reference-evidence-v1")
        self.assertEqual(old["total"]["matching_direct_bits"], 176)
        self.assertEqual(old["total"]["slots"]["outside_extent"], 59)

    def test_out_of_bounds_and_nonbinary_label_runs_are_invalid(self):
        for bit, value in [(263, "01"), (-1, "0"), (8, "1?"), (8, "")]:
            with self.subTest(bit=bit, value=value), self.assertRaises(ValueError):
                self.compare((0, bit, value))


if __name__ == "__main__":
    unittest.main()
