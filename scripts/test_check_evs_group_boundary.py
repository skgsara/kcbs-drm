"""Controls for the directly observed HQ flag between adjacent counter groups."""
from binascii import crc_hqx
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import numpy as np

from check_evs_group_boundary import check_boundaries


def unit(counter, phase, mode):
    row = bytearray(716)
    row[1] = phase << 4
    if phase == 0:
        row[2] = mode
        row[664:668] = counter.to_bytes(4, "big")
    elif phase == 2:
        row[629] = mode
    row[-2:] = (crc_hqx(row[:-2], 0xffff) ^ 0xffff).to_bytes(2, "big")
    return bytes(row)


class HQBoundaries(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.path = Path(scratch.name) / "input.npz"

    def units(self, rows):
        np.savez(self.path, counters=np.array([c for c, _, _ in rows], np.uint32),
                 phases=np.array([p for _, p, _ in rows], np.uint8),
                 du=np.frombuffer(b"".join(unit(*r) for r in rows), np.uint8).reshape(-1, 716))

    def packets(self, rows, flags):
        np.savez(self.path, ticks=np.array([3 * c + p for c, p, _ in rows], np.int64),
                 packets=np.frombuffer(b"".join(unit(*r) for r in rows), np.uint8).reshape(-1, 4, 179),
                 packet_ok=np.array(flags, bool).reshape(-1, 4))

    def test_flip_target_keeps_selection_and_prediction(self):
        for previous, predicted in [(0x50, 1), (0xf8, 0)]:
            reports = []
            for target in (0, 1):
                self.units([(103, 0, 0xf8 | target << 1), (102, 2, previous)])
                report = check_boundaries(self.path, counter=103)
                row, = report["rows"]
                self.assertEqual((row["left"], row["right"]), ([102, 2, 4, 4], [103, 0, 0, 1]))
                self.assertEqual((row["allowed_values"], row["rejected_values"]), ([predicted], [1 - predicted]))
                self.assertEqual(row["observed"], target)
                self.assertEqual(row["outcome"], "match" if target == predicted else "mismatch")
                reports.append(report)
            self.assertEqual(reports[0]["selection_sha256"], reports[1]["selection_sha256"])
            self.assertNotEqual(reports[0]["input_sha256"], reports[1]["input_sha256"])

    def test_missing_phase_holes_uncertain_modes_and_no_wrap(self):
        rows = [(0xffffffff, 2, 0x52), (5, 0, 0xfa), (3, 2, 0x52), (0, 0, 0xf8),
                (5, 2, 21 << 3), (6, 0, 0xfa), (6, 2, 0xf8), (7, 0, 0xfc)]
        self.units(rows)
        report = check_boundaries(self.path)
        self.assertEqual([r["counter"] for r in report["rows"]], sorted({c for c, _, _ in rows}))
        reasons = {r["counter"]: r["reason"] for r in report["rows"]}
        self.assertEqual(reasons[0], "counter_zero_has_no_predecessor")
        self.assertEqual(reasons[5], "previous_mode_unavailable")
        self.assertEqual(reasons[6], "previous_signalling_index_outside_scope")
        self.assertEqual(reasons[7], "current_mode_is_not_hq")
        self.assertEqual(reasons[3], "current_mode_unavailable")
        self.assertEqual(report["eligible"], 0)
        self.assertEqual(check_boundaries(self.path, counter=8)["rows"][0]["outcome"], "abstain")

    def test_partial_packets_require_only_the_two_endpoint_quarters(self):
        rows = [(111, 2, 0x51), (112, 0, 0xfa)]
        flags = [[False, False, False, True], [True, False, False, False]]
        self.packets(rows, flags)
        cmd = [sys.executable, "-B", Path(__file__).with_name("check_evs_group_boundary.py"),
               "--packets", self.path, "--counter", "112"]
        good = json.loads(subprocess.check_output(cmd))
        self.assertEqual(good["counts"], {"match": 1, "mismatch": 0, "abstain": 0})
        for i, reason in [(0, "previous_mode_unavailable"), (1, "current_mode_unavailable")]:
            partial = [f[:] for f in flags]
            partial[i] = [False, True, False, False]
            self.packets(rows, partial)
            first = check_boundaries(self.path, packets=True, counter=112)
            junk = list(rows)
            c, p, _ = junk[i]
            junk[i] = (c, p, 0xff)
            self.packets(junk, partial)
            second = check_boundaries(self.path, packets=True, counter=112)
            self.assertEqual(first["rows"], second["rows"])
            self.assertEqual(second["rows"][0]["reason"], reason)
            self.assertIsNone(second["rows"][0]["observed"])
        with self.assertRaises(ValueError):
            check_boundaries(self.path)  # A packet snapshot cannot be claimed as whole-DU evidence.

    def test_corrupt_full_du_and_invalid_flagged_phase_fail_closed(self):
        self.units([(111, 2, 0x50), (112, 0, 0xfa)])
        with np.load(self.path) as a:
            arrays = dict(a)
        arrays["du"] = arrays["du"].copy()
        arrays["du"][0, 629] ^= 1
        np.savez(self.path, **arrays)
        with self.assertRaisesRegex(ValueError, "CRC"):
            check_boundaries(self.path, counter=112)
        self.packets([(111, 2, 0x50), (112, 0, 0xfa)], [[False, False, False, True], [True, False, False, False]])
        with np.load(self.path) as a:
            arrays = dict(a)
        arrays["packets"] = arrays["packets"].copy()
        arrays["packets"][1, 0, 1] = 0x10
        np.savez(self.path, **arrays)
        with self.assertRaisesRegex(ValueError, "phase"):
            check_boundaries(self.path, packets=True, counter=112)


if __name__ == "__main__":
    unittest.main()
