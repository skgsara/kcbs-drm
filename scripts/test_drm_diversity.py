from pathlib import Path
import struct
import sys
from tempfile import TemporaryDirectory
import unittest

import numpy as np

from drm_diversity import compare, map_blocks, resolve_row, unsupported
from drm_msc_cells import Block, combine, read_blocks
from drm_row_alignment import parse_msc
from salvage_msc_packets import PACKET_HEADERS, crc


def with_crc(body):
    return body + crc(body).to_bytes(2, "big")


def native(seed):
    unit = with_crc(bytes((i + seed) % 256 for i in range(714)))
    return b"".join(with_crc(bytes([h]) + unit[q * 179:(q + 1) * 179])
                    for q, h in enumerate(PACKET_HEADERS))


def lose(row, *ordinals):
    changed = bytearray(row)
    for ordinal in ordinals:
        changed[182 * ordinal + 181] ^= 1
    return bytes(changed)


def alter(row, ordinal, byte_index):
    start = 182 * ordinal
    packet = bytearray(row[start:start + 180])
    packet[byte_index] ^= 1
    return row[:start] + with_crc(bytes(packet)) + row[start + 182:]


def write_site(path, rows):
    path.mkdir()
    (path / "msc.bin").write_bytes(b"".join(struct.pack("<I", len(row)) + row for row in rows))
    (path / "cells.bin").write_bytes(b"MSCObs1\n")
    return path


def block(index, row, channel=1):
    header = [0] * 28
    header[0:6] = [index, 2, 5824, 1, 3, 1]
    header[12] = 2
    header[19] = 728
    header[26] = 2
    cells = np.array([[0, 1, channel], [1, 0, channel]], dtype=float)
    return Block(tuple(header), cells, row)


class DiversityTests(unittest.TestCase):
    def setUp(self):
        self.row = native(15)

    def test_peer_and_soft_additions_require_observed_bytes(self):
        left = lose(self.row, 0, 1)
        right = lose(self.row, 0, 2)
        hard, report = resolve_row(left, right, None)
        self.assertEqual(hard, lose(self.row, 0))
        self.assertEqual(report["peer_added"], [1])
        row, report = resolve_row(left, right, lose(self.row, 1))
        self.assertEqual(row, self.row)
        self.assertEqual(report["soft_added"], [0])
        self.assertFalse(report["soft_du"])
        self.assertFalse(report["union_du"])

    def test_no_soft_promotion_without_complete_du_checksum(self):
        left = lose(self.row, 0, 1)
        for candidate in (lose(self.row, 1), alter(self.row, 0, 55)):
            row, report = resolve_row(left, left, candidate)
            self.assertEqual(row, left)
            self.assertFalse(report["soft_added"])
        wrong_q0 = alter(lose(self.row, 1), 0, 55)
        row, report = resolve_row(lose(self.row, 0), left, wrong_q0)
        self.assertEqual(row, lose(self.row, 0))
        self.assertEqual(report["status"], "unconfirmed_soft_packets")

    def test_independent_conflict_blocks_pooling(self):
        left = lose(self.row, 0)
        right = alter(lose(self.row, 1), 3, 28)
        row, report = resolve_row(left, right, self.row)
        self.assertEqual(row, left)
        self.assertEqual(report["hard_conflict_ordinals"], [3])

    def test_contradictory_soft_validation_preserves_hard_pool(self):
        left = lose(self.row, 0, 1)
        right = lose(self.row, 0, 2)
        alternative = alter(lose(self.row, 2), 3, 15)
        row, report = resolve_row(left, right, alternative)
        self.assertEqual(row, lose(self.row, 0))
        self.assertEqual(report["soft_conflict_ordinals"], [3])
        self.assertFalse(report["soft_added"])

    def test_bad_row_integrity_barriers(self):
        left = lose(self.row, 0, 2)
        for right, reason in ((alter(self.row, 3, 25), "invalid_complete_du_crc"),
                              (alter(self.row, 1, 0), "crc_valid_wrong_header")):
            row, report = resolve_row(left, right, self.row)
            self.assertEqual(row, left)
            self.assertEqual(report["status"], reason)
        incoherent_left = alter(lose(self.row, 0), 2, 18)
        row, report = resolve_row(incoherent_left, lose(self.row, 2), self.row)
        self.assertEqual(row, incoherent_left)
        self.assertEqual(report["status"], "hard_union_du_crc_failed")

    def test_unaligned_chronology_and_empty_observer(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            left_rows = [b"barrier", native(8), lose(self.row, 3)]
            left = write_site(root / "left", left_rows)
            peer = write_site(root / "peer", [native(30), self.row])
            raw, report = compare(left, peer, Path(sys.executable))
            self.assertEqual(parse_msc(raw), [*left_rows[:2], self.row])
            self.assertEqual(report["status"], "hard_pool_only")
            self.assertEqual(report["coverage"]["peer_added_packets"], 1)
            self.assertEqual(report["coverage"]["new_complete_dus_from_hard_pool"], 1)
            self.assertEqual(report["soft_skip_reasons"], {"no_unique_native_to_soft_binding": 1})
            row = report["rows"][0]
            self.assertEqual((row["left_row"], row["right_row"]), (2, 1))
            for i, rows in enumerate(([], [native(44)])):
                raw, report = compare(left, write_site(root / str(i), rows), Path(sys.executable))
                self.assertEqual(parse_msc(raw), left_rows)
                self.assertEqual(report["status"], "no_witnessed_pairs")
                self.assertEqual(report["coverage"]["output_accepted_packets"], 7)

    def test_observer_binding_ambiguity_and_crossed_callback_order(self):
        rows = [self.row, native(7), native(8)]
        swapped = [block(i, rows[j]) for i, j in enumerate((1, 0, 2))]
        self.assertEqual(list(map_blocks(rows, swapped)), [2])
        self.assertEqual(map_blocks(rows * 2, swapped), {})
        self.assertEqual(map_blocks(rows[:1], [block(0, self.row), block(1, self.row)]), {})

    def test_observer_framing_and_missing_channel_support(self):
        observed = block(0, self.row)
        raw = b"MSCObs1\n" + struct.pack("<28i", *observed.header) + observed.cells.astype("<f8").tobytes() + self.row
        restored, = read_blocks(raw)
        self.assertEqual(restored.hard, self.row)
        np.testing.assert_equal(restored.cells, observed.cells)
        for bad in (raw[:-1], raw[:10], b"unrelated"):
            with self.assertRaises(ValueError):
                read_blocks(bad)
        self.assertEqual(unsupported(block(0, self.row, 0)), "no_usable_channel_cells")
        self.assertIsNone(unsupported(restored))
        np.testing.assert_allclose(combine(restored, restored, 0)[:, :2], observed.cells[:, :2])


if __name__ == "__main__":
    unittest.main()
