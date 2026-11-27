"""Measure error detection on four previously decoded, publicly released text records."""
import json

from check import HERE, crc, parse_record, received_text


def binary_rank(columns):
    pivots = {}
    for value in columns:
        while value:
            pivot = value.bit_length() - 1
            if pivot not in pivots:
                pivots[pivot] = value
                break
            value ^= pivots[pivot]
    return len(pivots)


def single_bit_errors(record, blocks, tick):
    start = 3 * record["counter"] + record["phase"]
    raw = b"".join(blocks[t] for t in range(start, start + record["blocks"]))
    end = 2 + parse_record(raw).body_length
    expected = int(record["checksum"], 16)
    if crc(raw[:end]) != expected or int.from_bytes(raw[end:end + 2], "big") != expected:
        raise ValueError(f"CRC differs from release at tick {start}")
    # Keep the original record boundary and transmitted checksum fixed in every trial.
    offset = 16 * (tick - start)
    if not 0 <= offset <= end - 11:
        raise ValueError("the selected eleven octets must lie in the header or body")
    for byte in range(offset, offset + 11):
        for bit in range(8):
            changed = bytearray(raw[:end])
            changed[byte] ^= 1 << bit
            yield crc(changed) ^ expected


if __name__ == "__main__":
    release = json.loads((HERE / "evidence.json").read_text())
    records = {r["checksum"]: r for r in release["weather_records"] if r["kind"] == "ordinary"}
    blocks = received_text()
    for counter, phase_zero_crc, phase_two_crc in (
        (43854889, "5701", "ea16"),
        (43854896, "50b5", "71c2"),
    ):
        first = list(single_bit_errors(records[phase_zero_crc], blocks, 3 * counter))
        second = list(single_bit_errors(records[phase_two_crc], blocks, 3 * counter + 2))
        paired = [(a << 16) | b for a, b in zip(first, second, strict=True)]
        print(f"{counter}: rejected one-bit errors {sum(map(bool, first))}/{len(first)} "
              f"and {sum(map(bool, second))}/{len(second)}; "
              f"individual ranks {binary_rank(first)}, {binary_rank(second)}; combined rank {binary_rank(paired)}")
