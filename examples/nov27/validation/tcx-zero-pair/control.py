"""Generate the independent sender control, freeze prefix-only decisions, and score."""
import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import random
import struct
import subprocess
import sys

HERE = Path(__file__).resolve().parent
PCM_SHA = "6f2c7e35413894352caadb2080a8cf62e1c722d175d552e6682d48b500c51220"
G192_SHA = "5a190260c38a01024ca0fb4091d5725b711709ad3c97d474a352649961dfb256"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def make_pcm():
    rng = random.Random(202611271328)
    data = bytearray()
    rate = 32000
    phase = 2 * math.pi
    for second in range(18):
        for i in range(rate):
            t = i / rate
            if second % 3 == 0:
                sample = (.48 * math.sin(phase * (213*t + 41*t*t))
                          + .28 * math.cos(phase * (733*t + 75*t*t))
                          + .16 * math.sin(phase * (1233*t + 141*t*t))
                          + .06 * math.sin(phase * 9371*t))
            elif second % 3 == 1:
                sample = (rng.random()*2 - 1) * (.2 + .7*math.sin(phase*(2+second*.31)*t)**2)
            else:
                sample = 0.0
            data.extend(struct.pack("<h", round(13000 * sample)))
    return bytes(data)


def export_prefixes(source, target):
    rows = []
    with source.open("rb") as f:
        while (header := f.read(4)):
            if header != struct.pack("<HH", 0x6b21, 264):
                raise ValueError("expected a good-marked 264-bit G.192 record")
            symbols = struct.unpack("<128H", f.read(256))
            if set(symbols) - {0x7f, 0x81}:
                raise ValueError("bad G.192 prefix symbol")
            bits = "".join("1" if v == 0x81 else "0" for v in symbols)
            rows.append({"slot": len(rows), "prefix_hex": int(bits, 2).to_bytes(16, "big").hex()})
            f.seek(2*(264-128), 1)
        if f.tell() != source.stat().st_size:
            raise ValueError("short final G.192 record")
    target.write_text(json.dumps(rows, separators=(",", ":")) + "\n")


def score(decisions, frozen, sender):
    packed = decisions.read_bytes()
    if sha(packed) != frozen:
        raise ValueError("decisions changed after the prediction receipt was written")
    rows = json.loads(packed)["rows"]
    raw = sender.read_bytes()
    if sha(raw) != G192_SHA or len(raw) != len(rows) * 532:
        raise ValueError("different original G.192 answer stream")
    reasons = Counter(row["reason"] for row in rows)
    counts = Counter()
    positions = Counter()
    for slot, row in enumerate(rows):
        if row["slot"] != slot:
            raise ValueError("slot alignment changed")
        if row["reason"] != "one_zero_pair":
            continue
        if row["predicted_payload_offsets"] != {"15": 0, "18": 0}:
            raise ValueError("unexpected two-byte prediction for this control")
        symbols = struct.unpack_from("<264H", raw, slot*532 + 4)
        if set(symbols) - {0x7f, 0x81}:
            raise ValueError("invalid answer symbols")
        start, stop = row["zero_interval"]
        if not (0 < start <= 128 < stop == 164):
            raise ValueError("invalid filler interval")
        counts["all_fill_bits"] += stop-start
        counts["beyond_prefix_bits"] += stop-128
        counts["all_fill_mismatches"] += symbols[start:stop].count(0x81)
        counts["beyond_prefix_mismatches"] += symbols[128:stop].count(0x81)
        counts["tested_payload_octets"] += 2
        for offset in (15, 18):
            left = 8*(offset+1)
            counts["payload_octet_mismatches"] += 0x81 in symbols[left:left+8]
        positions[str(slot % 4 + 1)] += 1
    return dict(slots=len(rows), reasons=dict(reasons), positives_by_position=dict(positions),
                counts=dict(counts), input_pcm_sha256=PCM_SHA, stock_g192_sha256=G192_SHA)


def check_contradiction(prefixes, decisions, observer):
    """Changing one available synthetic filler symbol must cause abstention."""
    from predict import predict

    rows = json.loads(prefixes.read_bytes())
    accepted = next(r for r in json.loads(decisions.read_bytes())["rows"]
                    if r["reason"] == "one_zero_pair")
    prefix = bytearray.fromhex(rows[accepted["slot"]]["prefix_hex"])
    bit = accepted["zero_interval"][0]
    prefix[bit//8] |= 128 >> (bit%8)
    contrary = [{"slot": 0, "prefix_hex": prefix.hex()}]
    result = predict(observer.resolve(), contrary)
    if result[0]["reason"] != "known_filler_contradiction" or "zero_interval" in result[0]:
        raise ValueError("an already visible contradiction must prevent a prediction")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("stock_encoder", type=Path)
    p.add_argument("prefix_observer", type=Path)
    p.add_argument("new_output_directory", type=Path)
    args = p.parse_args()
    out = args.new_output_directory.resolve()
    out.mkdir(parents=True, exist_ok=False)
    pcm = make_pcm()
    if sha(pcm) != PCM_SHA:
        raise ValueError("synthetic PCM differs from the frozen fixture")
    (out/"source.s16").write_bytes(pcm)
    stream, prefixes, decisions = out/"answer.192", out/"prefixes.json", out/"decisions.json"
    subprocess.run([args.stock_encoder.resolve(), "-q", "-no_delay_cmp", "-max_band", "SWB",
                    "13200", "32", out/"source.s16", stream], check=True, capture_output=True)
    export_prefixes(stream, prefixes)
    # The prediction process is given the prefix file and observer only.
    process = subprocess.run([sys.executable, HERE/"predict.py", args.prefix_observer.resolve(),
                              prefixes, decisions], check=True, text=True, capture_output=True)
    frozen = process.stdout.strip()
    (out/"prediction.sha256").write_text(frozen + "\n")
    result = score(decisions, frozen, stream)
    check_contradiction(prefixes, decisions, args.prefix_observer)
    (out/"score.json").write_text(json.dumps(result, indent=2) + "\n")
    if result != json.loads((HERE/"expected.json").read_text()):
        raise ValueError("score differs from the frozen reference result")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
