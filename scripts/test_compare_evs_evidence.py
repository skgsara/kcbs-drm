"""Compare saved RF evidence to independent synthetic slot-addressed words."""
import gzip
from hashlib import sha256
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest

import numpy as np

from compare_evs_evidence import compare_evidence
from render_continuous import MODE_POSITIONS
from test_project_evs_group import COUNTER, finish, fixture


def g192(word):
    if not word:
        return struct.pack("<HH", 0x6b20, 0)
    bits = [0x81 if byte & (0x80 >> bit) else 0x7f for byte in word for bit in range(8)]
    return struct.pack("<266H", 0x6b21, 264, *bits)


class CompareEvidence(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        root = Path(scratch.name)
        self.projection, self.reference = root / "fields.json", root / "reference"
        phase, words = fixture(0)
        self.words = [bytearray(w) for w in words]
        for i, mode in enumerate((0xf9, 0xf8, 0xf9, 0xfc, 0xfa, 0xf9, 0xf8, 0xf8)):
            phase[MODE_POSITIONS[i]] = self.words[i][0] = mode
            self.words[i][1] = 0
        # FA permits 00/01/10 at b8:b9. This reference supplies 11.
        self.words[4][1] = 0xc0
        archive = root / "data_units.npz"
        np.savez(archive, counters=np.array([COUNTER], np.uint32), phases=np.array([0], np.uint8),
                 du=np.frombuffer(finish(phase), np.uint8).reshape(1, 716))
        cmd = [sys.executable, "-B", Path(__file__).with_name("project_evs_group.py"), archive,
               "--counter", str(COUNTER), "--field-checks"]
        self.projection.write_bytes(subprocess.check_output(cmd))

    def compare(self, start=(COUNTER, 0, 0, 1)):
        return compare_evidence(self.projection, self.reference, start=start)

    @staticmethod
    def predicate(result, slot, name):
        return next(e for e in result["slots"][slot]["predicates"] if e["check"] == name)

    def test_counts_distinct_reference_statuses_and_scores_only_restricted_fields(self):
        magic = b"#!EVS_MC1.0\n" + struct.pack(">I", 1)
        # The reference extends two slots into a phase missing from the receiver.
        words = [*self.words, bytes(33), None]
        self.reference.write_bytes(magic + b"".join(b"\x04" + w if w else b"\x0e" for w in words))
        result = self.compare()
        self.assertEqual([result[k] for k in ("projection_sha256", "reference_sha256")],
                         [sha256(p.read_bytes()).hexdigest() for p in (self.projection, self.reference)])
        self.assertEqual(result["total"]["slots"], dict(direct_agreement=20, direct_disagreement=0,
                         reference_only=1, reference_erasure=1, outside_extent=38))
        self.assertEqual(result["total"]["matching_direct_bits"], 20 * 176)
        self.assertEqual(self.predicate(result, 1, "hq_neighbor_class")["outcome"], "match")
        self.assertEqual(self.predicate(result, 6, "hq_neighbor_class")["outcome"], "unrestricted")
        rejected = self.predicate(result, 4, "swb_hq_class")
        self.assertEqual((rejected["allowed_values"], rejected["reference_value"], rejected["outcome"]),
                         ([0, 1, 2], 3, "mismatch"))
        for counts in result["by_position"].values():
            self.assertEqual(sum(counts["slots"].values()), 15)
        self.assertNotIn("group_exact", result)

    def test_keep_bit_comparisons_when_dependency_conflict_quarantines_predicates(self):
        self.words[2][0] ^= 1  # Direct successor b7, used by the middle word's field check.
        self.words[2][2] ^= 0x80  # A second direct disagreement in the same word.
        self.reference.write_bytes(b"".join(g192(w) for w in self.words[:6]))
        result = self.compare()
        bad = result["slots"][2]
        self.assertEqual((bad["differing_word_bit_offsets"], bad["matching_direct_bits"]), ([7, 16], 174))
        self.assertEqual(result["total"]["compared_direct_bits"], 6 * 176)
        self.assertEqual(result["total"]["matching_direct_bits"], 6 * 176 - 2)
        central = self.predicate(result, 1, "hq_neighbor_class")
        self.assertEqual((central["outcome"], central["conflicting_slots"]), ("quarantined", [2]))
        witness = next(i for i in central["inputs"] if i["role"] == "withheld_witness")
        self.assertEqual((witness["observed"], witness["reference_value"], witness["agrees_with_reference"]),
                         (1, 0, False))
        self.assertEqual(self.predicate(result, 2, "swb_hq_class")["outcome"], "quarantined")
        self.assertEqual(self.predicate(result, 4, "swb_hq_class")["outcome"], "mismatch")

    def test_partial_gzip_reference_with_explicit_erasure_keeps_origins(self):
        self.reference.write_bytes(gzip.compress(g192(self.words[1]) + g192(None) + g192(self.words[3])))
        result = self.compare(start=(COUNTER, 0, 0, 2))
        self.assertEqual([row["status"] for row in result["slots"][:5]],
                         ["outside_extent", "direct_agreement", "reference_erasure", "direct_agreement", "outside_extent"])
        check = self.predicate(result, 1, "hq_neighbor_class")
        self.assertEqual(check["outcome"], "match")
        self.assertIsNone(check["inputs"][-1]["reference_value"])
        self.assertEqual(self.predicate(result, 2, "swb_hq_class")["outcome"], "reference_erasure")
        with self.assertRaises(ValueError):
            self.compare(start=(COUNTER, 3, 0, 1))

    def test_partial_receiver_keeps_a_reference_observation_separate(self):
        # At slot eight the P1 mode arrives in q0. Its p4 belongs to the absent q1.
        phase, _ = fixture(0)
        phase[MODE_POSITIONS[8]] = self.words[8][0] = 0x68
        snap = self.projection.with_suffix(".npz")
        np.savez(snap, ticks=[3 * COUNTER], packets=np.frombuffer(phase, np.uint8).reshape(1, 4, 179),
                 packet_ok=[[True, False, False, False]])
        self.projection.write_bytes(subprocess.check_output([
            sys.executable, "-B", Path(__file__).with_name("project_evs_group.py"), "--packets", snap,
            "--counter", str(COUNTER), "--field-checks"]))
        self.reference.write_bytes(g192(self.words[8]))
        result = self.compare((COUNTER, 0, 2, 1))
        self.assertEqual((result["slots"][8]["status"], result["total"]["matching_direct_bits"]),
                         ("direct_agreement", 8))
        event = self.predicate(result, 8, "audio_noisy")
        self.assertEqual((event["target_receipt"], event["projection_value"], event["reference_value"]),
                         ("no_receipt", None, 0))
        self.assertEqual(event["outcome"], "mismatch")

    def test_input_errors(self):
        self.reference.write_bytes(b"\x21")
        with self.assertRaisesRegex(ValueError, "truncated"):
            self.compare()
        self.projection.write_text('{"counter": 1, "counter": 2}')
        with self.assertRaisesRegex(ValueError, "duplicate"):
            self.compare()


if __name__ == "__main__":
    unittest.main()
