"""Source binding and partial-packet regression tests for measured EVS replay."""
from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import wave

import numpy as np

from render_measured_evs import collect, coverage, measured_groups, render
from tail_fill_audit import crc


class MeasuredReplayTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.counter = 1234
        self.traffic = np.arange(3 * 716, dtype=np.int32).astype("u1").reshape(3, 716)
        self.flags = np.ones((3, 4), bool)
        self.key = np.arange(16, dtype="u1")
        self.traffic[0, 664:668] = np.frombuffer(self.counter.to_bytes(4, "big"), "u1")
        for phase, unit in enumerate(self.traffic):
            unit[1] = phase << 4
            unit[-2:] = np.frombuffer(crc(unit[:-2]).to_bytes(2, "big"), "u1")
        self.mask = bytes(range(21, 32))
        np.savez(self.root / "keys.npz", counters=np.array([self.counter], dtype="u4"),
                 ks=self.key[None], crc_supported=np.ones((1, 16), bool))

    def manifest(self):
        return measured_groups({"groups": {str(self.counter): {
            "du_sha256": [sha256(unit.tobytes()).hexdigest() for unit in self.traffic],
            "masks": {"2": self.mask.hex(), "4": self.mask.hex()},
        }}})

    def replay(self, groups):
        ticks = self.counter * 3 + np.arange(3)
        np.savez(self.root / "packets.npz", ticks=ticks, packets=self.traffic.reshape(3, 4, 179),
                 packet_ok=self.flags)
        return collect(self.root, groups)

    def test_masks_leave_mode_and_clear_bytes_intact(self):
        words, kinds, report = self.replay(self.manifest())
        self.assertEqual(coverage(kinds)["frames_by_position"], {"1": 15, "2": 15, "3": 0, "4": 15})
        for slot, begin in [(1, 39), (3, 105)]:
            expected = self.traffic[0, begin:begin + 33].copy()
            expected[1::3] ^= np.frombuffer(self.mask, "u1")
            np.testing.assert_array_equal(words[slot], expected)
        self.assertEqual(report["applied_group_positions"], {self.counter: [2, 4]})

    def test_valid_other_source_crc_rejected_by_sha(self):
        groups = self.manifest()
        self.traffic[2, 111] ^= 1
        self.traffic[2, -2:] = np.frombuffer(crc(self.traffic[2, :-2]).to_bytes(2, "big"), "u1")
        _, kinds, report = self.replay(groups)
        self.assertEqual(coverage(kinds)["inferred"], 0)
        self.assertEqual(report["skipped_in_range_groups"][self.counter], "phase 2 SHA-256 mismatch")

    def test_matching_hash_does_not_override_bad_du_crc(self):
        self.traffic[1, 100] ^= 1
        _, kinds, report = self.replay(self.manifest())
        self.assertEqual(coverage(kinds)["inferred"], 0)
        self.assertEqual(report["skipped_in_range_groups"][self.counter], "phase 1 CRC mismatch")

    def test_partial_group_preserves_individually_received_first_position(self):
        self.flags[2, 0] = False
        _, kinds, report = self.replay(self.manifest())
        self.assertEqual(coverage(kinds)["established"], 10)
        self.assertEqual(coverage(kinds)["inferred"], 0)
        self.assertEqual(report["skipped_in_range_groups"][self.counter], "phase 2 incomplete")

    def test_measured_first_and_partial_phase_binding(self):
        doc = {"groups": {str(self.counter): {
            "du_sha256": [sha256(self.traffic[0].tobytes()).hexdigest(), None, None],
            "masks": {"1": self.mask.hex()},
        }}}
        groups = measured_groups(doc)
        _, kinds, _ = self.replay(groups)
        self.assertEqual(coverage(kinds)["established"], 15)
        self.assertEqual(coverage(kinds)["inferred"], 0)
        np.savez(self.root / "keys.npz", counters=np.array([self.counter], dtype="u4"),
                 ks=self.key[None], crc_supported=np.zeros((1, 16), bool))
        _, kinds, _ = self.replay(groups)
        self.assertEqual(coverage(kinds)["inferred_first_position"], 5)
        self.assertEqual(coverage(kinds)["frames_by_position"]["1"], 5)
        self.assertEqual(coverage(kinds)["established"], 0)
        self.assertFalse(kinds[20:].any())

    def test_received_span_keeps_interior_gap_and_crops_counter_excerpt(self):
        # Two received phases with an unreceived phase between them.
        ticks = 3 * self.counter + np.array([2, 4])
        np.savez(self.root / "packets.npz", ticks=ticks,
                 packets=self.traffic[[2, 1]].reshape(2, 4, 179), packet_ok=self.flags[[2, 1]])
        manifest = self.root / "manifest.json"
        manifest.write_text(json.dumps({"groups": {}}))
        pcms = np.arange(60, dtype="<i2").repeat(320)

        def decode(args, **kwargs):
            Path(args[-1]).write_bytes(pcms.tobytes())

        with patch("render_measured_evs.linux_command", side_effect=lambda *args: args), \
             patch("render_measured_evs.subprocess.run", side_effect=decode):
            report = render(self.root, manifest, self.root, "decoder", (self.counter + 1, self.counter + 1), True)
        self.assertEqual((report["total_slots"], report["established"], report["erased"]), (60, 5, 55))
        self.assertEqual(report["excerpt"]["total_slots"], 40)
        with wave.open(str(self.root / "excerpt.wav"), "rb") as stream:
            self.assertEqual(stream.readframes(stream.getnframes()), pcms[20 * 320:].tobytes())


if __name__ == "__main__":
    unittest.main()
