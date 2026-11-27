"""Check that public group projections expose only directly witnessed clear octets."""
from binascii import crc_hqx
import csv
from io import StringIO
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import numpy as np

from project_evs_group import project_group


COUNTER = 0x01020304


def finish(unit):
    unit[-2:] = (crc_hqx(unit[:-2], 0xffff) ^ 0xffff).to_bytes(2, "big")
    return unit


def fixture(phase):
    unit = bytearray(716)
    unit[1] = phase << 4
    if phase == 0:
        unit[664:668] = COUNTER.to_bytes(4, "big")
    cursor = 7
    words = []
    for cycle in range(5):
        for role in range(4):
            slot = phase * 20 + cycle * 4 + role
            word = bytes((slot + 17 * i) % 256 for i in range(33))
            if role == 0:
                unit[2 + cycle] = word[0]
            else:
                unit[cursor] = word[0]
                cursor += 1
            unit[cursor:cursor + 32] = word[1:]
            cursor += 32
            words.append(word)
    return finish(unit), words


class ProjectionTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "data_units.npz"

    def save(self, phases):
        dus = [list(fixture(p)[0]) for p in phases]
        np.savez(self.path, counters=np.full(len(dus), COUNTER, np.uint32), phases=np.array(phases, np.uint8),
                 du=np.array(dus, np.uint8).reshape(-1, 716))

    def test_exact_slot_geometry_and_visibility(self):
        self.save([2, 0, 1])
        result = project_group(self.path, COUNTER)
        self.assertEqual(result["received_du_phases"], [0, 1, 2])
        self.assertEqual((result["physically_complete_slots"], result["confirmed_direct_bits"],
                          result["full_clear_words"], result["word_erasures"]), (60, 10560, 0, 60))
        expected = [word for phase in range(3) for word in fixture(phase)[1]]
        for slot, (row, word) in enumerate(zip(result["slots"], expected, strict=True)):
            self.assertEqual((row["slot"], row["phase"], row["cycle"], row["position"]),
                             (slot, slot // 20, slot % 20 // 4, slot % 4 + 1))
            self.assertEqual(row["octets"].split(), [
                "??" if j % 3 == 1 else f"{v:02x}" for j, v in enumerate(word)])
        self.assertEqual(result["slots"][3]["octets"].split()[31], "??")

    def test_missing_phases_empty_archive_and_tsv_agree(self):
        self.save([1])
        command = [sys.executable, "-B", str(Path(__file__).with_name("project_evs_group.py")),
                   str(self.path), "--counter", str(COUNTER)]
        result = json.loads(subprocess.check_output(command))
        tsv = subprocess.check_output([*command, "--format", "tsv"], text=True)
        lines = list(csv.DictReader(StringIO(tsv), delimiter="\t"))
        self.assertEqual([r["octets"] for r in lines], [r["octets"] for r in result["slots"]])
        self.assertEqual((len(lines), result["confirmed_direct_bits"], result["missing_du_slots"]), (60, 3520, 40))
        self.assertEqual([r["receipt"] for r in lines], ["missing_du"] * 20 + ["received_du"] * 20 + ["missing_du"] * 20)
        self.assertEqual(lines[40]["octets"].split(), ["--"] * 33)
        self.assertEqual(project_group(self.path, COUNTER + 1)["confirmed_direct_bits"], 0)
        self.save([])
        self.assertEqual(project_group(self.path, COUNTER)["missing_du_slots"], 60)

    def test_rejects_damaged_or_mislabeled_source_rows(self):
        self.save([1, 1])
        with self.assertRaisesRegex(ValueError, "duplicate"):
            project_group(self.path, COUNTER)
        for kind in ("crc", "phase", "phase-zero counter", "other group's crc", "short DU", "metadata"):
            with self.subTest(kind=kind):
                row = fixture(0)[0]
                source_counter = COUNTER
                if kind in ("crc", "other group's crc"):
                    row[100] ^= 1
                    if kind == "other group's crc":
                        source_counter += 1
                elif kind == "phase":
                    row[1] = 16
                    finish(row)
                elif kind == "phase-zero counter":
                    source_counter += 1
                elif kind == "short DU":
                    row.pop()
                phases = np.array([0.0] if kind == "metadata" else [0])
                np.savez(self.path, counters=[source_counter], phases=phases, du=[np.frombuffer(row, np.uint8)])
                with self.assertRaises(ValueError):
                    project_group(self.path, COUNTER)
        with self.assertRaisesRegex(ValueError, "unsigned"):
            project_group(self.path, 2**32)


if __name__ == "__main__":
    unittest.main()
