"""Exercise the transport repair on synthetic rows with known source bytes."""
from binascii import crc_hqx
from hashlib import sha256
import json

from repair import repair_row, single_bit_positions


def with_crc(data):
    checksum = crc_hqx(data, 0xffff) ^ 0xffff
    return data + checksum.to_bytes(2, "big")


def sender_row():
    data = bytes((i * 37 + 5) % 256 for i in range(714))
    unit = with_crc(data)
    headers = (0x80, 0x01, 0x02, 0x43)
    return b"".join(with_crc(bytes([header]) + unit[q * 179:(q + 1) * 179])
                    for q, header in enumerate(headers))


def checks(row):
    packets = [row[start:start + 182] for start in range(0, 728, 182)]
    unit = b"".join(packet[1:-2] for packet in packets)
    return dict(packet_crcs_pass=sum(with_crc(p[:-2]) == p for p in packets),
                data_unit_crc_pass=with_crc(unit[:-2]) == unit)


def corrupt(row, packet, wire_bits):
    data = bytearray(row)
    for bit in wire_bits:
        data[packet * 182 + bit // 8] ^= 1 << (7 - bit % 8)
    return bytes(data)


def check(condition, description):
    if not condition:
        raise ValueError(description)


def run():
    original = sender_row()
    positions = single_bit_positions()
    all_good = dict(packet_crcs_pass=4, data_unit_crc_pass=True)
    check(checks(original) == all_good, "synthetic sender CRCs")
    check(repair_row(original, positions) == (original, "all_packet_crcs_pass", None),
          "clean row changed")

    counts = []
    for packet in range(4):
        exact = 0
        for bit in range(182 * 8):
            damaged = corrupt(original, packet, [bit])
            proposed, reason, change = repair_row(damaged, positions)
            check(proposed == original and reason == "single_bit_proposed"
                  and change["packet_ordinal"] == packet and change["wire_bit_msb0"] == bit,
                  f"one-bit control failed at packet {packet}, bit {bit}")
            exact += 1
        counts.append(exact)

    two = corrupt(corrupt(original, 0, [48]), 1, [48])
    proposed, reason, change = repair_row(two, positions)
    check((proposed, reason, change) == (two, "multiple_failed_packet_crcs", None),
          "two failed packets produced a repair")

    # The MSB-first support of x^16 + x^12 + x^5 + 1 has offsets 0, 4, 11, 16.
    # Transmit the original and damage three of those bits. All four positions
    # lie inside the second packet's payload, away from either transmitted CRC.
    packet, first = 1, 48
    errors = [first, first + 4, first + 11]
    damaged = corrupt(original, packet, errors)
    false_word, false_reason, false_change = repair_row(damaged, positions)
    fourth = first + 16
    check(false_reason == "single_bit_proposed" and false_change["wire_bit_msb0"] == fourth
          and false_change["packet_ordinal"] == packet, "missing three-bit counterexample")
    check(false_word == corrupt(original, packet, [*errors, fourth]) and false_word != original
          and checks(false_word) == all_good, "counterexample must pass both checks")

    single = corrupt(original, packet, [fourth])
    restored, true_reason, true_change = repair_row(single, positions)
    check(restored == original and true_reason == false_reason
          and true_change["wire_bit_msb0"] == fourth, "paired one-bit control")

    return dict(
        synthetic_sender_row_sha256=sha256(original).hexdigest(), clean_unchanged=True,
        single_bit_trials_per_packet=182 * 8, single_bit_exact_by_packet=counts,
        single_bit_trials=sum(counts), single_bit_matching_sender=sum(counts),
        one_payload_bit_error=dict(packet_ordinal=packet, damaged_wire_bits_msb0=[fourth],
                                   proposed_wire_bit_msb0=true_change["wire_bit_msb0"],
                                   input_checks=checks(single), output_checks=checks(restored),
                                   proposed_matches_sender=restored == original),
        two_damaged_packets=dict(outcome=reason, input_checks=checks(two),
                                 unchanged=proposed == two, proposal=change),
        three_payload_bit_errors=dict(packet_ordinal=packet, damaged_wire_bits_msb0=errors,
                                      proposed_wire_bit_msb0=fourth, outcome=false_reason,
                                      input_checks=checks(damaged), output_checks=checks(false_word),
                                      proposed_matches_sender=False,
                                      proposed_row_sha256=sha256(false_word).hexdigest()),
    )


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
