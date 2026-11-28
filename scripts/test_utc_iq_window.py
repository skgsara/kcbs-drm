"""UTC cuts on recorder samples, including sub-packet boundaries and backward clocks."""
import csv
from pathlib import Path
import sys
import tempfile
import unittest
import wave


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "examples/nov28/yokohama-1300"))
from window_bounds import HEADER, NS, RATE, bounds, utc_ns


class UTCWindowTest(unittest.TestCase):
    def make_case(self, root, rows, pairs):
        wav = root / "iq.wav"
        with wave.open(str(wav), "wb") as stream:
            stream.setparams((2, 2, RATE, pairs, "NONE", "not compressed"))
            stream.writeframes(bytes(4 * pairs))
        timing = root / "iq.timing.csv"
        with timing.open("w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(HEADER)
            writer.writerows(rows)
        return wav, timing

    def test_blank_and_subpacket_endpoints(self):
        with tempfile.TemporaryDirectory() as temp:
            paths = self.make_case(Path(temp), [(0, 7, ""), (7, 48, NS)], 55)
            report = bounds(*paths, NS + 1, NS + 62500)
            self.assertEqual(report["single_direct_range"], [8, 10])
            self.assertEqual(report["blank_time_ranges"][0]["samples"], [0, 7])
            self.assertEqual(report["utc_boundaries"]["end_exclusive"]["in_packets"][0]["first_sample_at_or_after"], 10)
            self.assertEqual(utc_ns("1970-01-01T00:00:01.000000001Z"), NS + 1)

    def test_two_samples_in_a_backward_step(self):
        with tempfile.TemporaryDirectory() as temp:
            paths = self.make_case(Path(temp), [(0, 48, NS), (48, 48, NS + 978664)], 96)
            report = bounds(*paths, NS + 978500, NS + 979500)
            self.assertEqual([r["samples"] for r in report["directly_timed_in_window_ranges"]], [[47, 48], [48, 49]])
            self.assertIsNone(report["single_direct_range"])
            self.assertEqual(report["clock_steps"][0]["signed_jump_ns"], -21336)

    def test_missing_csv_rows(self):
        with tempfile.TemporaryDirectory() as temp:
            paths = self.make_case(Path(temp), [(0, 48, NS)], 96)
            with self.assertRaisesRegex(ValueError, "covers 48 pairs"):
                bounds(*paths, NS, 2 * NS)


if __name__ == "__main__":
    unittest.main()
