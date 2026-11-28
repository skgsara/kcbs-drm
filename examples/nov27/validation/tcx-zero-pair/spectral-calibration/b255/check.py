"""Check how the reference TCX decoder consumes physical bit 255 on fifteen fully known P1s."""
import argparse
from collections import Counter
from hashlib import sha256
from importlib.util import module_from_spec, spec_from_file_location
import json
from pathlib import Path
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
spec = spec_from_file_location("spectral_calibration", HERE.parent / "check.py")
calibration = module_from_spec(spec)
spec.loader.exec_module(calibration)


def decode(observer, stock, stream, directory):
    source = directory / "words.192"
    source.write_bytes(stream)
    traces = {}
    observed = directory / "observed.pcm"
    reference = directory / "stock.pcm"
    for executable, output in ((stock, reference), (observer, observed)):
        result = subprocess.run([executable, "-q", "-no_delay_cmp", "16", source, output],
                                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True)
    for line in result.stderr.splitlines():
        if not line.startswith(b"B255_"):
            continue
        event, slot, *values = line.decode("ascii").split(",")
        record = traces.setdefault(int(slot), {})
        if event in record:
            raise ValueError(f"duplicate {event} for slot {slot}")
        record[event] = values
    pcm = observed.read_bytes()
    if pcm != reference.read_bytes():
        raise ValueError("observer PCM differs from stock decoder")
    return traces, pcm


def interpret(trace, expected_bit):
    spectrum_start, spectrum_end, sign_start, sign_end, res_start, res_end = map(int, trace["B255_RANGES"])
    if not spectrum_start <= 255 < spectrum_end:
        raise ValueError("b255 outside main spectral range")
    role, index, count, value = trace["B255_ROLE"]
    index, count, value = int(index), int(count), int(value)
    ranges = (spectrum_start, spectrum_end, sign_start, sign_end, res_start, res_end)
    if role == "sign":
        if not sign_start <= 255 < sign_end or count <= 0 or value != count * (1 - 2 * expected_bit):
            raise ValueError("inconsistent signed coefficient")
        return ("coefficient_sign", index, None), value, ranges
    if role != "residual" or not res_start <= 255 < res_end or count != res_end - res_start:
        raise ValueError("unexpected residual range")
    use, consumer_index, bin_index, operand = trace["B255_USE"]
    if index != res_end - 1 - 255 or index != int(consumer_index) or value != int(operand) or value != expected_bit:
        raise ValueError("backward residual read and inverse-quantizer operand disagree")
    return (use, int(bin_index), index), value, ranges


def run(observer, stock, directory):
    groups = calibration.read_fixture()
    before = calibration.make_stream(groups, None)
    if sha256(before).hexdigest() != calibration.ORIGINAL_SHA256:
        raise ValueError("original chronological fixture failed its digest check")
    original, pcm_a = decode(observer, stock, before, directory)
    modified, pcm_b = decode(observer, stock, calibration.make_stream(groups, 30), directory)
    if len(pcm_a) != calibration.SLOTS * 640 or len(pcm_a) != len(pcm_b):
        raise ValueError("wrong output clock for chronological replay")
    rows = []
    cold_matches = 0
    for cycle, word in enumerate(groups[calibration.TARGET]):
        index = calibration.TARGET_START + 4 * cycle
        bit = word[31] & 1
        address, operand_a, layout = interpret(original[index], bit)
        address_b, operand_b, layout_b = interpret(modified[index], bit ^ 1)
        if address != address_b or layout != layout_b or operand_a == operand_b:
            raise ValueError(f"fixed b255 flip did not isolate the same field at cycle {cycle}")
        isolated = calibration.GOOD + b"".join(calibration.BYTE_SYMBOLS[b] for b in word)
        cold, _ = decode(observer, stock, isolated, directory)
        cold_address, cold_value, cold_layout = interpret(cold[0], bit)
        cold_matches += (cold_address, cold_value, cold_layout) == (address, operand_a, layout)
        window = slice(index * 640, (index + 1) * 640)
        rows.append(dict(cycle=cycle, mode=f"{word[0]:02X}", original_b255=bit, operation=address[0],
                         coefficient_bin=address[1], residual_index=address[2],
                         original_operand=operand_a, flipped_operand=operand_b, pcm_changed=pcm_a[window] != pcm_b[window]))
    return dict(counter=calibration.TARGET, position=1, original_g192_sha256=calibration.ORIGINAL_SHA256,
                operation_counts=dict(Counter(row["operation"] for row in rows)), same_address_after_flip=len(rows),
                same_address_operand_and_ranges_from_cold=cold_matches, rows=rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--observer", type=Path, required=True)
    parser.add_argument("--stock", type=Path, required=True, help="unmodified floating-point EVS_dec")
    args = parser.parse_args()
    observer, stock = args.observer.resolve(), args.stock.resolve()
    try:
        with tempfile.TemporaryDirectory() as tmp:
            result = run(observer, stock, Path(tmp))
        expected = json.loads((HERE / "expected.json").read_text(encoding="utf-8"))
        match = result == expected
        print(json.dumps(dict(matches_expected=match, observer_sha256=sha256(observer.read_bytes()).hexdigest(),
                              stock_sha256=sha256(stock.read_bytes()).hexdigest(), result=result), indent=2))
        return 0 if match else 1
    except (KeyError, ValueError, OSError, subprocess.CalledProcessError) as error:
        print(str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
