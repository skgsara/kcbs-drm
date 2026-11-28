"""Evidence accounting preserves the packet clock and the original field domains."""
from binascii import crc_hqx
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from evs_evidence import bit_evidence, field_sections, normalize_event, summarize
from project_evs_group import project_group


def projection(packets, *, gsc_everywhere=False):
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
        if gsc_everywhere:
            for cycle in range(5):
                for role in range(4):
                    start = 7 + 131 * cycle + 33 * role
                    unit[2 + cycle if role == 0 else start - 1] = 0x74
                    unit[start + 4] = 0xc1
            if phase == 0:
                unit[40 + 4] = 0xa1  # P2: two upper bits differ from C.
                unit[106 + 4] = 0xcf  # P4: low nibble outside 0..10, upper bits match.
        unit[714:] = list((crc_hqx(unit[:714].tobytes(), 0xffff) ^ 0xffff).to_bytes(2, "big"))
    with tempfile.TemporaryDirectory() as name:
        path = Path(name) / "packets.npz"
        np.savez(path, ticks=np.arange(3 * counter, 3 * counter + 3),
                 packets=body.reshape(3, 4, 179), packet_ok=np.repeat([packets], 3, axis=0))
        result = project_group(path, counter, packets=True)
    result.update(field_sections(result["slots"]))
    return result


class EVSEvidenceTests(unittest.TestCase):
    def test_default_report_retains_the_frozen_v1_encoding(self):
        source = projection([True, False, False, False])
        current = bit_evidence(source)
        encoded = (json.dumps(current, indent=2, allow_nan=False) + "\n").encode()
        # Exact CLI encoding of this fixture under the published v1 implementation.
        self.assertEqual(sha256(encoded).hexdigest(), "f75eb65764df007bf3d02c6da15da72e1eda2a3de621825d8031b9c66ee2194a")
        self.assertEqual(current, bit_evidence(source, version=1))
        extended = bit_evidence(source, version=2)
        self.assertEqual(extended["format"], "kcbs-evs-bit-evidence-v2")
        self.assertEqual(extended["slots"], current["slots"])

    def test_exact_direct_bits_versus_field_membership_across_all_positions(self):
        result = bit_evidence(projection([True] * 4, gsc_everywhere=True), version=2)
        for position, counts in result["by_position"].items():
            self.assertEqual(counts["unique_direct_checked_bits"], 15 * 8)
            self.assertEqual(counts["unique_direct_fixed_bits"], 15 * 4)
            self.assertEqual(counts["unique_direct_fixed_bits_checked"], 15 * 4)
            wrong = 2 if position == "2" else 0
            self.assertEqual(counts["unique_direct_fixed_bits_mismatching"], wrong)
            self.assertEqual(counts["unique_direct_fixed_bits_matching"], 60 - wrong)
        self.assertEqual(result["total"]["unique_direct_fixed_bits_matching"], 238)
        self.assertEqual(result["total"]["events_by_outcome"]["mismatch"], 2)
        self.assertEqual(result["total"]["word_erasures"], 60)

    def test_conflicts_and_conditional_labels_stay_separate_from_direct_comparisons(self):
        result = bit_evidence(projection([True, False, False, False]))
        slot = result["slots"][8]
        counts = summarize([slot], version=2)
        self.assertEqual(counts["unique_direct_fixed_bits"], 4)
        self.assertEqual(counts["unique_direct_fixed_bits_unavailable"], 4)
        self.assertEqual(counts["unique_direct_fixed_bits_checked"], 0)

        # Repeated or conflicting rules here test accounting independently of the live ruleset.
        row = deepcopy(bit_evidence(projection([True] * 4, gsc_everywhere=True))["slots"][0])
        nibble = next(event for event in row["events"] if event["check"] == "inactive_nibble")
        row["events"].extend([deepcopy(nibble), dict(nibble, fixed_bits={"40": 0}),
                              dict(nibble, kind="conditional", fixed_bits={"41": 0}, outcome="restricted")])
        counts = summarize([row], version=2)
        self.assertEqual(counts["unique_conflicting_direct_bits"], 1)
        self.assertEqual(counts["unique_direct_fixed_bits_matching"], 3)
        self.assertEqual(counts["unique_conditional_fixed_bits"], 1)
        self.assertEqual(counts["unique_direct_checked_bits"], 8)

    def test_non_singleton_domain_can_fix_only_some_bits(self):
        # An illustrative four-bit field checks the normalization and tally independently
        # of the current sender rules. Values 8..11 all start with 10.
        row = bit_evidence(projection([True] * 4, gsc_everywhere=True))["slots"][0]
        raw = dict(slot=0, check="swb_gsc_inactive", allowed=[8, 11], word_bits=[44, 48],
                   observed=1, outcome="reject")
        field = normalize_event("intra_word", raw, {}, [row["octets"].split()])
        self.assertEqual(field["fixed_bits"], {"44": 1, "45": 0})
        counts = summarize([dict(row, events=[field])], version=2)
        self.assertEqual(counts["unique_direct_checked_bits"], 4)
        self.assertEqual(counts["unique_direct_fixed_bits_checked"], 2)
        self.assertEqual(counts["unique_direct_fixed_bits_matching"], 1)
        self.assertEqual(counts["unique_direct_fixed_bits_mismatching"], 1)

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
