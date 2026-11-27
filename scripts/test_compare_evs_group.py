"""Bit-exact comparison of independently framed G.192 streams on the group clock."""
import gzip
from pathlib import Path
import struct
from tempfile import TemporaryDirectory
import unittest

from compare_evs_group import compare_group


def good_frame(slot):
    word = bytes((slot + 17 * i) % 256 for i in range(33))
    bits = [0x81 if octet & (1 << bit) else 0x7f
            for octet in word for bit in range(7, -1, -1)]
    return struct.pack("<266H", 0x6b21, 264, *bits)


ERASURE = struct.pack("<HH", 0x6b20, 0)


class CompareGroupTests(unittest.TestCase):
    def setUp(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.candidate = self.root / "candidate.192"
        self.reference = self.root / "reference.192.gz"
        self.words = [good_frame(slot) for slot in range(60)]
        self.candidate.write_bytes(b"".join(self.words))
        self.reference.write_bytes(gzip.compress(b"".join(self.words)))

    def compare(self, candidate_start=(87, 0, 0, 1), reference_start=(87, 0, 0, 1)):
        return compare_group(self.candidate, self.reference, counter=87,
                             candidate_start=candidate_start, reference_start=reference_start)

    def test_complete_group_must_match_at_every_position(self):
        result = self.compare()
        self.assertTrue(result["group_exact"])
        for position in ("1", "2", "3", "4"):
            self.assertEqual(result["by_position"][position]["match"], 15)

    def test_partial_reference_starts_mid_phase_and_candidate_crosses_group_boundary(self):
        # Candidate slot zero is the previous counter's final frame. Reference
        # begins at slot 25 of the target counter and covers two of each position.
        self.candidate.write_bytes(good_frame(59) + b"".join(self.words[:40]))
        self.reference.write_bytes(gzip.compress(b"".join(self.words[25:33])))
        result = self.compare(candidate_start=(86, 2, 4, 4), reference_start=(87, 1, 1, 2))
        self.assertFalse(result["group_exact"])
        for position in ("1", "2", "3", "4"):
            row = result["by_position"][position]
            self.assertEqual(row["match"], 2)
            self.assertEqual(row["outside_extent"], 13)
            self.assertEqual(row["candidate_only"], 0)
            self.assertEqual(row["reference_only"], 0)

    def test_flip_one_mode_bit_or_one_payload_bit(self):
        for slot, bit in ((0, 0), (57, 263)):
            with self.subTest(slot=slot, bit=bit):
                words = self.words.copy()
                frame = bytearray(words[slot])
                word_offset = 4 + 2 * bit
                frame[word_offset] = 0x81 if frame[word_offset] == 0x7f else 0x7f
                words[slot] = frame
                self.candidate.write_bytes(b"".join(words))
                result = self.compare()
                self.assertFalse(result["group_exact"])
                position = str(slot % 4 + 1)
                self.assertEqual(result["by_position"][position]["match"], 14)
                self.assertEqual(result["by_position"][position]["mismatch"], 1)

    def test_erasures_count_as_missing_without_shifting_later_words(self):
        candidate, reference = self.words.copy(), self.words.copy()
        candidate[1] = reference[1] = ERASURE
        candidate[5] = ERASURE
        reference[9] = ERASURE
        reference[13] = ERASURE
        self.candidate.write_bytes(b"".join(candidate))
        self.reference.write_bytes(gzip.compress(b"".join(reference)))
        result = self.compare()
        self.assertFalse(result["group_exact"])
        row = result["by_position"]["2"]
        self.assertEqual([row[k] for k in ("match", "mismatch", "both_erased",
                                           "candidate_only", "reference_only", "outside_extent")],
                         [11, 0, 1, 2, 1, 0])

    def test_matching_erasure_timelines_supply_no_evidence(self):
        self.candidate.write_bytes(60 * ERASURE)
        self.reference.write_bytes(gzip.compress(60 * ERASURE))
        result = self.compare()
        self.assertFalse(result["group_exact"])
        for position in ("1", "2", "3", "4"):
            row = result["by_position"][position]
            self.assertEqual(row["both_erased"], 15)
            self.assertEqual(row["match"], 0)

    def test_rejects_truncated_or_malformed_frame(self):
        cases = {"partial_header": b"\x21\x6b", "short_payload": self.words[0][:-2],
                 "odd_byte_count": self.words[0][:-1],
                 "bad_symbol": self.words[0][:-2] + struct.pack("<H", 0x80),
                 "bad_length": struct.pack("<HH", 0x6b21, 0)}
        for kind, frame in cases.items():
            with self.subTest(kind=kind):
                self.reference.write_bytes(gzip.compress(frame))
                with self.assertRaises(ValueError):
                    self.compare()

    def test_rejects_invalid_stream_origins(self):
        for origin in ((-1, 0, 0, 1), (87, 3, 0, 1), (87, 0, 5, 1), (87, 0, 0, 0)):
            with self.subTest(origin=origin):
                with self.assertRaises(ValueError):
                    self.compare(candidate_start=origin)
                with self.assertRaises(ValueError):
                    self.compare(reference_start=origin)


if __name__ == "__main__":
    unittest.main()
