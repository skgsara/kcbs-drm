"""Mono EVS Primary storage input for the evidence comparator (TS 26.445 A.2.6)."""
import gzip
from pathlib import Path
import struct
import tempfile
import unittest

from compare_evs_group import compare_group, read_words


MAGIC = b"#!EVS_MC1.0\n"
MONO = MAGIC + b"\x00\x00\x00\x01"
WORD = bytes(range(33))


class EVSStorageTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "reference.bin"

    def read(self, data):
        self.path.write_bytes(data)
        return list(read_words(self.path))

    def test_storage_matches_g192_without_shifting_empty_slots(self):
        frame = bytes([4]) + WORD
        encoded = MONO + frame + b"\x0e\x0f" + frame
        g192 = struct.pack("<HH", 0x6b21, 264)
        g192 += b"".join(struct.pack("<H", 0x81 if byte & (1 << bit) else 0x7f)
                         for byte in WORD for bit in range(7, -1, -1))
        comparison = self.path.with_suffix(".192")
        comparison.write_bytes(g192 + struct.pack("<HH", 0x6b20, 0) * 2 + g192)
        for data in (encoded, gzip.compress(encoded)):
            with self.subTest(gzipped=data != encoded):
                self.assertEqual(self.read(data), [WORD, b"", b"", WORD])
                result = compare_group(comparison, self.path, counter=42,
                                       candidate_start=(42, 0, 0, 1), reference_start=(42, 0, 0, 1))
                self.assertEqual(result["by_position"]["1"]["match"], 1)
                self.assertEqual(result["by_position"]["4"]["match"], 1)
                self.assertEqual(result["by_position"]["2"]["both_erased"], 1)
                self.assertEqual(result["by_position"]["3"]["both_erased"], 1)

    def test_mime_validation(self):
        cases = [
            b"#!EVS_MC1.1\n" + bytes(4), b"#!AMR-WB\n", MAGIC[:-1], MAGIC + bytes(3),
            MAGIC + bytes(4), MAGIC + struct.pack("<I", 1), MAGIC + struct.pack(">I", 2),
            MONO + b"\x04" + bytes(32), gzip.compress(MONO + b"\x0e")[:-3],
        ]
        # ToC fields H/F, EVS mode and reserved bit, other rates, SID and future FT.
        cases.extend(MONO + bytes([toc]) + WORD for toc in (0x84, 0x44, 0x24, 0x14, 0x05, 0x0c, 0x0d))
        for data in cases:
            with self.subTest(data=data[:24]):
                with self.assertRaises(ValueError):
                    self.read(data)


if __name__ == "__main__":
    unittest.main()
