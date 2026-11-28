"""Verify one original SWB GSC sender word and its prefix-only p24 codebook bound."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

import numpy as np

from waveform import ANCHOR, waveform

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "late-payload/gsc-control"))
import bounded

SLOT = ANCHOR + 2
FRAME_BYTES = 532
OPTIONS = ["-q", "-no_delay_cmp", "16"]
PCM_SHA = "f91d847d3fb1ee0a208d27d4011a03c60e0c21e12926cb06b33f7dce51d49961"
G192_SHA = "aefe48d266f8c0a4fb1bef3717d5bc9ef18b30bc77ec0c8b5c6db232be4b7010"


def digest(data):
    return hashlib.sha256(data).hexdigest()


def build_observer(work, source):
    # Only the optional trace of the native error branch moves to this fixed
    # control's field. The 128-bit allocation walk is the published checker.
    original = bounded.patch_vector

    def select_this_field(text):
        patched = original(text)
        marker = "st->rc_offset == 230"
        if patched.count(marker) != 2:
            raise ValueError("Unexpected reference-error observer anchors")
        return patched.replace(marker, "st->rc_offset == 204")

    bounded.patch_vector = select_this_field
    try:
        return bounded.build(work, source)
    finally:
        bounded.patch_vector = original


def decoded_trace(executable, stream, pcm):
    return subprocess.run(
        [executable, *OPTIONS, stream, pcm], check=True, capture_output=True,
        env={**os.environ, "GSC_CONTROL_CHECK": "1"},
    ).stderr.splitlines()


def expect_prefix(trace, slot):
    # P is emitted only after checking every preceding current-word read;
    # N is emitted by the bounded native walk before consulting the raw residual.
    assert f"P,{slot},89,89".encode() in trace
    assert f"N,{slot},142544,139,10,204".encode() in trace


def run(source, encoder, work):
    pcm = waveform()
    assert digest(pcm) == PCM_SHA
    input_path = work / "input.s16"
    input_path.write_bytes(pcm)
    stream = work / "sender.192"
    subprocess.run(
        [encoder, "-q", "-no_delay_cmp", "-max_band", "SWB", "13200", "32", input_path, stream],
        check=True, capture_output=True,
    )
    encoded = stream.read_bytes()
    assert len(encoded) == (SLOT + 1) * FRAME_BYTES and digest(encoded) == G192_SHA
    all_words = np.frombuffer(encoded, dtype="<u2").reshape(-1, 266)
    assert np.all(all_words[:, 0] == 0x6B21) and np.all(all_words[:, 1] == 264)
    assert np.all(np.isin(all_words[:, 2:], [0x7F, 0x81]))
    selected = all_words[SLOT]
    observer = build_observer(work, source)
    rendered = work / "decoded.s16"
    expect_prefix(decoded_trace(observer, stream, rendered), SLOT)
    stateful_pcm = digest(rendered.read_bytes())

    single = work / "one.192"
    single.write_bytes(selected.tobytes())
    expect_prefix(decoded_trace(observer, single, rendered), 0)
    # Two diagnostic completions of the KNOWN synthetic word demonstrate that
    # the predictor observes the same field even if every suffix bit changes.
    for marker in (0x7F, 0x81):
        test = selected.copy()
        test[2 + 128:] = marker
        single.write_bytes(test.tobytes())
        expect_prefix(decoded_trace(observer, single, rendered), 0)

    size, high, width, start = 142544, 139, 10, 204
    limit = size - (high << width)
    surviving = [value for value in range(256) if ((value & 15) << 6) < limit]
    assert limit == 208 and len(surviving) == 64
    assert sorted({value & 15 for value in surviving}) == [0, 1, 2, 3]

    # Compare with the held-back sender bits after the prediction.
    bits = selected[2:] == 0x81
    word = np.packbits(bits).tobytes()
    prefix_hash = digest(word[:16])
    assert prefix_hash == "989688191c2dd49c33ab7e99e80d97a450b1644cc2a7dc14056225fc71cd12aa"
    value = 0
    for bit in bits[start:start + width]:
        value = (value << 1) | int(bit)
    assert word[0] == 0x6C and word[25] == 0x83 and value == 195
    controls = []
    for nibble in range(16):
        trial = selected.copy()
        for offset in range(4):
            trial[2 + start + offset] = 0x81 if nibble & (8 >> offset) else 0x7F
        single.write_bytes(trial.tobytes())
        trace = decoded_trace(observer, single, rendered)
        expect_prefix(trace, 0)
        index = (high << width) + (nibble << 6) + (value & 63)
        assert f"I,{size},{index},0".encode() in trace
        failed = f"F,{index}".encode() in trace
        assert failed == (index >= size) == (nibble >= 4)
        controls.append(dict(low_nibble=nibble, stock_index=index, native_range_error=failed))

    copies = int(np.all(all_words[:, 2:] == selected[2:], axis=1).sum())
    prefix_copies = int(np.all(all_words[:, 2:130] == selected[2:130], axis=1).sum())
    assert (copies, prefix_copies) == (1, 1)
    return {
        "sender": {"pcm_sha256": PCM_SHA, "g192_sha256": G192_SHA, "words": len(all_words),
                   "input_sample_rate_hz": 32000, "input_samples": len(pcm) // 2,
                   "stateful_observer_pcm_sha256": stateful_pcm},
        "word": {"zero_based_slot": SLOT, "ordinal_in_four_slot_group": 1 + SLOT % 4,
                 "mode_hex": word[:1].hex(), "sender_word_hex": word.hex(),
                 "prefix_128bit_sha256": prefix_hash, "full_word_copies_in_replay": copies,
                 "same_prefixes_in_replay": prefix_copies},
        "prefix_prediction": {"available_physical_bits": [0, 128], "pre_pvq_read_highwater": 89,
                              "history_conditions": ["complete sender timeline", "cold one-word reset"],
                              "cold_same_prediction_for_uniform_suffixes": ["zero", "one"],
                              "target_payload_offset": 24, "target_physical_interval": [200, 208],
                              "mpvq_dimension": 16, "pulses": 5, "codebook_size": size,
                              "upper_symbol": high, "residual_interval": [204, 214],
                              "residual_limit_exclusive": limit, "forced_zero_physical_bits": [204, 205],
                              "allowed_low_nibbles": [0, 1, 2, 3], "remaining_octets": len(surviving)},
        "sender_comparison": {"original_payload24_hex": word[25:26].hex(),
                              "actual_residual": value, "actual_index": (high << width) + value,
                              "reset_controls": controls},
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True, help="pristine floating-point TS 26.443 c-code")
    parser.add_argument("--encoder", type=Path, required=True, help="standard floating-point EVS_cod")
    parser.add_argument("--out", type=Path, help="optional JSON report")
    args = parser.parse_args()
    if not __debug__:
        parser.error("Run with Python assertions enabled.")
    with tempfile.TemporaryDirectory() as temp:
        result = run(args.source.resolve(), args.encoder.resolve(), Path(temp))
    published = HERE / "result.json"
    if published.is_file():
        assert result == json.loads(published.read_text())["single_word_replay"]
    output = json.dumps(result, indent=2) + "\n"
    if args.out:
        args.out.write_text(output)
    print(output, end="")


if __name__ == "__main__":
    main()
