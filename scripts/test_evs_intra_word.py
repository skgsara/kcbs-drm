"""Exercise SWB HQ class predictions through the CRC-checked receiver projection."""
from binascii import crc_hqx
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import numpy as np

from evs_intra_word import intra_word
from render_continuous import MODE_POSITIONS, PACKET_STARTS


class HQClassTests(unittest.TestCase):
    def test_receiver_keeps_class_constraints_separate_from_received_octets(self):
        counter = 17
        units = []
        for phase, modes in [(0, [0xF9, 0xFA, 0xF8, 0xFB]), (2, [0xFC, 0xFA])]:
            unit = bytearray(716)
            unit[1] = phase << 4
            if phase == 0:
                unit[664:668] = counter.to_bytes(4, "big")
            for i, mode in enumerate(modes):
                unit[MODE_POSITIONS[i]] = mode
                unit[PACKET_STARTS[i]] = 0xff  # Protected octet, inaccessible to the predictor.
            unit[-2:] = (crc_hqx(unit[:-2], 0xffff) ^ 0xffff).to_bytes(2, "big")
            units.append(np.frombuffer(unit, dtype=np.uint8))
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "data_units.npz"
            np.savez(archive, counters=[counter, counter], phases=[0, 2], du=units)
            command = [sys.executable, "-B", str(Path(__file__).with_name("project_evs_group.py")),
                       str(archive), "--counter", str(counter)]
            plain = json.loads(subprocess.check_output(command))
            checked = json.loads(subprocess.check_output([*command, "--field-checks"]))
        for field, value in plain.items():
            self.assertEqual(checked[field], value)
        self.assertEqual((checked["confirmed_direct_bits"], checked["missing_du_slots"], checked["word_erasures"]),
                         (7040, 20, 60))
        fields = checked["intra_word"]
        self.assertEqual([(r["slot"], r["word_bits"], r["allowed"]) for r in fields["slots"]],
                         [(0, [8, 9], [0, 0]), (1, [8, 10], [0, 2]),
                          (3, [8, 10], [0, 2]), (41, [8, 10], [0, 2])])
        for r in fields["slots"]:
            self.assertEqual((r["check"], r["outcome"], r["observed"]), ("swb_hq_class", "conditional", None))
            self.assertEqual(checked["slots"][r["slot"]]["octets"].split()[1], "??")
        self.assertEqual(fields["by_check"]["swb_hq_class"]["conditional"], 4)

    def test_unknown_mode_and_missing_receipt_have_no_class_restriction(self):
        for mode, receipt in (("??", "received_du"), ("--", "missing_du"), ("fb", "fill")):
            slot = dict(slot=0, counter=3, phase=0, cycle=0, position=1, receipt=receipt, octets=mode)
            with self.subTest(mode=mode, receipt=receipt):
                self.assertEqual(intra_word([slot])["slots"], [])


if __name__ == "__main__":
    unittest.main()
