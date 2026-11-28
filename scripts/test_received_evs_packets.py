"""Packet-snapshot provenance checks with unavailable bytes left poisoned."""
from binascii import crc_hqx
from pathlib import Path
import tempfile
import unittest
from zipfile import ZipFile

import numpy as np

from received_evs_packets import read_packet_snapshot


def inputs():
    # The middle phase-zero row has packet 3 but lacks packet 0.
    ticks = np.array([0, 3, 4, 3 * 0xffffffff + 2], dtype=np.uint64)
    flags = np.array([[0, 0, 0, 0], [0, 0, 0, 1], [1, 0, 1, 0], [1, 1, 1, 1]], dtype=bool)
    packets = np.full((4, 4, 179), 0xff, dtype=np.uint8)
    units = packets.reshape(4, 716)
    units[1, 664:668] = [0, 0, 0, 1]
    units[2, 1] = 0x1f
    units[3, 1] = 0x2f
    units[3, 714:] = list((crc_hqx(units[3, :714].tobytes(), 0xffff) ^ 0xffff).to_bytes(2, "big"))
    return dict(ticks=ticks, packets=packets, packet_ok=flags)


class PacketSnapshotTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / "packets.npz"

    def save(self, arrays):
        np.savez(self.path, **arrays)

    def test_preserves_partial_missing_complete_and_empty(self):
        arrays = inputs()
        self.save(arrays)
        ticks, units, flags = read_packet_snapshot(self.path)
        self.assertEqual(ticks.dtype, np.int64)
        np.testing.assert_array_equal(ticks, arrays["ticks"])
        np.testing.assert_array_equal(units, arrays["packets"].reshape(4, 716))
        np.testing.assert_array_equal(flags, arrays["packet_ok"])
        self.save({name: a[:0] for name, a in arrays.items()})
        self.assertEqual([a.shape for a in read_packet_snapshot(self.path)], [(0,), (0, 716), (0, 4)])

    def test_checks_only_observed_fields_and_complete_crc(self):
        for row, offset, error in [(1, 667, "counter"), (2, 1, "phase"), (3, 180, "CRC")]:
            with self.subTest(error=error):
                arrays = inputs()
                arrays["packets"].reshape(4, 716)[row, offset] ^= 0x10
                self.save(arrays)
                with self.assertRaisesRegex(ValueError, error):
                    read_packet_snapshot(self.path)

    def test_shapes_types_range_and_order(self):
        maximum = 3 * 0xffffffff + 2
        for key, bad in [
            ("ticks", [-1, 3, 4, 5]), ("ticks", np.array([0, 3, 4, maximum + 1], np.uint64)),
            ("ticks", [0, 3, 3, 4]), ("ticks", [0, 4, 3, 5]), ("ticks", [0., 3., 4., 5.]),
            ("ticks", [[0, 3, 4, 5]]), ("ticks", np.array([0, 3, 4, 5], dtype=object)),
            ("packets", np.zeros((4, 716), np.uint8)), ("packets", np.zeros((4, 4, 179), np.int8)),
            ("packet_ok", np.zeros((3, 4), bool)), ("packet_ok", np.zeros((4, 4), np.uint8)),
        ]:
            with self.subTest(key=key, shape=np.shape(bad), dtype=np.asarray(bad).dtype):
                self.save(inputs() | {key: bad})
                with self.assertRaises(ValueError):
                    read_packet_snapshot(self.path)

    def test_rejects_missing_duplicate_and_malformed_arrays(self):
        arrays = inputs()
        self.save({k: v for k, v in arrays.items() if k != "packet_ok"})
        with self.assertRaises(ValueError):
            read_packet_snapshot(self.path)
        self.save(arrays | {"metadata": [1]})
        np.testing.assert_array_equal(read_packet_snapshot(self.path)[2], arrays["packet_ok"])
        self.save(arrays)
        with ZipFile(self.path, "a") as archive:
            with self.assertWarns(UserWarning):
                archive.writestr("ticks.npy", archive.read("ticks.npy"))
        with self.assertRaisesRegex(ValueError, "duplicate"):
            read_packet_snapshot(self.path)
        with ZipFile(self.path, "w") as archive:
            for key in arrays:
                archive.writestr(key + ".npy", b"not a NumPy array")
        with self.assertRaises(ValueError):
            read_packet_snapshot(self.path)
        with self.path.open("wb") as fp:
            np.save(fp, np.arange(4))
        with self.assertRaises(ValueError):
            read_packet_snapshot(self.path)

    def test_rejects_noncanonical_stored_receipt_flag(self):
        arrays = inputs()
        arrays["packet_ok"].view(np.uint8)[0, 1] = 2
        self.save(arrays)
        with self.assertRaisesRegex(ValueError, "0 or 1"):
            read_packet_snapshot(self.path)


if __name__ == "__main__":
    unittest.main()
