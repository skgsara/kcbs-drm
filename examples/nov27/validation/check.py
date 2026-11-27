"""Verify November 27 text CRCs, evidence classes and EVS frame counts from bundled data."""
from collections import Counter
import csv
import gzip
import json
from pathlib import Path
import sys

import numpy as np

HERE = Path(__file__).resolve().parent
EXAMPLE = HERE.parent
ROOT = EXAMPLE.parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from parse_text_records import crc, parse_record
from render_measured_evs import collect, measured_groups


def received_text():
    with np.load(EXAMPLE / "receiver/keys.npz") as data:
        keys = {int(c): mask for c, mask, valid in zip(data["counters"], data["ks"], data["crc_supported"], strict=True) if valid.all()}
    with np.load(EXAMPLE / "receiver/packets.npz") as data:
        return {int(t): (packet.ravel()[698:714] ^ keys[t // 3]).tobytes()
                for t, packet, valid in zip(data["ticks"], data["packets"], data["packet_ok"], strict=True)
                if t // 3 in keys and valid.all()}


def read_words(path):
    data = np.frombuffer(gzip.decompress(path.read_bytes()), dtype="<u2")
    offset = 0
    while offset < len(data):
        sync, length = map(int, data[offset:offset+2])
        if (sync, length) not in ((0x6B20, 0), (0x6B21, 264)):
            raise ValueError(f"Unexpected frame header in {path.name} at word {offset}")
        bits = data[offset+2:offset+2+length]
        if len(bits) != length or not np.isin(bits, (0x7F, 0x81)).all():
            raise ValueError(f"Invalid frame bits in {path.name} at word {offset}")
        yield np.packbits(bits == 0x81).tobytes()
        offset += 2 + length


def main():
    evidence = json.loads((HERE / "evidence.json").read_text())
    blocks = received_text()
    for record in evidence["weather_records"]:
        tick = 3 * record["counter"] + record["phase"]
        raw = b"".join(blocks[t] for t in range(tick, tick + record["blocks"]))
        end = 2 + 16 * (raw[0] & 7) + (raw[1] & 15)
        actual = crc(raw[:end]).to_bytes(2, "big")
        if actual != raw[end:end+2] or actual.hex() != record["checksum"]:
            raise ValueError(f"Weather CRC mismatch at tick {tick}")
        if record["kind"] == "ordinary":
            parse_record(raw)

    methods = {tuple(group): method for method, groups in evidence["inferred_counter_positions"].items()
               for group in groups}
    if len(methods) != sum(map(len, evidence["inferred_counter_positions"].values())):
        raise ValueError("A mask has more than one evidence class")
    manifest = json.loads((ROOT / "dumps/nov27-measured-masks.json").read_text())
    registered = {(int(c), int(p)) for c, v in manifest["groups"].items() for p in v["masks"]}
    if set(methods) != registered:
        raise ValueError("Evidence classes and capture-specific masks disagree")
    words, kinds, reception = collect(EXAMPLE / "receiver", measured_groups(manifest))
    first_slot = reception["first_tick"] % 3 * 20
    counts, frames = Counter(), Counter()
    visited = set()
    with (EXAMPLE / "frames.csv").open(newline="") as handle:
        timeline = csv.DictReader(handle)
        streams = zip(timeline, read_words(EXAMPLE / "programme.192.gz"),
                      read_words(EXAMPLE / "text-supported.192.gz"), strict=True)
        for slot, (row, full, text) in enumerate(streams):
            counter, phase, cycle, position = (int(row[name]) for name in ("counter", "phase", "cycle", "position"))
            tick = 3 * counter + phase
            if 20 * (tick - reception["first_tick"]) + 4 * cycle + position - 1 != slot:
                raise ValueError(f"Frame coordinate out of order at slot {slot}")
            index = first_slot + slot
            expected = words[index].tobytes() if kinds[index] else b""
            if full != expected or bool(text) != (kinds[index] == 1):
                raise ValueError(f"Receiver bytes, mask and released frame disagree at slot {slot}")
            label = "text-supported" if text else "inferred" if full else "erasure"
            if row["source"] != label or (text and text != full):
                raise ValueError(f"Frame streams and ledger disagree at {row['time_seconds']} s")
            counts[label] += 1
            if label == "inferred":
                key = (int(row["counter"]), int(row["position"]))
                frames[methods[key]] += 1
                visited.add(key)
    if visited != registered:
        raise ValueError("Some listed masks apply to no released frames")
    print(f"{len(evidence['weather_records'])} weather records passed their received CRC.")
    print(f"{sum(counts.values())} frame slots agree with receiver bytes, masks and both streams.")
    print(dict(sorted(counts.items())))
    for name, groups in evidence["inferred_counter_positions"].items():
        print(f"{name:27} {len(groups):2} masks {frames[name]:3} frames")


if __name__ == "__main__":
    main()
