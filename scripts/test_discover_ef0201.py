"""Check the sparse authored-service native group catalog on synthetic native records."""
from binascii import crc_hqx
from pathlib import Path
import struct
import sys
import tempfile
import unittest

from compare_evs_group import read_words

CASE = Path(__file__).resolve().parents[1] / "examples/receiver-control"
sys.path.insert(0, str(CASE))
from discover import discover


def add_crc(data):
    return bytes(data) + (crc_hqx(data, 0xffff) ^ 0xffff).to_bytes(2, "big")


def row(counter, phase, *, guard=False, fill=7, stamp=None, bad_unit_crc=False):
    data = bytearray(714)
    data[1] = phase << 4
    if phase == 0:
        data[664:668] = counter.to_bytes(4, "big")
    if guard:
        data[668:672] = (counter if stamp is None else stamp).to_bytes(4, "big")
    else:
        data[2:662] = bytes([fill]) * 660
    unit = bytearray(add_crc(data))
    if bad_unit_crc:
        unit[715] ^= 1
    return b"".join(add_crc(bytes([h]) + unit[179*q:179*(q+1)]) for q, h in enumerate((128, 1, 2, 67)))


def group(c, **kwargs):
    return [row(c, p, **kwargs) for p in range(3)]


class NativeDiscoveryTests(unittest.TestCase):
    def run_rows(self, rows):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        msc = root / "input.msc"
        msc.write_bytes(b"".join(struct.pack("<I", len(r)) + r for r in rows))
        out = root / "groups"
        return discover(msc, out), out

    def test_native_order_jumps_wrap_duplicates_and_g192_files(self):
        # A genuine data group can use the numerical leading-guard range.
        counters = [0xffffffff, 0, 0x0f800000, 0x0f800000, 0x0f800000]
        rows = [r for c, fill in zip(counters, (4, 5, 6, 6, 8), strict=True) for r in group(c, fill=fill)]
        report, out = self.run_rows(rows)
        self.assertEqual([g["counter"] for g in report["groups"]], counters)
        self.assertEqual([g["run"] for g in report["groups"]], [0, 0, 1, 2, 3])
        self.assertEqual(report["repeated_counters"], [
            dict(counter=0x0f800000, native_starts=[6, 9, 12], identical_data_units=False)])
        files = [g["g192"] for g in report["groups"]]
        self.assertEqual(len(set(files)), 5)
        for name, fill in zip(files, (4, 5, 6, 6, 8), strict=True):
            self.assertEqual(list(read_words(out / name)), [bytes([fill]) * 33] * 60)

    def test_empty_catalog_and_equal_repeat(self):
        empty, out = self.run_rows([])
        self.assertEqual((empty["native_rows"], empty["groups"], list(out.glob("*.192"))), (0, [], []))
        with self.assertRaises(FileExistsError):
            discover(out.parent / "input.msc", out)
        report, _ = self.run_rows(group(52) * 2)
        self.assertEqual(report["repeated_counters"], [
            dict(counter=52, native_starts=[0, 3], identical_data_units=True)])

    def test_exact_guard_and_mixed_profile_data(self):
        # Guard matching uses structure and every body byte, at any counter value.
        rows = group(5, guard=True)
        rows.extend([row(6, 0, guard=True), row(6, 1, guard=True, stamp=7), row(6, 2, guard=True)])
        rows.extend([row(7, 0, guard=True), row(7, 1), row(7, 2, guard=True)])
        good_guard = group(8, guard=True)
        logical = bytearray(b"".join(good_guard[1][q*182+1:q*182+180] for q in range(4)))
        logical[700] = 1
        unit = add_crc(logical[:-2])
        good_guard[1] = b"".join(add_crc(bytes([h]) + unit[q*179:q*179+179]) for q,h in enumerate((128,1,2,67)))
        rows.extend(good_guard)
        report, out = self.run_rows(rows)
        self.assertEqual([g["kind"] for g in report["groups"]], ["guard"] + ["mixed_guard_quarantined"] * 3)
        self.assertEqual(report["groups"][1]["guard_stamps"], [6, 7, 6])
        self.assertEqual(list(out.glob("*.192")), [])

    def test_packet_du_barrier_and_partial_phase0(self):
        first = bytearray(row(2, 0))
        first[182 + 181] ^= 1  # Failed q1; canonical q0 and q3 still identify the P0 counter.
        malformed = bytearray(row(4, 1))
        malformed[182:364] = add_crc(bytes([2]) + malformed[183:362])  # q1 wrong header, valid CRC.
        rows = group(1) + [bytes(first), row(2, 1), row(2, 2)]
        rows += [row(3, 0), row(3, 1, bad_unit_crc=True), row(3, 2)]
        rows += [row(4, 0), bytes(malformed), row(4, 2)]
        rows += [row(5, 0), b"barrier", row(5, 1), row(5, 2)] + group(6)
        report, _ = self.run_rows(rows)
        self.assertEqual([g["counter"] for g in report["groups"]], [1, 6])
        self.assertEqual(report["groups"][1]["preceding_unselected_rows"], 13)
        rest = {r["native_row"]: r for r in report["unselected_rows"]}
        self.assertEqual((rest[3]["accepted_ordinals"], rest[3]["phase0_counter"]), ([0, 2, 3], 2))
        self.assertIsNone(rest[4]["phase0_counter"])
        self.assertEqual(rest[7]["status"], "failed_du_crc")
        self.assertEqual(rest[10]["status"], "unexpected_crc_valid_header")


if __name__ == "__main__":
    unittest.main()
