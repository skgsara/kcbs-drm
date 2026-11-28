"""Synthetic tests for the plaintext scrolling-text record parser."""

import unittest

from parse_text_records import (
    RecordError, crc, parse_record, replay_rows, scan_records,
)


def reference_crc(data):
    value = 0xFFFF
    for byte in data:
        value ^= byte << 8
        for _ in range(8):
            value = ((value << 1) ^ (0x1021 if value & 0x8000 else 0)) & 0xFFFF
    return value ^ 0xFFFF


def make_record(body, *, sequence=0, toggle=0, final=False):
    length = len(body)
    payload = bytes([(0x80 if toggle else 0) | (0x20 if final else 0) | (length >> 4),
                     (sequence << 4) | (length & 15)]) + body
    with_crc = payload + reference_crc(payload).to_bytes(2, "big")
    return with_crc + bytes(-len(with_crc) % 16) + (b"" if final else b"\xbb" * 16)


def make_opening(title, *, category="기상정보", number="1", toggle=0, per_copy=b"\x00" * 6):
    """Item-opening record (header 0x45 0xFC) with its fixed metadata frame and a fill block."""
    body = bytearray(92)
    body[0:2] = per_copy[0:2]
    body[2:4] = b"\x08\x00"
    body[4:6] = per_copy[2:4]
    body[6:8] = b"\xab\x7e"
    body[8:12] = per_copy[4:6] + b"\x00\x00"
    body[12:14] = b"\x51\x00"
    body[15] = 0xAB
    body[16:18] = b"\x7e\x00"
    body[18:20] = number.encode("utf-16le")
    body[20:22] = b"\x2e\x00"
    body[22:30] = category.encode("utf-16le")
    encoded = title.encode("utf-16le")
    body[36:36 + len(encoded)] = encoded
    payload = bytes([0x45 | (0x80 if toggle else 0), 0xFC]) + bytes(body)
    return payload + reference_crc(payload).to_bytes(2, "big") + b"\xbb" * 16


def flip(data, index):
    result = bytearray(data)
    result[index] ^= 1
    return bytes(result)


class TextRecordsTest(unittest.TestCase):
    def test_crc_standard_check(self):
        self.assertEqual(crc(b"123456789"), 0xD64E)
        self.assertEqual(crc(bytes(range(128))), reference_crc(bytes(range(128))))

    def test_all_nonempty_even_lengths_with_and_without_fill(self):
        for length in range(2, 128, 2):
            for final in (False, True):
                sequence, toggle = (length // 2) % 16, (length // 2) % 2
                with self.subTest(length=length, final=final):
                    text = "가" * (length // 2)
                    row = make_record(text.encode("utf-16le"), final=final,
                                      sequence=sequence, toggle=toggle)
                    record = parse_record(row)
                    self.assertEqual(record.size, len(row))
                    self.assertEqual(record.size % 16, 0)
                    self.assertEqual((record.body_length, record.text), (length, text))
                    self.assertEqual((record.sequence, record.item_toggle, record.final),
                                     (sequence, toggle, final))
                    self.assertEqual(record.header_hex, row[:2].hex())

    def test_crc_covers_header_and_body_and_is_big_endian(self):
        row = make_record(b"A\0B\0")
        for index in (0, 2, 6, 7):
            with self.subTest(index=index):
                # Change an unassigned header bit at index 0, not the length.
                bad = bytes([row[0] ^ 0x40]) + row[1:] if index == 0 else flip(row, index)
                with self.assertRaisesRegex(RecordError, "CRC mismatch"):
                    parse_record(bad)
        self.assertNotEqual(row[6], row[7])
        with self.assertRaisesRegex(RecordError, "CRC mismatch"):
            parse_record(row[:6] + row[6:8][::-1] + row[8:])

    def test_odd_and_malformed_utf16le_are_structural_failures(self):
        with self.assertRaisesRegex(RecordError, "odd UTF-16LE body length"):
            parse_record(make_record(b"A"), check_charset=False)
        with self.assertRaisesRegex(RecordError, "invalid UTF-16LE"):
            parse_record(make_record(b"\x00\xd8"), check_charset=False)

    def test_printable_text_and_character_controls(self):
        text = "한글\t12.5㎏ / 漢字\r\nNext \U0001f326"
        row = make_record(text.encode("utf-16le"))
        self.assertEqual(parse_record(row).text, text)
        for text in ("A\x00", "A\x1b", "A‮", "A​", "뮻" * 3, "--\r\n", ""):
            with self.subTest(text=text):
                row = make_record(text.encode("utf-16le"))
                with self.assertRaisesRegex(RecordError, "charset gate"):
                    parse_record(row)
                self.assertEqual(parse_record(row, check_charset=False).text, text)

    def test_padding_must_be_zero_for_both_final_states(self):
        for final in (False, True):
            with self.subTest(final=final):
                row = make_record(b"A\0", final=final)
                with self.assertRaisesRegex(RecordError, "nonzero padding"):
                    parse_record(flip(row, 15))

    def test_nonfinal_requires_full_exact_fill(self):
        row = make_record(b"A\0")
        for missing in (1, 16, 17):
            with self.subTest(missing=missing):
                with self.assertRaisesRegex(RecordError, "truncated record"):
                    parse_record(row[:-missing])
        with self.assertRaisesRegex(RecordError, "invalid nonfinal fill"):
            parse_record(flip(row, -1))
        with self.assertRaisesRegex(RecordError, "truncated header"):
            parse_record(row[:1])

    def test_final_neither_requires_nor_allows_immediate_fill(self):
        row = make_record(b"A\0", final=True)
        self.assertEqual(parse_record(row).size, len(row))
        with self.assertRaisesRegex(RecordError, "unexpected fill block"):
            parse_record(row + b"\xbb" * 16)
        with self.assertRaisesRegex(RecordError, "truncated record"):
            parse_record(row[:-1])
        self.assertEqual(parse_record(row + bytes(16)).size, len(row))

    def test_scanner_alignment_and_resynchronization(self):
        first = make_record(b"X\0", final=True, toggle=1, sequence=15)
        broken = flip(make_record(b"Y\0"), 4)
        last = make_record(b"Z\0", sequence=0)
        wire = bytes(16) + first + broken + last
        self.assertEqual([(r.offset, r.text) for r in scan_records(wire)],
                         [(16, "X"), (16 + len(first) + len(broken), "Z")])
        with self.assertRaisesRegex(RecordError, "unaligned offset"):
            parse_record(b"\x00" + first, offset=1)
        self.assertEqual(list(scan_records(b"\x00" + first)), [])

    def test_unknown_bytes_cannot_pass_structural_checks(self):
        plaintext = make_record(b"A\0")
        self.assertEqual(parse_record(plaintext, known_bytes=b"\x01"*len(plaintext)).text, "A")
        with self.assertRaisesRegex(ValueError, "exactly the input length"):
            list(scan_records(plaintext, known_bytes=b"\x01"))
        for index in (0, 1, 2, 4, 6, 16):
            with self.subTest(index=index):
                known = flip(b"\x01" * len(plaintext), index)
                with self.assertRaisesRegex(RecordError, "unknown"):
                    parse_record(plaintext, known_bytes=known)

    def test_final_does_not_infer_from_unknown_lookahead(self):
        row = make_record(b"A\0", final=True)
        self.assertEqual(parse_record(row + b"\xbb" * 16,
                                      known_bytes=b"\x01" * len(row) + bytes(16)).size, len(row))

    def test_extended_accepts_ideographic_indent_only_when_enabled(self):
        text = "\u3000평양의 날씨"
        row = make_record(text.encode("utf-16le"))
        with self.assertRaisesRegex(RecordError, "charset gate"):
            parse_record(row)
        self.assertEqual(parse_record(row, extended=True).text, text)
        for bad in ("A\x00", "A\x1b", "A\u202e", "\u3000" * 3, ""):
            with self.subTest(text=bad):
                with self.assertRaisesRegex(RecordError, "charset gate"):
                    parse_record(make_record(bad.encode("utf-16le")), extended=True)

    def test_extended_final_consumes_known_fill_but_never_requires_it(self):
        row = make_record(b"A\0", final=True)
        self.assertEqual(parse_record(row + b"\xbb" * 16, extended=True).size, len(row) + 16)
        self.assertEqual(parse_record(row, extended=True).size, len(row))
        self.assertEqual(parse_record(row + bytes(16), extended=True).size, len(row))
        unknown_fill = b"\x01" * len(row) + bytes(16)
        self.assertEqual(parse_record(row + b"\xbb" * 16, known_bytes=unknown_fill,
                                      extended=True).size, len(row))
        # The scanner skips the consumed fill block and finds the next record.
        nxt = make_record(b"B\0", sequence=3)
        self.assertEqual([(r.offset, r.text) for r in scan_records(row + b"\xbb" * 16 + nxt,
                                                                    extended=True)],
                         [(0, "A"), (len(row) + 16, "B")])

    def test_extended_opening_record_requires_fixed_metadata_frame(self):
        row = make_opening("11월 26일 날씨", per_copy=b"\x12\x34\x56\x78\x9a\xbc")
        record = parse_record(row, extended=True)
        self.assertEqual(record.text, "~1.기상정보\n11월 26일 날씨")
        self.assertEqual((record.size, record.body_length, record.sequence, record.final),
                         (len(row), 92, 15, False))
        self.assertEqual(parse_record(make_opening("제목", toggle=1), extended=True).item_toggle, 1)
        with self.assertRaisesRegex(RecordError, "charset gate"):
            parse_record(row)                      # default grammar: control bytes in the frame
        for index in (4, 5, 8, 9, 14, 15, 17, 18, 19, 22, 23, 32, 37):
            with self.subTest(index=index):
                bad = bytearray(row)
                bad[index] ^= 0x01
                payload = bytes(bad[:94])
                bad[94:96] = reference_crc(payload).to_bytes(2, "big")
                with self.assertRaisesRegex(RecordError, "metadata header"):
                    parse_record(bytes(bad), extended=True)
        with self.assertRaisesRegex(RecordError, "category failed"):
            parse_record(make_opening("제목", category="ABCD"), extended=True)
        with self.assertRaisesRegex(RecordError, "embedded NUL"):
            parse_record(make_opening("제\x00목"), extended=True)
        with self.assertRaisesRegex(RecordError, "CRC mismatch"):
            parse_record(flip(row, 50), extended=True)

    def test_extended_scan_matches_default_on_default_grammar_streams(self):
        first = make_record(b"X\0", final=True, toggle=1, sequence=15)
        last = make_record("평양".encode("utf-16le"), sequence=2)
        wire = bytes(16) + first + flip(make_record(b"Y\0"), 4) + last
        self.assertEqual(list(scan_records(wire)), list(scan_records(wire, extended=True)))

    def test_replay_ignores_input_flags_and_requires_exact_window(self):
        row = make_record(b"A\0")
        report = replay_rows([
            {"plaintext_hex": row.hex(), "crc_ok": False},
            {"plaintext_hex": flip(row, 4).hex(), "crc_ok": True},
            {"plaintext_hex": (row + bytes(16)).hex()},
        ])
        self.assertEqual(report, {
            "rows": 3, "accepted": 1, "accepted_body_lengths": {2: 1},
            "rejected_by_reason": {"CRC mismatch": 1, "trailing bytes after record": 1},
        })


if __name__ == "__main__":
    unittest.main()
