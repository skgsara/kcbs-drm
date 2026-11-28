"""Evidence accounting preserves the packet clock and the original field domains."""
from binascii import crc_hqx
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

import numpy as np

from evs_evidence import bit_evidence, field_sections
from project_evs_group import project_group


def projection(packets):
    counter = 5
    body = np.zeros((3, 716), dtype=np.uint8)
    for phase, unit in enumerate(body):
        unit[1] = phase << 4
        if phase == 0:
            unit[664:668] = list(counter.to_bytes(4, "big"))
        unit[2] = 0xfa       # Slot 0: three legal two-bit HQ class values.
        unit[39] = 0x61      # Slot 1: the transition tag requires a zero suffix.
        unit[40 + 31] = 1    # This tail contradicts all four candidate bit pairs.
        unit[4] = 0x74       # Slot 8: P1 mode in packet 0, its GSC fields in packet 1.
        unit[714:] = list((crc_hqx(unit[:714].tobytes(), 0xffff) ^ 0xffff).to_bytes(2, "big"))
    with tempfile.TemporaryDirectory() as name:
        path = Path(name) / "packets.npz"
        np.savez(path, ticks=np.arange(3 * counter, 3 * counter + 3),
                 packets=body.reshape(3, 4, 179), packet_ok=np.repeat([packets], 3, axis=0))
        result = project_group(path, counter, packets=True)
    result.update(field_sections(result["slots"]))
    return result


class EVSEvidenceTests(unittest.TestCase):
    def test_restricted_pair_is_preserved_even_without_fixed_bits(self):
        original = projection([True] * 4)
        saved = deepcopy(original)
        result = bit_evidence(original)
        self.assertEqual(original, saved)
        event, = result["slots"][0]["events"]
        self.assertEqual(event["word_bits"], [8, 10])
        self.assertEqual(event["allowed_values"], [0, 1, 2])
        self.assertEqual(event["fixed_bits"], {})
        self.assertEqual((event["kind"], event["outcome"], event["excluded_value_count"], event["observed"]),
                         ("conditional", "restricted", 1, None))
        self.assertEqual(event["observation"], "carried_unknown")
        self.assertEqual(result["total"]["direct_bits"], 10560)
        self.assertEqual(result["total"]["word_erasures"], 60)

    def test_empty_domain_preserves_contradiction_and_erasure(self):
        result = bit_evidence(projection([True] * 4))
        row = result["slots"][1]
        event = next(e for e in row["events"] if e["check"] == "transition_tag")
        self.assertEqual((event["allowed_values"], event["excluded_value_count"], event["fixed_bits"]),
                         ([], 4, {}))
        self.assertEqual((event["outcome"], row["direct_bits"], row["word_erased"]),
                         ("contradiction", 176, True))

    def test_partial_receipt_preserves_unavailable_observations(self):
        report = bit_evidence(projection([True, False, False, False]))
        row = report["slots"][8]
        self.assertEqual((row["direct_bits"], row["carried_unknown_bits"], row["no_receipt_bits"]), (8, 0, 256))
        for event in row["events"]:
            self.assertEqual((event["kind"], event["observation"], event["outcome"], event["observed"]),
                             ("direct_check", "no_receipt", "unavailable", None))
        self.assertEqual({e["check"] for e in row["events"]}, {"swb_gsc_inactive", "inactive_nibble"})
        self.assertEqual(sum(report["total"][k] for k in ("direct_bits", "carried_unknown_bits", "no_receipt_bits")),
                         60 * 264)
        self.assertEqual(sum(p["rule_events"] for p in report["by_position"].values()), report["total"]["rule_events"])

    def test_modified_section_or_projection_fails_validation(self):
        report = projection([True, False, False, False])
        changed = deepcopy(report)
        changed["intra_word"]["slots"][0]["allowed"] = [1, 1]
        with self.assertRaisesRegex(ValueError, "saved intra_word"):
            bit_evidence(changed)
        changed = deepcopy(report)
        changed["intra_word"]["slots"].pop()
        with self.assertRaisesRegex(ValueError, "saved intra_word"):
            bit_evidence(changed)
        row = report["slots"][5]
        tokens = row["octets"].split()
        self.assertEqual(tokens[9], "--")  # Starts at DU offset 179, the missing packet 1.
        tokens[9] = "00"
        row["octets"] = " ".join(tokens)
        row["direct_bits"] += 8
        with self.assertRaisesRegex(ValueError, "physical packet receipt"):
            bit_evidence(report)


if __name__ == "__main__":
    unittest.main()
