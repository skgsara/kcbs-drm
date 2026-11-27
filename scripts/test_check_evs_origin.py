"""Synthetic independently projected word receipts on the 60-slot counter clock."""
from contextlib import redirect_stderr, redirect_stdout
from hashlib import sha256, shake_256
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from check_evs_origin import main
from compare_evs_group import compare_group


# Mode, followed by the second and third payload byte of each complete 3-byte
# block, plus payload byte 31. Values are physical octet indices.
DIRECT = (0, 2, 3, 5, 6, 8, 9, 11, 12, 14, 15, 17, 18, 20, 21, 23, 24, 26, 27, 29, 30, 32)


class OriginTest(unittest.TestCase):
    def setUp(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        self.target, self.receipt, self.export = (root / name for name in ("target.json", "receipt.json", "test.evs"))
        self.target.write_text(json.dumps({"format": "opaque-drm-transport-target-v1", "target": {"counter": 123}}))
        self.words = [shake_256(bytes([i])).digest(33) for i in range(60)]
        self.witness = dict(format="kcbs-evs-origin-v1", counter=123,
                            target_sha256=sha256(self.target.read_bytes()).hexdigest(),
                            position_sha256=[sha256(bytes(word[i] for word in self.words[k::4] for i in DIRECT))
                                             .hexdigest() for k in range(4)])
        self.receipt.write_text(json.dumps(self.witness))
        self.write_words(self.words)

    def write_words(self, words):
        self.export.write_bytes(b"#!EVS_MC1.0\n\x00\x00\x00\x01"
                                + b"".join(b"\x04" + w if w else b"\x0e" for w in words))

    def run_cli(self, code, start=("123", "0", "0", "1")):
        out, err = StringIO(), StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            actual = main([str(self.receipt), str(self.export), "--target", str(self.target), "--start", *start])
        self.assertEqual(actual, code, (out.getvalue(), err.getvalue()))
        return json.loads(err.getvalue() if code == 2 else out.getvalue())

    def test_flips_in_projected_mode_and_payload_and_excluded_payload(self):
        self.assertTrue(self.run_cli(0)["origin_match"])
        for index in (0, 2, 32, 1, 31):
            with self.subTest(index=index):
                words = self.words.copy()
                word = bytearray(words[57])
                word[index] ^= 1
                words[57] = bytes(word)
                self.write_words(words)
                included = index in DIRECT
                result = self.run_cli(1 if included else 0)
                self.assertEqual(result["by_position"]["2"]["match"], not included)
                self.assertTrue(all(result["by_position"][p]["match"] for p in ("1", "3", "4")))

    def test_shared_rotation_and_wrong_origin(self):
        origin = (123, 0, 0, 1)
        self.write_words(self.words[4:] + self.words[:4])
        duplicate = self.export.with_suffix(".copy")
        duplicate.write_bytes(self.export.read_bytes())
        score = compare_group(self.export, duplicate, counter=123, candidate_start=origin, reference_start=origin)
        self.assertTrue(score["group_exact"])
        self.assertFalse(any(row["match"] for row in self.run_cli(1)["by_position"].values()))

        self.write_words([bytes(33)] + self.words)
        self.assertTrue(self.run_cli(0, ("122", "2", "4", "4"))["origin_match"])
        result = self.run_cli(1)
        self.assertTrue(all(row["supplied"] == 15 and not row["match"] for row in result["by_position"].values()))

    def test_erasures_and_outside_extent_remain_distinct(self):
        words = self.words[:-1]
        words[7] = b""
        self.write_words(words)
        row = self.run_cli(1)["by_position"]["4"]
        self.assertEqual((row["supplied"], row["erased"], row["outside_extent"]), (13, 1, 1))
        self.assertIsNone(row["projected_sha256"])
        self.assertFalse(row["match"])

    def test_target_digest_and_counter_must_both_match(self):
        self.target.write_bytes(self.target.read_bytes() + b"\n")
        self.assertIn("SHA-256", self.run_cli(2)["error"])
        receipt = dict(self.witness, target_sha256=sha256(self.target.read_bytes()).hexdigest(), counter=124)
        self.receipt.write_text(json.dumps(receipt))
        self.assertIn("counter", self.run_cli(2)["error"])

    def test_rejects_malformed_receipt_target_and_export(self):
        for updates in ({"position_sha256": ["1" * 64] * 3}, {"position_sha256": ["1" * 65] * 4},
                        {"target_sha256": "g" * 64}, {"unknown": 7}, {"counter": True}):
            with self.subTest(updates=updates):
                self.receipt.write_text(json.dumps(dict(self.witness, **updates)))
                self.run_cli(2)
        self.receipt.write_text(json.dumps(self.witness))
        self.export.write_bytes(self.export.read_bytes() + b"\x04")
        self.run_cli(2)
        self.target.write_text("[]")
        self.receipt.write_text(json.dumps(dict(self.witness, target_sha256=sha256(b"[]").hexdigest())))
        self.assertIn("target", self.run_cli(2)["error"])


if __name__ == "__main__":
    unittest.main()
