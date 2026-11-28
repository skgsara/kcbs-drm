"""Check prediction invariance when every withheld center octet in the public 12:32 source changes."""
import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import struct
import sys

HERE = Path(__file__).resolve().parent
CASE = HERE.parents[1] / "nov28/same-6140-1232"
sys.path.insert(0, str(CASE))
from native_groups import native_groups
from check_evs_origin import PROJECTED_OCTETS
from drm_row_alignment import parse_msc
from render_continuous import MODE_POSITIONS, PACKET_STARTS
from salvage_msc_packets import PACKET_HEADERS, crc
from rule import decisions, features, train

SOURCE_SHA = "267261e04afc6f48ef05a547f7784feb4cc9cf39401bf518697992153bdb0c64"
P5 = 5  # Zero-based payload index; word octet 6 includes the mode.
CENTERS = range(1, 60, 3)


def check(condition, message):
    if not condition:
        raise ValueError(message)


def digest(raw):
    return sha256(raw).hexdigest()


def record_digest(rows):
    return digest(json.dumps(rows, separators=(",", ":")).encode("ascii"))


def with_crc(data):
    return data + crc(data).to_bytes(2, "big")


def frame(rows):
    return b"".join(struct.pack("<I", len(row)) + row for row in rows)


def mutate(raw, receipts):
    changed = parse_msc(raw)
    stale = changed.copy()
    rows = {}
    for item in receipts:
        for phase in range(3):
            index = item["phase0_row"] + phase
            check(rows.setdefault(index, phase) == phase, "contradictory source phase")
    stats = Counter()
    for index, phase in rows.items():
        original = changed[index]
        invalid_wire = bytearray(original)
        unit = bytearray(b"".join(original[i+1:i+180] for i in range(0, 728, 182)))
        for slot in CENTERS:
            slot_phase, local = divmod(slot, 20)
            if slot_phase == phase:
                offset = PACKET_STARTS[local] + P5
                unit[offset] ^= 255
                ordinal, payload_byte = divmod(offset, 179)
                invalid_wire[ordinal * 182 + 1 + payload_byte] ^= 255
                stats["changed_physical_center_octets"] += 1
        unit = with_crc(bytes(unit[:-2]))
        check(unit[-2:] != original[-4:-2], "expected a different DU checksum for this fixed edit")
        packets = []
        for ordinal, header in enumerate(PACKET_HEADERS):
            start = ordinal * 179
            packets.append(with_crc(bytes([header]) + unit[start:start + 179]))
            old_crc_start = ordinal * 182 + 180
            stats["changed_packet_crcs"] += packets[-1][-2:] != original[old_crc_start:old_crc_start + 2]
        changed[index] = b"".join(packets)
        stale[index] = bytes(invalid_wire)
    stats["recomputed_du_crcs"] = len(rows)
    stats["recomputed_packet_crcs"] = 4 * len(rows)
    return frame(changed), frame(stale), stats


class FeatureOctets:
    """Provide only the individual octets specified by the feature contract."""
    def __init__(self, unit, phase):
        allowed = set(MODE_POSITIONS)
        allowed.update(start + P5 for local, start in enumerate(PACKET_STARTS) if 20 * phase + local not in CENTERS)
        self.octets = {address: unit[address] for address in allowed}
        self.read = set()

    def __getitem__(self, address):
        if type(address) is not int or address not in self.octets:
            raise ValueError(f"unexpected feature access at DU offset {address}")
        self.read.add(address)
        return self.octets[address]


def observed_features(groups):
    # Independent wire address calculation by absolute 60-slot position, including phase boundaries.
    def octet(triple, slot, addresses, offset=0):
        phase, local = divmod(slot, 20)
        return triple[phase][addresses[local] + offset]
    return {(counter, center, *(octet(triple, s, MODE_POSITIONS) for s in (center-1, center, center+1)),
             octet(triple, center-1, PACKET_STARTS, P5), octet(triple, center+1, PACKET_STARTS, P5))
            for counter, triple in groups.items() for center in CENTERS}


def run():
    raw = (CASE / "yokohama-msc.bin").read_bytes()
    check(digest(raw) == SOURCE_SHA, "wrong development MSC")
    check(1 + P5 in PROJECTED_OCTETS, "target is outside the direct octets")
    counts, receipts, _, groups = native_groups(raw)
    altered, stale, stats = mutate(raw, receipts)
    other_counts, other_receipts, _, altered_groups = native_groups(altered)
    _, _, _, stale_groups = native_groups(stale)
    source_rows = [(r["counter"], r["phase0_row"]) for r in receipts]
    changed_rows = [(r["counter"], r["phase0_row"]) for r in other_receipts]
    check(counts == other_counts and source_rows == changed_rows,
          "rewritten CRC-valid groups or reception counts differ")
    check(not stale_groups, "stale CRC negative unexpectedly supplied a complete group")
    for counter, triple in groups.items():
        for center in CENTERS:
            phase, local = divmod(center, 20)
            offset = PACKET_STARTS[local] + P5
            check(triple[phase][offset] ^ altered_groups[counter][phase][offset] == 255,
                  "a reserved center survived the edit")
    before = list(features(groups))
    after = list(features(altered_groups))
    guarded = {c: tuple(FeatureOctets(unit, phase) for phase, unit in enumerate(triple)) for c, triple in groups.items()}
    safe = list(features(guarded))
    check(before == after == safe, "altering or withholding centers changed the feature ledger")
    check(len(before) == 20 * len(groups) and set(map(tuple, before)) == observed_features(groups),
          "feature ledger differs from the twenty disjoint physical triples per group")
    # Train only on the separate pinned member capture and pass the two permitted model fields.
    fit = train()
    check(not set(groups).intersection(fit["training_counter_ids"]), "overlapping training and mutation-control counters")
    model = {key: fit[key] for key in ("by_mode", "fallback")}
    forecast = list(decisions(before, model))
    check(forecast == list(decisions(after, model)) == list(decisions(safe, model)), "decisions differ")
    check(forecast, "positive control made no forecasts")
    reads = sum(len(unit.read) for triple in guarded.values() for unit in triple)
    check(reads == 100 * len(groups), "expected sixty modes and forty distinct donor octets per group")
    return dict(source="../../nov28/same-6140-1232/yokohama-msc.bin", source_msc_sha256=SOURCE_SHA,
                changed_valid_msc_sha256=digest(altered), stale_crc_negative_msc_sha256=digest(stale),
                source_and_valid_mutant_native_counts=counts, native_groups=len(groups),
                negative_complete_groups=len(stale_groups), changed_du_and_packet_checks=stats,
                reserved_slots_per_group=list(CENTERS), payload_offset=P5, feature_rows=len(before),
                permitted_scalar_octets_read=reads, accepted_decisions=len(forecast),
                features_sha256_before_after_and_restricted=record_digest(before),
                decisions_sha256_before_after_and_restricted=record_digest(forecast),
                model_fit_source_sha256=fit["source_sha256"], mode_baseline_sha256=record_digest(model),
                model_training_counter_overlap=0,
                scope="Artificial withhold on one receiver. Naturally missing targets and independent station "
                      "scores are separate evaluations. The predictor receives no current center octet or CRC.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", type=Path, help="compare with a saved JSON receipt")
    args = parser.parse_args()
    result = run()
    if args.check:
        check(result == json.loads(args.check.read_bytes()), "saved redaction receipt differs")
        print(f"{result['native_groups']} groups, {result['feature_rows']} identical feature rows, "
              f"{result['accepted_decisions']} identical decisions")
    else:
        print(json.dumps(result, indent=2))
