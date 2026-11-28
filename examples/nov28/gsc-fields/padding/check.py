"""Prove the b223 zero-fill bound and check legal indices with the stock TS 26.443 encoder."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import tempfile

HERE = Path(__file__).resolve().parent
PINS = {
    "lib_com/bitstream.c": "801448e98e002c31cd6c9a626b73e4eb6e0b9bf929875725ae53a7b90200a6cc",
    "lib_com/pvq_com.c": "ec71a7c1cfe4ea44cb21796808eacd3659b4cc4c4f790035fd1d3934fc709608",
    "lib_com/range_com.c": "ec46d6c3f2a26874668cfc99c505bed894e1ff3f670ac7e3602d5c30696584e5",
    "lib_com/tools.c": "b20cd52fe6f850352bcdbf66b528df5e35e6807a98cce21829cdd0c47229ec03",
    "lib_enc/range_enc.c": "b82a4cf45976dbb83150e8c017cfed6ceaaed68653b0296248011e4d884e5062",
}


def symbol_unit(width, total):
    """TS 26.443 UL_inverse and UMult_32_32, followed by the rc_encode shift."""
    leading_zeros = 32 - total.bit_length()
    error = 0xffffffff - (total << leading_zeros)
    reciprocal = 0x80000000
    for _ in range(5):
        reciprocal += (reciprocal * error) >> 32
        error = (error * error) >> 32
    return ((width * reciprocal) >> 32) >> (31 - leading_zeros)


def geometry():
    width = 0xffffffff
    steps = []
    renormalized = 0
    for total in (256, 256, 256, 256, 172):
        unit = symbol_unit(width, total)
        width = unit  # All five arithmetic symbols have frequency one.
        shift = 0
        while width < 1 << 24:
            width <<= 8
            shift += 8
        renormalized += shift
        steps.append({"total": total, "unit": unit, "shift_bits": shift, "width": width})

    available = 51 - 9 - renormalized
    base = 1 + (32 - width.bit_length())
    terminators = [min(available, base), min(available, base + 1)]
    fill = [available - terminators[1], available - terminators[0]]
    if renormalized != 32 or terminators != [8, 9] or fill != [1, 2]:
        raise ValueError("the mathematical derivation differs from the expected geometry")
    return {"steps": steps, "renormalization_bits": renormalized, "backward_raw_bits": 9,
            "termination_bits": terminators, "zero_fill_bits": fill, "guaranteed_zero_bit": 223}


def native(source, math):
    for name, expected in PINS.items():
        if sha256((source / name).read_bytes()).hexdigest() != expected:
            raise ValueError(f"reference source digest differs for {name}")
    with tempfile.TemporaryDirectory() as folder:
        exe = Path(folder) / "stock"
        includes = ["-I" + str(source / subdir) for subdir in ("lib_com", "lib_enc", "lib_dec")]
        subprocess.run(["gcc", "-O2", "-std=gnu99", "-fno-strict-aliasing",
                        "-ffunction-sections", "-fdata-sections", "-Wl,--gc-sections", *includes,
                        HERE / "stock.c", *(source / name for name in PINS), "-lm", "-o", exe], check=True)
        lines = subprocess.check_output([exe], text=True).splitlines()
    records = {"range": [], "count": [], "witness": []}
    for line in lines:
        label, *values = line.split()
        records[label].append(tuple(map(int, values)))
    if records["range"] != [(step["width"],) for step in math["steps"]]:
        raise ValueError("stock ranges differ from the mathematical derivation")
    counts = [{"zero_fill_bits": fill, "b222": a, "b223": 0, "trials": n}
              for fill, a, n in records["count"]]
    if sum(row["trials"] for row in counts) != 2000 or len(records["witness"]) != 5:
        raise ValueError("incomplete native test output")
    return {"trials": counts, "b222_one_witness": [
        {"index": index, "leading_sign": sign} for index, sign in records["witness"]]}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("source", type=Path, help="root of the TS 26.443 floating-point c-code directory")
    ap.add_argument("--out", type=Path, help="write JSON here (default: standard output)")
    args = ap.parse_args()
    math = geometry()
    try:
        result = {"source_sha256": PINS, "geometry": math, "native": native(args.source.resolve(), math)}
        text = json.dumps(result, indent=2) + "\n"
        if args.out:
            args.out.write_text(text, encoding="utf-8")
        else:
            print(text, end="")
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        ap.exit(1, f"{ap.prog}: {exc}\n")


if __name__ == "__main__":
    main()
