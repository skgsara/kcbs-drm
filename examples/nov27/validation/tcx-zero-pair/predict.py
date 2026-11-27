"""Predict TS 26.443 TCX20 filler from contiguous 128-bit EVS word prefixes."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import tempfile

PAYLOAD_OFFSETS = (15, 18, 21, 24, 27, 30)


def field(word, start, width):
    if not (0 <= start and width >= 0 and start + width <= 8*len(word)):
        raise ValueError("field extends outside supplied prefix")
    return (int.from_bytes(word, "big") >> (8*len(word)-start-width)) & ((1 << width)-1)


def primary_tcx20(prefix):
    return prefix[0] >> 3 >= 29 and bool(prefix[0] & 4)


def decide(prefix, native):
    if len(prefix) != 16:
        raise ValueError("exactly 128 physical word bits required")
    if not primary_tcx20(prefix):
        return {"reason": "not_primary_tcx20"}
    if native is None:
        return {"reason": "prefix_bound_or_native_abstention"}

    start, width, lines, mapped, budget, residual_limit, ber, bfi = native
    expected_lines = (160, 320, 640)[(prefix[0] >> 3)-29]
    if field(prefix, 8, 1) == 0:
        expected_lines += expected_lines//4
    if (start < 8 or budget <= 0 or start + budget != 264 or mapped not in (0, 1)
            or lines != expected_lines or width != (lines//2-1).bit_length()
            or residual_limit != 100 or ber or bfi):
        return {"reason": "unsupported_native_configuration"}
    fields = {"start": start, "width": width, "lines": lines, "mapped": bool(mapped)}
    if mapped:
        return dict(fields, reason="harmonic_mapping_on")
    arithmetic_start = start + width
    if arithmetic_start + 3 > 128:
        return dict(fields, reason="prefix_too_short")
    count_code = field(prefix, start, width)
    if count_code:
        return dict(fields, reason="more_than_one_pair", tuple_count=count_code+1)
    if field(prefix, arithmetic_start, 3) != 0b101:
        return dict(fields, reason="different_single_pair")

    begin, end = arithmetic_start+3, 264-residual_limit
    if begin >= end:
        return dict(fields, reason="empty_fill")
    if field(prefix, begin, min(128, end)-begin):
        return dict(fields, reason="known_filler_contradiction")
    offsets = {str(o): 0 for o in PAYLOAD_OFFSETS if begin <= 8*(o+1) and 8*(o+2) <= end}
    return dict(fields, reason="one_zero_pair", zero_interval=[begin, end],
                predicted_payload_offsets=offsets)


def observe(binary, stream, prefix):
    symbols = [0x81 if octet & (128 >> bit) else 0x7f for octet in prefix for bit in range(8)]
    stream.write_bytes(struct.pack("<130H", 0x7777, 128, *symbols))
    try:
        result = subprocess.run([binary, "-q", "-no_delay_cmp", "16", stream, os.devnull],
                                capture_output=True, timeout=10)
    except subprocess.TimeoutExpired:
        return {"reason": "native_timeout"}
    if result.returncode in (42, 44):
        return decide(prefix, None)
    if result.returncode != 45:
        return {"reason": "native_failure", "status": result.returncode}

    receipts = [line for line in result.stderr.splitlines() if line.startswith(b"PREFIX_META,")]
    if len(receipts) != 1:
        raise ValueError("missing or duplicate native cursor receipt")
    fields = tuple(map(int, receipts[0].split(b",")[1:]))
    if len(fields) != 8:
        raise ValueError("invalid native metadata")
    return decide(prefix, fields)


def predict(binary, rows):
    if not isinstance(rows, list):
        raise ValueError("expected a JSON array")
    seen = set()
    decisions = []
    with tempfile.TemporaryDirectory() as tmp:
        stream = Path(tmp)/"prefix.192"
        for row in rows:
            if (not isinstance(row, dict) or set(row) != {"slot", "prefix_hex"}
                    or type(row["slot"]) is not int or row["slot"] < 0
                    or not isinstance(row["prefix_hex"], str)):
                raise ValueError("each row needs a nonnegative integer slot and a hex prefix")
            slot = row["slot"]
            if slot in seen:
                raise ValueError(f"duplicate slot {slot}")
            seen.add(slot)
            prefix = bytes.fromhex(row["prefix_hex"])
            if len(prefix) != 16:
                raise ValueError("expected exactly 128 supplied bits")
            decision = observe(binary, stream, prefix) if primary_tcx20(prefix) else decide(prefix, None)
            decisions.append(dict(slot=slot, **decision))
    return decisions


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("observer", type=Path)
    parser.add_argument("prefixes", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    if args.output.resolve() in {args.prefixes.resolve(), args.observer.resolve()}:
        raise ValueError("write decisions to a separate output file")
    raw = args.prefixes.read_bytes()
    result = dict(format="evs13k2-prefix-filler-v1", prefixes_sha256=hashlib.sha256(raw).hexdigest(),
                  rules_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  observer_sha256=hashlib.sha256(args.observer.read_bytes()).hexdigest(),
                  rows=predict(args.observer.resolve(), json.loads(raw)))
    encoded = (json.dumps(result, sort_keys=True, separators=(",", ":"))+"\n").encode()
    args.output.write_bytes(encoded)
    print(hashlib.sha256(encoded).hexdigest())


if __name__ == "__main__":
    main()
