"""Compare independent DU receipts, including disagreements with valid checksums."""
from binascii import crc_hqx
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import numpy as np

from compare_dus import compare


def unit(c, p, value=0):
    row = bytearray(716)
    row[1] = p << 4
    row[10] = value
    if p == 0:
        row[664:668] = c.to_bytes(4, "big")
    row[-2:] = (crc_hqx(row[:-2], 0xffff) ^ 0xffff).to_bytes(2, "big")
    return bytes(row)


def save(path, rows):
    np.savez(path, counters=np.array([c for c, p, u in rows], np.uint32),
             phases=np.array([p for c, p, u in rows], np.uint8),
             du=np.frombuffer(b"".join(u for c, p, u in rows), np.uint8).reshape(-1, 716))


class DUComparison(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.left = Path(directory.name) / "left.npz"
        self.right = Path(directory.name) / "right.npz"

    def cli(self, *args):
        return subprocess.run([sys.executable, "-B", Path(__file__).with_name("compare_dus.py"),
                               self.left, self.right, *args], capture_output=True, text=True)

    def test_coordinate_join_and_full_bytes(self):
        # These identical phase-one units have different assigned counters. They cannot match.
        a, b = unit(4, 0), unit(4, 0, 1)
        shared = unit(4, 2)
        save(self.left, [(4, 2, shared), (4, 1, unit(4, 1)), (4, 0, a)])
        save(self.right, [(4, 0, b), (9, 1, unit(9, 1)), (4, 2, shared)])
        run = self.cli()
        self.assertEqual(run.returncode, 1)
        r = json.loads(run.stdout)
        self.assertEqual(r["compared_du_bytes"], 1432)
        self.assertEqual(r["bytes_in_matching_dus"], 716)
        self.assertEqual(r["matching_coordinates"], [[4, 2]])
        self.assertEqual(r["left_only_coordinates"], [[4, 1]])
        self.assertEqual(r["right_only_coordinates"], [[9, 1]])
        differing = [i for i in range(716) if a[i] != b[i]]
        self.assertIn(10, differing)
        self.assertEqual(r["disagreements"], [{"coordinate": [4, 0], "left_du_sha256": sha256(a).hexdigest(),
                         "right_du_sha256": sha256(b).hexdigest(), "differing_byte_offsets": differing}])
        self.assertEqual(r["equal_bytes_at_shared_coordinates"], 1432 - len(differing))
        self.assertEqual(r["left"]["archive_sha256"], sha256(self.left.read_bytes()).hexdigest())
        self.assertEqual(r["right"]["archive_sha256"], sha256(self.right.read_bytes()).hexdigest())

    def test_empty_overlap_and_positive_receipt(self):
        save(self.left, [(7, 0, unit(7, 0))])
        save(self.right, [])
        run = self.cli()
        self.assertEqual(run.returncode, 1)
        self.assertEqual(json.loads(run.stdout)["matching_dus"], 0)
        self.right.write_bytes(self.left.read_bytes())
        receipt = self.right.with_suffix(".json")
        self.assertEqual(self.cli("--out", receipt).returncode, 0)
        r = json.loads(receipt.read_text())
        self.assertTrue(r["same_archive_bytes"])
        self.assertEqual(r["matching_dus"], 1)
        self.assertEqual(self.cli("--out", receipt).returncode, 2)

    def test_rejects_corrupt_duplicate_or_misassigned_units_on_either_side(self):
        good = unit(7, 0)
        damaged = good[:10] + b"\x01" + good[11:]
        for bad in ([(7, 0, damaged)], [(7, 0, good)] * 2, [(8, 0, good)], [(7, 1, good)]):
            for first, second in [(self.left, self.right), (self.right, self.left)]:
                with self.subTest(bad_rows=len(bad), side=first.name):
                    save(first, bad)
                    save(second, [(7, 0, good)])
                    with self.assertRaises(ValueError):
                        compare(self.left, self.right)


if __name__ == "__main__":
    unittest.main()
