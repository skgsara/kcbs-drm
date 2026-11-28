"""The 12:32 replay must detect an incorrect packet-overlap or primary peer receipt."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


CASE = Path(__file__).resolve().parents[1] / "examples/nov28/same-6140-1232"


class SameCarrierReceiptTest(unittest.TestCase):
    def test_overlap_is_recomputed_from_stations(self):
        with tempfile.TemporaryDirectory() as temp:
            work = Path(temp)
            for pattern in ("*.json", "*.npz", "*.csv", "*.json.gz"):
                for path in CASE.glob(pattern):
                    shutil.copyfile(path, work / path.name)
            command = [sys.executable, str(CASE / "check.py"), "--case", str(work)]
            baseline = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(baseline.returncode, 0, baseline.stderr)
            receipt = work / "comparison.json"
            original = receipt.read_text()
            for section, field in (("comparison_packets", "exact_matches"), ("primary_peer_receipt", "equal_dus")):
                with self.subTest(section=section, field=field):
                    changed = json.loads(original)
                    changed[section][field] -= 1
                    receipt.write_text(json.dumps(changed))
                    replay = subprocess.run(command, capture_output=True, text=True)
                    self.assertNotEqual(replay.returncode, 0, "inconsistent receipt accepted")


if __name__ == "__main__":
    unittest.main()
