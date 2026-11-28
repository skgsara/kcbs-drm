import json
from pathlib import Path
import struct
from tempfile import TemporaryDirectory
import unittest

from drm_row_alignment import parse_msc, read_msc, valid_packets, witnessed_pairs
from salvage_msc_packets import PACKET_HEADERS, crc


def wire(q, value):
    packet = bytes([PACKET_HEADERS[q]]) + bytes([value]) * 179
    return packet + crc(packet).to_bytes(2, "big")


def row(*packets):
    quarters = [bytes(182)] * 4
    for q, value in packets:
        quarters[q] = wire(q, value)
    return b"".join(quarters)


class AlignmentTests(unittest.TestCase):
    def test_framing_retains_unsupported_rows_and_bounds(self):
        rows = [row((2, 94)), b"short", row((0, 31))]
        framed = b"".join(struct.pack("<I", len(data)) + data for data in rows)
        self.assertEqual(parse_msc(b""), [])
        self.assertEqual(parse_msc(framed), rows)
        with TemporaryDirectory() as directory:
            path = Path(directory) / "msc.bin"
            path.write_bytes(framed)
            self.assertEqual(read_msc(path), rows)
        for bad in (framed + b"\0", framed[:-1], struct.pack("<I", 0), struct.pack("<I", 1048577)):
            with self.subTest(bad=bad[-4:]), self.assertRaises(ValueError):
                parse_msc(bad)

    def test_only_actual_witnesses_across_variable_row_offsets(self):
        left = [row((0, 1), (1, 9)), row((3, 5)), row((3, 11)), row((1, 7))]
        right = [b"x", row((0, 1), (2, 4)), row((2, 5)), row((1, 7))]
        pairs, stats = witnessed_pairs(left, right)
        self.assertEqual(pairs, [(0, 1), (3, 3)])
        self.assertEqual(stats["accepted_witnesses"], 2)
        self.assertEqual(stats["right"]["unsupported_rows"], 1)
        self.assertEqual(json.loads(json.dumps(stats)), stats)

    def test_crc_header_and_ordinal(self):
        good = wire(1, 19)
        bad_crc = good[:-1] + bytes([good[-1] ^ 1])
        left = row((1, 19))
        for bad in (bad_crc, wire(2, 19)):
            wrong = bytes(182) + bad + bytes(364)
            self.assertEqual(valid_packets(wrong), {})
            self.assertEqual(witnessed_pairs([left], [wrong])[0], [])
        self.assertEqual(valid_packets(left), {1: good})
        self.assertEqual(valid_packets(left[:-1]), {})

    def test_nonunique_wires_cannot_supply_witness(self):
        repeated = row((1, 3))
        both = row((1, 3), (2, 9))
        pairs, stats = witnessed_pairs([repeated, repeated, both], [both])
        self.assertEqual(pairs, [(2, 0)])
        self.assertEqual(stats["nonunique_shared_wires"], 1)
        self.assertEqual(stats["accepted_witnesses"], 1)
        self.assertEqual(witnessed_pairs([repeated], [repeated, repeated])[0], [])

    def test_ambiguous_partner_rejected_in_both_directions(self):
        # Two witnesses for one partner cannot override a third for another.
        left = [row((0, 1), (1, 2), (2, 3))]
        right = [row((0, 1), (1, 2)), row((2, 3))]
        for a, b in ((left, right), (right, left)):
            pairs, stats = witnessed_pairs(a, b)
            self.assertEqual(pairs, [])
            self.assertEqual(stats["rejection_reasons"], {"ambiguous_partner": 2})

    def test_joint_crc_valid_packet_conflict(self):
        left = [row((0, 1), (1, 2), (2, 3)), row((0, 4))]
        right = [row((0, 1), (1, 2), (2, 5)), row((0, 4))]
        pairs, stats = witnessed_pairs(left, right)
        self.assertEqual(pairs, [(1, 1)])
        self.assertEqual(stats["rejections"], [dict(left=0, right=0, reasons=["conflicting_packet"])])

    def test_all_participants_in_crossed_order_rejected(self):
        left = [row((0, n)) for n in range(6)]
        right = [left[n] for n in (0, 4, 1, 2, 3, 5)]
        pairs, stats = witnessed_pairs(left, right)
        self.assertEqual(pairs, [(0, 0), (5, 5)])
        self.assertEqual(stats["rejection_reasons"], {"crossed_order": 4})

    def test_public_development_pair_list(self):
        case = Path(__file__).resolve().parents[1] / "examples/nov28/same-6140-1232"
        saved = json.loads((case / "diversity/alignment/row-pairs.json").read_bytes())
        expected = [(r["edogawa_row"], r["yokohama_row"]) for r in saved]
        pairs, stats = witnessed_pairs(read_msc(case / "edogawa-msc.bin"), read_msc(case / "yokohama-msc.bin"))
        self.assertEqual(pairs, expected)
        self.assertEqual((len(pairs), stats["accepted_witnesses"]), (135, 444))

    def test_public_weak_pair_abstains(self):
        case = Path(__file__).resolve().parents[1] / "examples/nov28/edogawa-audio-branch/results"
        pairs, stats = witnessed_pairs(read_msc(case / "edogawa/msc.bin"), read_msc(case / "yokohama/msc.bin"))
        self.assertEqual(pairs, [])
        self.assertEqual((stats["left"]["valid_packets"], stats["right"]["valid_packets"]), (26, 0))


if __name__ == "__main__":
    unittest.main()
