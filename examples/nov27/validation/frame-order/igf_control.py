"""Reproduce bounded TCX20 IGF whitening reads in the 15 published P2 prefixes of group 43865914."""
import argparse
from collections import Counter
from hashlib import sha256
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
BOUNDED = HERE.parent / "tcx-zero-pair"
sys.path.insert(0, str(BOUNDED))
from build import EXPECTED_SOURCE, instrument, replace

FIXTURE = BOUNDED / "43865914-p2-prefixes.json"
FIXTURE_SHA = "2d735ba5018a85721c071b6136ca43c05432565de53bd53f081827a951dd2e8d"
LEVELS = {"MID": "0", "OFF": "10", "STRONG": "11"}


def canonical(first, second):
    return LEVELS[first] + ("0" if first == second else "1" + LEVELS[second])


def build_observer(src, output):
    """Reuse the source-pinned 128-bit guard and stop at the existing main-spectrum marker."""
    folders = [src / name for name in ("lib_com", "lib_dec", "lib_enc")]
    files = sorted(p for folder in folders for p in folder.iterdir()
                   if p.suffix == ".h" or (p.suffix == ".c" and folder.name != "lib_enc"))
    tree = sha256()
    for p in files:
        tree.update(p.relative_to(src).as_posix().encode("ascii") + b"\0" + sha256(p.read_bytes()).digest())
    if tree.hexdigest() != EXPECTED_SOURCE:
        raise ValueError("requires the original-byte November 4, 2021 TS 26.443 source tree")
    changes = {
        "igf_dec.c": [
            ("IGFAllZero    = get_next_indice(st, 1);",
             'fprintf(stderr, "IGF_ENVELOPE %d\\n", st->next_bit_pos);'),
            ("tmp          = -1;",
             'fprintf(stderr, "IGF_WHITE %d %d %d %d\\n", st->next_bit_pos, igfGridIdx, isIndepFrame, nT);'),
            ("IGF_decode_temp_flattening_trigger(st, hInstance);",
             'fprintf(stderr, "IGF_FLAT %d %d %d\\n", st->next_bit_pos, hPrivateData->currWhiteningLevel[0], hPrivateData->currWhiteningLevel[1]);'),
        ],
        "igf_scf_dec.c": [
            ("get_next_indice_tmp(st, -14);",
             'fprintf(stderr, "IGF_REWIND %d\\n", st->next_bit_pos);'),
        ],
    }
    intercepted = set(changes) | {"bitstream.c", "io_dec.c", "ACcontextMapping_dec.c", "decoder.c"}
    with tempfile.TemporaryDirectory() as td:
        inputs = []
        for path in files:
            if path.suffix != ".c":
                continue
            if path.name not in intercepted:
                inputs.append(path)
                continue
            code = instrument(path.name, path.read_text())
            if path.name in changes:
                code = "#include <stdio.h>\n" + code
                for anchor, event in changes[path.name]:
                    code = replace(code, anchor, event + "\n        " + anchor)
            copy = Path(td) / path.name
            copy.write_text(code)
            inputs.append(copy)
        output.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["gcc", "-O2", "-std=gnu99", "-fno-strict-aliasing",
                        *[f"-I{folder}" for folder in folders], *inputs, "-lm", "-o", output], check=True)


def lane(bit):
    # Mode octet 0, then 32 payload octets. Payload offsets 0, 3, ... are masked.
    return "supported_prefix" if bit >= 8 and (bit // 8 - 1) % 3 == 0 else "direct"


def observe(reader, stream, slot, prefix):
    bits = "".join(f"{b:08b}" for b in prefix)
    symbols = [0x81 if b == "1" else 0x7f for b in bits]
    stream.write_bytes(struct.pack("<130H", 0x7777, 128, *symbols))
    proc = subprocess.run([reader, "-q", "-no_delay_cmp", "16", stream, os.devnull],
                          capture_output=True, text=True, timeout=10)
    if proc.returncode != 45:
        raise ValueError(f"slot {slot}: bounded decoder did not reach the main spectrum ({proc.returncode})")

    def event(name):
        rows = [line.split()[1:] for line in proc.stderr.splitlines() if line.startswith(name + " ")]
        if len(rows) != 1:
            raise ValueError(f"slot {slot}: expected one {name} marker")
        return tuple(map(int, rows[0]))

    start, = event("IGF_ENVELOPE")
    rewind_from, = event("IGF_REWIND")
    w, grid, independent, tiles = event("IGF_WHITE")
    flat, first, second = event("IGF_FLAT")
    spectral = [line.split(",")[1:] for line in proc.stderr.splitlines() if line.startswith("PREFIX_META,")]
    if len(spectral) != 1 or len(spectral[0]) != 8:
        raise ValueError(f"slot {slot}: missing bounded spectral cursor")
    end, _, _, _, _, _, ber, bfi = map(int, spectral[0])
    if (not 8 <= start < w <= flat < end <= 128 or not 0 <= rewind_from <= 128 or
            rewind_from - 14 != w or end != flat + 1 or independent != 1 or tiles != 2 or
            grid not in (0, 1) or ber or bfi or bits[start] != "0"):
        raise ValueError(f"slot {slot}: unexpected native IGF configuration or boundary")
    codes = ("OFF", "MID", "STRONG")
    if first not in range(3) or second not in range(3):
        raise ValueError(f"slot {slot}: unknown whitening level")
    first_name, second_name = codes[first], codes[second]
    observed = bits[w:flat]
    if observed != canonical(first_name, second_name):
        raise ValueError(f"slot {slot}: decoded levels do not give the original canonical whitening code")
    return dict(slot=slot, igf_start=start, whitening_start=w, whitening_code=observed,
                levels=[first_name, second_name], whitening_bit_lanes=[lane(i) for i in range(w, flat)],
                pre_whitening_read_end_exclusive=rewind_from, flattening_bit=int(bits[flat]),
                igf_end_exclusive=end)


def check(reader):
    raw = FIXTURE.read_bytes()
    if sha256(raw).hexdigest() != FIXTURE_SHA:
        raise ValueError("unexpected archived prefix file")
    settings = json.loads(raw)
    if [row["slot"] for row in settings] != list(range(1, 60, 4)):
        raise ValueError("expected 15 position-two slots in chronological order")
    with tempfile.TemporaryDirectory() as td:
        rows = []
        for item in settings:
            prefix = bytes.fromhex(item["prefix_hex"])
            if len(prefix) != 16 or prefix[0] < 0xfc:
                raise ValueError("expected a 128-bit ordinary SWB TCX20 prefix")
            rows.append(observe(reader, Path(td) / "prefix.192", item["slot"], prefix))
    counts = Counter(row["whitening_code"] for row in rows)
    lanes = Counter(l for row in rows for l in row["whitening_bit_lanes"])
    if any(row["igf_end_exclusive"] > 128 for row in rows):
        raise ValueError("IGF extends into unsupported bytes")
    return dict(counter=43865914, prefix_sha256=FIXTURE_SHA, source_tree_sha256=EXPECTED_SOURCE,
                words=len(rows), whitening_codes=counts, whitening_bits_by_lane=lanes,
                legal_whitening_codes_after_first_tile_OFF=sorted(canonical("OFF", second) for second in LEVELS),
                first_unresolved_bit=128, unresolved_suffix_bits_checked=0, rows=rows)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build")
    build.add_argument("source", type=Path)
    build.add_argument("observer", type=Path)
    score = sub.add_parser("check")
    score.add_argument("observer", type=Path)
    score.add_argument("output", type=Path)
    a = p.parse_args()
    if a.command == "build":
        build_observer(a.source.resolve(), a.observer.resolve())
    else:
        if a.output.resolve() in (a.observer.resolve(), FIXTURE.resolve()):
            p.error("write the report to a separate path")
        a.output.write_text(json.dumps(check(a.observer.resolve()), indent=2) + "\n")


if __name__ == "__main__":
    main()
