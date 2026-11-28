"""A direct-octet hit is a candidate coordinate within the supplied archive."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import numpy as np

from locate_evs_slots import build_index, check_against_receiver, export_locations
from test_compare_evs_evidence import g192
from test_project_evs_group import COUNTER, fixture


class LocateEVSSlots(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.dus = Path(temp.name) / "data_units.npz"
        self.export = Path(temp.name) / "input.192"

    def save_units(self, rows):
        np.savez(self.dus,
                 counters=np.array([count for count, _, _ in rows], np.uint32),
                 phases=np.array([phase for _, phase, _ in rows], np.uint8),
                 du=np.array([list(unit) for _, _, unit in rows], np.uint8).reshape(-1, 716))

    def index(self, rows):
        self.save_units(rows)
        return build_index(self.dus)

    def locate(self, index, words):
        self.export.write_bytes(b"".join(g192(word) for word in words))
        return list(export_locations(index, self.export))

    def index_with_packets(self, unit, phase, flags):
        path = self.dus.with_name("packets.npz")
        np.savez(path, ticks=np.array([3 * COUNTER + phase], np.int64),
                 packets=np.frombuffer(unit, np.uint8).reshape(1, 4, 179),
                 packet_ok=np.array([flags], np.bool_))
        return build_index(self.dus, extra_packets=path)

    def test_all_twenty_offsets_in_each_du_and_missing_phase(self):
        first, words0 = fixture(0)
        last, words2 = fixture(2)
        index = self.index([(COUNTER, 2, last), (COUNTER, 0, first)])
        self.assertEqual(len(index), 40)
        # P1 modes are packed separately. Retain the actual phase even if an entire DU is absent.
        for phase, words in ((0, words0), (2, words2)):
            for local, word in enumerate(words):
                with self.subTest(phase=phase, local=local):
                    # Omit payload 0,3,...,30. The mode is the first physical word octet.
                    fingerprint = word[:1] + bytes(word[1 + p] for p in range(32) if p % 3)
                    self.assertEqual(len(fingerprint), 22)
                    self.assertEqual(index[fingerprint], [(COUNTER, phase, local // 4, local % 4 + 1)])
        _, missing = fixture(1)
        rows = self.locate(index, [words0[-1], b"", missing[0], words2[0]])
        self.assertEqual([r["input_slot"] for r in rows], [0, 1, 2, 3])
        self.assertEqual([r["outcome"] for r in rows], ["unique", "erasure", "unmatched", "unique"])
        self.assertEqual([r["candidates"] for r in rows],
                         [[(COUNTER, 0, 4, 4)], [], [], [(COUNTER, 2, 0, 1)]])

    def test_mode_and_every_included_payload_octet_are_compared(self):
        unit, words = fixture(0)
        index = self.index([(COUNTER, 0, unit)])
        variants = []
        for i in range(33):
            changed = bytearray(words[19])
            changed[i] ^= 0x80
            variants.append(changed)
        for i, row in enumerate(self.locate(index, variants)):
            with self.subTest(word_octet=i):
                included = i == 0 or (i - 1) % 3 != 0
                self.assertEqual(row["outcome"], "unmatched" if included else "unique")
                self.assertEqual(row["candidates"], [] if included else [(COUNTER, 0, 4, 4)])

    def test_duplicate_queries_and_true_source_absent(self):
        # These two DUs carry equal projections at the same local slot. Phase 1 contains no embedded counter.
        unit, words = fixture(1)
        query = words[3]
        source = (COUNTER + 2, 1, 0, 4)
        other = (COUNTER, 1, 0, 4)
        index = self.index([(other[0], 1, unit), (source[0], 1, unit)])
        rows = self.locate(index, [query, query])
        self.assertEqual([row["input_slot"] for row in rows], [0, 1])
        for row in rows:
            self.assertEqual(row["outcome"], "ambiguous")
            self.assertCountEqual(row["candidates"], [source, other])
        # Removing the originating occurrence makes a different coordinate unique in this smaller index.
        index = self.index([(other[0], 1, unit)])
        row, = self.locate(index, [query])
        self.assertEqual((row["outcome"], row["candidates"]), ("unique", [other]))
        # The peer knows the real coordinates of both copies. Only the first is in the smaller index.
        self.save_units([(other[0], 1, unit), (source[0], 1, unit)])
        score = check_against_receiver(index, self.dus)["by_true_coordinate"]
        self.assertEqual(score["absent"], {"unique_wrong": 20})
        self.assertEqual(score["present"], {"unique_correct": 20})

    def test_empty_index_and_invalid_du_crc(self):
        unit, words = fixture(0)
        rows = self.locate(self.index([]), [words[0], b""])
        self.assertEqual([r["outcome"] for r in rows], ["unmatched", "erasure"])
        self.assertTrue(all(row["candidates"] == [] for row in rows))
        unit[74] ^= 1
        with self.assertRaisesRegex(ValueError, "CRC"):
            self.index([(COUNTER, 0, unit)])

    def test_packet_flags_control_all_direct_octets_including_packed_p1_modes(self):
        self.index([])
        unit, words = fixture(1)
        cases = [
            ([False] * 4, []),
            ([True, False, False, False], [0, 1, 2, 3, 4]),
            ([False, True, False, False], [6, 7, 9]),
            ([True, True, False, False], list(range(10))),
            ([False, False, True, True], [11, 13, 14, 15, 17, 18, 19]),
            ([True] * 4, list(range(20))),
        ]
        for flags, expected in cases:
            with self.subTest(flags=flags):
                # In slot 5 the payload crosses q0–q1. Slot 8 has its mode in q0 and payload in q1.
                # Even bytes which happen to be correct give no index entry without the packet flag.
                index = self.index_with_packets(unit, 1, flags)
                rows = self.locate(index, words)
                actual = [row["input_slot"] for row in rows if row["outcome"] == "unique"]
                self.assertEqual(actual, expected)
                for i, row in enumerate(rows):
                    coordinates = [(COUNTER, 1, i // 4, i % 4 + 1)] if i in expected else []
                    self.assertEqual(row["candidates"], coordinates)
                altered = bytearray(unit)
                for q, present in enumerate(flags):
                    if not present:
                        altered[179 * q:179 * (q + 1)] = bytes([255]) * 179
                self.assertEqual(self.index_with_packets(altered, 1, flags), index)

    def test_duplicate_coordinate_verifies_accepted_packet_bodies(self):
        unit, words = fixture(0)
        standard = self.index([(COUNTER, 0, unit)])
        self.assertEqual(self.index_with_packets(unit, 0, [True] * 4), standard)
        unit[200] ^= 1  # q1 storage is unobserved in the supplemental snapshot.
        extra = self.index_with_packets(unit, 0, [True, False, False, False])
        self.assertEqual(extra, standard)
        self.assertEqual(self.locate(extra, [words[0]])[0]["outcome"], "unique")
        # q0 is shared with the full DU: p1 in slot 0, p0 in slot 0, and the mode of incomplete slot 8.
        for offset in (8, 7, 4):
            with self.subTest(offset=offset):
                changed = bytearray(unit)
                changed[offset] ^= 1
                with self.assertRaises(ValueError):
                    self.index_with_packets(changed, 0, [True, False, False, False])


if __name__ == "__main__":
    unittest.main()
