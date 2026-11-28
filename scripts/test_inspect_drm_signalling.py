"""Raw receiver observations and boundary cases for DRM30 service signalling."""
from binascii import crc_hqx
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from inspect_drm_signalling import fac_crc, inspect_file, service_counts


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


def fac(service_id, code, *, reconfiguration=0):
    bits = list(f"{int.from_bytes(FAC[:-1], 'big'):064b}")
    bits[11:15] = f"{code:04b}"
    bits[15:18] = f"{reconfiguration:03b}"
    bits[20:44] = f"{service_id:024b}"
    raw = int("".join(bits), 2).to_bytes(8, "big")
    return line("FAC", raw + bytes([fac_crc(raw)]))


class SignallingTest(unittest.TestCase):
    def inspect(self, content, **kwargs):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "signalling.bits"
            path.write_text(content, encoding="ascii")
            return inspect_file(path, **kwargs)

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

    def test_joint_fac_states_and_singleton_callback_order(self):
        bad_fac = line("FAC", FAC[:-1] + bytes([FAC[-1] ^ 1]))
        data = (fac(1, 1) + sdc(bytes.fromhex("0850c1b30000")) + bad_fac +
                fac(2, 0, reconfiguration=4) + sdc(bytes.fromhex("0210")) + fac(1, 0xf))
        result = self.inspect(data, components=True)
        components = result.pop("components")
        self.assertEqual(result, self.inspect(data))
        rows = components["fac_joint_states"]
        self.assertEqual([(x["audio"], x["data"], x["service_class_consistency"]) for x in rows],
                         [(0, 1, "permitted"), (4, 0, "contradicted"), (0, 4, "permitted")])
        singleton, = components["singleton_fac_services"]
        self.assertEqual(singleton["fac"]["state"]["reconfiguration_index"], 4)
        self.assertEqual(singleton["fac"]["at"], dict(line=4, channel_ordinal=2))
        self.assertEqual([singleton[k]["at"]["line"] for k in ("previous_fac", "following_fac", "previous_sdc", "following_sdc")],
                         [1, 6, 2, 5])
        self.assertIn("framing_error", singleton["following_sdc"])
        self.assertEqual((components["sdc_crc_valid_blocks"], components["sdc_parseable_blocks"]), (2, 1))

    def test_reserved_and_combined_service_counts(self):
        self.assertEqual([service_counts(code) for code in range(16)], [
            (4, 0), (0, 1), (0, 2), (0, 3), (1, 0), (1, 1), (1, 2), (1, 3),
            (2, 0), (2, 1), (2, 2), None, (3, 0), (3, 1), None, (0, 4)])
        comp = self.inspect(fac(3, 0xb), components=True)["components"]
        self.assertIsNone(comp["fac_joint_states"][0]["data"])
        self.assertEqual(comp["fac_joint_states"][0]["service_class_consistency"], "reserved_count_code")
        self.assertIsNone(comp["singleton_fac_services"][0]["following_sdc"])

    def test_received_fac_toggle_and_reserved_bit_qualify_class_interpretation(self):
        # CRC-valid Yokohama FAC, 13:00 primary, callback ordinal 1367.
        singleton = bytes.fromhex("67c137dd19cc5aa5e9")
        comp = self.inspect(line("FAC", FAC) + line("FAC", singleton), components=True)["components"]
        ordinary, flagged = comp["fac_joint_states"]
        for state, expected in ((ordinary, (0, 0, 0)), (flagged, (0, 1, 1))):
            self.assertEqual(tuple(state[k] for k in ("rm_flag", "toggle", "rfu")), expected)
        self.assertEqual(ordinary["format_flags"], [])
        self.assertEqual(flagged["service_id"], "7DD19C")
        self.assertEqual(flagged["format_flags"], ["nonzero_toggle_for_rm0", "nonzero_rfu"])
        self.assertEqual(flagged["service_class_consistency"], "contradicted")

    def test_component_sets_are_local_to_block_and_version(self):
        alloc = bytes.fromhex("06010002d8")
        app = bytes.fromhex("0850c1b30000")
        audio = bytes.fromhex("05914000")  # next-configuration audio, stream 1
        next_alloc = bytes.fromhex("0d01000008000010")  # two streams
        content = (sdc(app + alloc + audio) + sdc(audio + app + alloc) + sdc(audio + next_alloc) +
                   sdc(app) + sdc(bytes.fromhex("021041")))
        sets = self.inspect(content, components=True)["components"]["sdc_component_sets"]
        self.assertEqual([s["count"] for s in sets], [2, 1, 1, 1])
        self.assertEqual([sets[0][k]["line"] for k in ("first", "last")], [1, 2])
        current, upcoming = sets[0]["configurations"]
        d, = current["descriptors"]
        self.assertEqual((d["allocation_raw_hex"], d["stream"]["part_b_bytes"]), (alloc.hex(), 728))
        self.assertEqual(upcoming["descriptors"][0]["allocation_status"], "missing_allocation")
        upcoming = sets[1]["configurations"][1]
        self.assertEqual(upcoming["descriptors"][0]["stream"], dict(stream_id=1, part_a_bytes=0, part_b_bytes=16))
        self.assertEqual(upcoming["descriptors"][0]["audio_coding"], 1)
        self.assertEqual(sets[2]["configurations"][0]["descriptors"][0]["allocation_status"], "missing_allocation")
        self.assertEqual(sets[3]["configurations"][0]["missing_types"], [0, 5, 9])

    def test_conflicting_missing_and_malformed_allocations(self):
        alloc = bytes.fromhex("06010002d8")
        app = bytes.fromhex("0851c1b30000")  # requires stream 1
        bad_alloc = bytes.fromhex("020000")
        bad_app = bytes.fromhex("0051")
        data = (sdc(alloc + app) + sdc(alloc + bytes.fromhex("06010002d0") + app) +
                sdc(bad_alloc + app) + sdc(alloc + bad_app) + sdc(alloc + alloc + app))
        sets = self.inspect(data, components=True)["components"]["sdc_component_sets"]
        statuses = [r["configurations"][0]["descriptors"][0]["allocation_status"] for r in sets]
        self.assertEqual(statuses, ["stream_absent", "ambiguous_allocation", "malformed_allocation",
                                    "malformed_descriptor", "stream_absent"])
        self.assertEqual(sets[4]["envelopes"].count(alloc.hex()), 2)

    def test_zero_length_stream_preserves_descriptor_without_claiming_capacity(self):
        comp = self.inspect(sdc(bytes.fromhex("060000000004904000")), components=True)["components"]
        audio, = comp["sdc_component_sets"][0]["configurations"][0]["descriptors"]
        self.assertEqual((audio["audio_coding"], audio["allocation_status"]), (1, "stream_zero_length"))
        self.assertEqual(audio["stream"], dict(stream_id=0, part_a_bytes=0, part_b_bytes=0))
