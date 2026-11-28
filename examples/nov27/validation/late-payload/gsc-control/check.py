"""Test a fixed GSC codebook bound on two synthetic WB sender streams."""

import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

import numpy as np

from bounded import build
from stimuli import make_pcm, synthesize

HERE = Path(__file__).resolve().parent
DECODER_OPTIONS = ["-q", "-no_delay_cmp", "16"]


def digest(data):
    return hashlib.sha256(data).hexdigest()


def physical_position(start, width, logical_bit):
    """Position of a raw index bit, numbered from its least significant bit."""
    if width <= 16:
        return start + width - 1 - logical_bit
    # TS 26.443 reads the upper chunk first from the higher address.
    if logical_bit < 16:
        return start + 15 - logical_bit
    return start + width + 15 - logical_bit


def census(trace, expected):
    predicted = []
    intersections = Counter()
    for line in trace.splitlines():
        if not line.startswith(b"N,"):
            continue
        slot, size, high, width, start = map(int, line.split(b",")[1:])
        for offset, base in [(24, 200), (27, 224)]:
            relevant = {}
            for bit in range(width):
                position = physical_position(start, width, bit)
                if base <= position < base + 8:
                    relevant[bit] = position
            if not relevant:
                continue
            intersections[offset] += 1
            remainder = size % (1 << width)
            if high != size >> width or sum(1 << bit for bit in relevant) < remainder:
                continue
            zeros = sorted(position for bit, position in relevant.items() if 1 << bit >= remainder)
            assert (offset, size, high, width, start, zeros) == (27, 142544, 139, 10, 230, [230, 231])
            predicted.append((slot, size, high, width, start))
    for offset in (24, 27):
        assert intersections[offset] == expected[f"prefix_p{offset}_indices"]
    assert [row[0] for row in predicted] == expected["prefix_p27_slots"]
    return intersections, predicted


def cold_controls(decoder, record, low, size, high, width, work):
    """Give the native decoder one word per process, resetting history each time."""
    output = []
    single = work / "single.192"
    environment = {**os.environ, "GSC_CONTROL_CHECK": "1"}
    for pair in range(4):
        symbols = record.copy()
        # Two G.192 header symbols precede the 264 physical bits.
        symbols[2 + 230] = 0x81 if pair & 2 else 0x7F
        symbols[2 + 231] = 0x81 if pair & 1 else 0x7F
        single.write_bytes(symbols.tobytes())
        run = subprocess.run(
            [decoder, *DECODER_OPTIONS, single, work / "single.raw"],
            check=True, capture_output=True, env=environment,
        )
        lines = run.stderr.splitlines()
        index = (high << width) + (pair << 8) + (low & 0xFF)
        assert b"N,0,142544,139,10,230" in lines
        assert f"I,{size},{index},0".encode() in lines
        rejected = f"F,{index}".encode() in lines
        assert rejected == (pair != 0)
        output.append(dict(pair=pair, native_index=index, reference_range_error=rejected))
    return output


def verify_stream(expected, encoder, decoder, work):
    rate = expected["rate_khz"]
    pcm = make_pcm() if rate == 32 else synthesize().astype("<i2").tobytes()
    assert digest(pcm) == expected["pcm_sha256"]
    source = work / "input.raw"
    stream = work / "original.192"
    decoded = work / "decoded.raw"
    source.write_bytes(pcm)
    subprocess.run(
        [encoder, "-q", "-no_delay_cmp", "-max_band", "WB", "13200", str(rate), source, stream],
        check=True, capture_output=True,
    )
    encoded = stream.read_bytes()
    assert digest(encoded) == expected["g192_sha256"]
    trace = subprocess.run(
        [decoder, *DECODER_OPTIONS, stream, decoded], check=True, capture_output=True,
    )
    assert digest(decoded.read_bytes()) == expected["decoder_pcm_sha256"]
    # Freeze the stateful prefix-only predictions before inspecting the held-back indices.
    intersections, predicted = census(trace.stderr, expected)
    frames = expected["frames"]
    words = np.frombuffer(encoded, dtype="<u2").reshape(frames, 266)
    assert np.all(words[:, 0] == 0x6B21) and np.all(words[:, 1] == 264)
    assert np.all(np.isin(words[:, 2:], [0x7F, 0x81]))
    bits = words[:, 2:] == 0x81
    hashes = hashlib.sha256()
    rows = []
    for slot, size, high, width, start in predicted:
        prefix = np.packbits(bits[slot, :128]).tobytes()
        assert digest(prefix) == expected["prefix_sha256_by_slot"][str(slot)]
        hashes.update(prefix)
        residual = 0
        for bit in bits[slot, start:start + width]:
            residual = (residual << 1) | int(bit)
        pair = residual >> 8
        decisions = [
            ((high << width) + (value << 8) + (residual & 0xFF)) < size
            for value in range(4)
        ]
        assert pair == expected["expected_pair"] == 0 and decisions == [True, False, False, False]
        checks = cold_controls(decoder, words[slot], residual, size, high, width, work)
        rows.append(dict(
            zero_based_slot=slot,
            ordinal_position=1 + slot % 4,
            prefix_sha256=digest(prefix),
            held_back_pair=pair,
            original_10bit_index_residual=residual,
            index_bound_checks_for_00_01_10_11=decisions,
            reset_native_controls=checks,
        ))
    assert hashes.hexdigest() == expected["selected_128bit_prefixes_sha256"]
    assert [row["original_10bit_index_residual"] for row in rows] == expected["expected_true_10bit_residuals"]
    for pair in range(4):
        errors = sum(row["reset_native_controls"][pair]["reference_range_error"] for row in rows)
        assert errors == expected["native_range_errors_by_pair_00_01_10_11"][pair]
    return dict(
        frames=frames,
        stateful_prefix_certified_intersections=intersections,
        selected_prefixes_sha256=hashes.hexdigest(),
        comparisons=rows,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True, help="pristine TS 26.443 c-code directory")
    parser.add_argument("--encoder", type=Path, required=True, help="stock floating-point EVS_cod")
    parser.add_argument("--out", type=Path, help="optional JSON output file")
    args = parser.parse_args()
    expected = json.loads((HERE / "expected.json").read_text())
    results = {}
    with tempfile.TemporaryDirectory() as temp:
        work = Path(temp)
        decoder = build(work, args.source.resolve())
        for name, fixture in expected.items():
            results[name] = verify_stream(fixture, args.encoder.resolve(), decoder, work)
    data = json.dumps(results, indent=2) + "\n"
    if args.out:
        args.out.write_text(data)
    print(data, end="")


if __name__ == "__main__":
    main()
