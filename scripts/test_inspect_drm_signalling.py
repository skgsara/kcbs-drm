"""Raw receiver observations and boundary cases for DRM30 service signalling."""
from binascii import crc_hqx
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from inspect_drm_signalling import inspect_file


FAC = bytes.fromhex("47c20a0000201000f0")
SDC = bytes.fromhex(
    "0106010002d80850c1b300000ac02d2d2d6b703e10eca1b0ec84a0eca491ec9599eca09c32eb9dbceca780ec98a4"
    "ebb0a9ec86a100000000000000000000000000000000000000000000000000e0f8")


def line(ch, word):
    bits = "".join(f"{b:08b}" for b in word)
    return ch + " " + (bits if ch == "FAC" else bits[4:]) + "\n"


def sdc(data):
    word = b"\x0f" + data  # CRC includes the AFS nibble represented as a full leading byte.
    return line("SDC", word + (crc_hqx(word, 0xffff) ^ 0xffff).to_bytes(2, "big"))


class SignallingTest(unittest.TestCase):
    def inspect(self, content):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "signalling.bits"
            path.write_text(content, encoding="ascii")
            return inspect_file(path)

    def test_observed_words_and_corrupt_copies(self):
        good = line("FAC", FAC) + line("SDC", SDC)
        corrupted = (line("FAC", FAC[:-1] + bytes([FAC[-1] ^ 1])) +
                     line("SDC", SDC[:-1] + bytes([SDC[-1] ^ 1])))
        r = self.inspect(good + corrupted)
        for channel in ("FAC", "SDC"):
            self.assertEqual(r["blocks"][channel], dict(observed=2, crc_passed=1, crc_failed=1))
        self.assertEqual(r["fac_services"], [dict(service_id="A00002", short_id=0, audio_ca=0, language_code=0,
                         service="data", service_descriptor=0, data_ca=0, count=1)])
        types = {e["type"]: e for e in r["sdc_entities"]}
        self.assertEqual(set(types), {0, 1, 5, 12})
        self.assertEqual(types[0]["streams"], [dict(stream_id=0, part_a_bytes=0, part_b_bytes=728)])
        self.assertEqual(types[1]["label"], "조선중앙제2라지오방송")
        self.assertEqual((types[12]["language"], types[12]["country"]), ("---", "kp"))
        self.assertEqual((types[5]["packet_data_bytes"], types[5]["dab_user_application_type"]), (179, 0))

    def test_crc_good_envelope_overrun_does_not_supply_partial_evidence(self):
        valid = bytes.fromhex("0850c1b30000")
        r = self.inspect(sdc(valid + b"\x02\x10"))
        self.assertEqual(r["blocks"]["SDC"]["crc_passed"], 1)
        self.assertEqual(r["sdc_entities"], [])
        self.assertEqual(sum(r["sdc_crc_passed_with_framing_error"].values()), 1)

    def test_unknown_zero_length_entity_and_unreadable_fields_keep_their_boundaries(self):
        r = self.inspect(sdc(bytes.fromhex("00f00210ff00230ac02d2d2d6b7000")))
        by_type = {e["type"]: e for e in r["sdc_entities"]}
        self.assertEqual(by_type[15]["raw_hex"], "00f0")
        self.assertIn("field_error", by_type[1])
        self.assertEqual((by_type[2]["audio_ca_scope"], by_type[2]["data_ca_scope"]), (1, 1))
        self.assertEqual(by_type[12]["country"], "kp")

    def test_time_with_optional_signed_offset(self):
        # Previously received 3-byte date/time body, followed by a 90-minute negative offset.
        a = bytes.fromhex("06877ddbd0")
        b = bytes.fromhex("08877ddbd023")
        r = self.inspect(sdc(a) + sdc(b))
        by_hex = {e["raw_hex"]: e for e in r["sdc_entities"]}
        self.assertEqual(by_hex[a.hex()]["signalled_utc_minute"], "2026-11-27T15:16Z")
        self.assertIsNone(by_hex[a.hex()]["local_offset_minutes"])
        self.assertEqual(by_hex[b.hex()]["local_offset_minutes"], -90)
        self.assertEqual(r["time_entity_occurrences"], [dict(sdc_block_index=0, raw_hex=a.hex()),
                                                        dict(sdc_block_index=1, raw_hex=b.hex())])

    def test_empty_or_invalid_input(self):
        self.assertEqual(self.inspect("")["blocks"]["FAC"]["observed"], 0)
        for bad in ("FAC 01\n", "SDC 00010102\n", "MSC 1101\n"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self.inspect(bad)
