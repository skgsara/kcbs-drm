"""Compare a fully supplied group's PCM under three starts of the same November 27 release."""
import argparse
from collections import Counter
import csv
import gzip
from hashlib import sha256
import json
from pathlib import Path
import struct
import subprocess
from tempfile import TemporaryDirectory

import numpy as np

RELEASE = Path(__file__).resolve().parents[2] / "nov27"
SAMPLES = 320  # 20 ms at 16 kHz


def digest(data):
    return sha256(data).hexdigest()


def checked(data, expected):
    if digest(data) != expected:
        raise ValueError(f"SHA-256 differs from the release: expected {expected}")
    return data


def records(stream):
    at = 0
    while at < len(stream):
        if at + 4 > len(stream):
            raise ValueError("truncated G.192 header")
        marker, size = struct.unpack_from("<HH", stream, at)
        end = at + 4 + 2*size
        if (marker, size) not in ((0x6b21, 264), (0x6b20, 0)) or end > len(stream):
            raise ValueError("invalid G.192 record")
        yield stream[at:end]
        at = end


def decode(decoder, raw, expected_slots):
    with TemporaryDirectory() as tmp:
        source = Path(tmp) / "input.192"
        output = Path(tmp) / "output.pcm"
        source.write_bytes(raw)
        subprocess.run([decoder, "-q", "-no_delay_cmp", "16", source, output],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        pcm = output.read_bytes()
    if len(pcm) != 2 * SAMPLES * expected_slots:
        raise ValueError("decoder output sample count disagrees with the input slot count")
    return pcm


def compare_pcms(reference, test, absolute_sample):
    a = np.frombuffer(reference, dtype="<i2").astype(np.int32)
    b = np.frombuffer(test, dtype="<i2").astype(np.int32)
    difference = b - a
    indices = np.flatnonzero(difference)
    per_slot = np.count_nonzero(difference.reshape(-1, SAMPLES), axis=1)
    endpoints = [int(indices[0]), int(indices[-1])] if len(indices) else None
    return dict(target_pcm_sha256=digest(test), differing_samples=len(indices),
                differing_20ms_slots=int(np.count_nonzero(per_slot)),
                differing_samples_per_20ms_slot=per_slot.tolist(),
                first_last_differing_sample_in_group=endpoints,
                first_last_differing_sample_in_release=[absolute_sample + x for x in endpoints] if endpoints else None,
                maximum_absolute_difference_pcm_counts=int(np.abs(difference).max()))


def measure(decoder, counter):
    manifest = json.loads((RELEASE / "replay.json").read_bytes())
    info = manifest["streams"]["programme"]
    compressed = checked((RELEASE / info["file"]).read_bytes(), info["compressed_sha256"])
    stream = checked(gzip.decompress(compressed), info["g192_sha256"])
    frames = list(records(stream))
    ledger = checked((RELEASE / "frames.csv").read_bytes(), manifest["frames_csv_sha256"])
    rows = list(csv.DictReader(ledger.decode("ascii").splitlines()))
    if len(rows) != len(frames) or len(rows) != manifest["frame_slots"]:
        raise ValueError("release stream and frame ledger have different extents")
    indices = [i for i, r in enumerate(rows) if int(r["counter"]) == counter]
    if len(indices) != 60 or indices != list(range(indices[0], indices[0] + 60)):
        raise ValueError("counter must occupy 60 consecutive release slots")
    start, end = indices[0], indices[-1] + 1
    for s, i in enumerate(indices):
        r = rows[i]
        if ((int(r["phase"]), int(r["cycle"]), int(r["position"])) != (s//20, s%20//4, 1+s%4)
                or len(frames[i]) != 532 or r["source"] not in ("text-supported", "inferred")):
            raise ValueError("expected all 60 words supplied in chronological order")
    target = b"".join(frames[start:end])
    full_pcm = checked(decode(decoder, stream, len(frames)), info["pcm_sha256"])
    reference = full_pcm[2*SAMPLES*start:2*SAMPLES*end]
    result = dict(scope="PCM from the published programme reconstruction", counter=counter,
                  decoder_sha256=digest(decoder.read_bytes()), decoder_options=["-q", "-no_delay_cmp", "16"],
                  source_stream="examples/nov27/programme.192.gz", source_manifest="examples/nov27/replay.json",
                  frames_csv_sha256=digest(ledger), full_g192_sha256=digest(stream), full_pcm_sha256=digest(full_pcm),
                  full_samples=len(full_pcm)//2, group_release_slots_half_open=[start, end],
                  group_release_samples_half_open=[start*SAMPLES, end*SAMPLES], target_samples=len(reference)//2,
                  chronology_source_counts=dict(Counter(rows[i]["source"] for i in indices)),
                  group_g192_sha256=digest(target), reference_target_pcm_sha256=digest(reference), trials={})
    trials = [("cold_group_start", start)]
    if start >= 60 and all(int(row["counter"]) == counter-1 for row in rows[start-60:start]):
        trials.append(("one_prior_group", start-60))
    for name, begin in trials:
        trial = b"".join(frames[begin:end])
        if trial[-len(target):] != target:
            raise ValueError("target G.192 records differ between runs")
        pcm = decode(decoder, trial, end-begin)
        result["trials"][name] = dict(first_release_slot=begin, prior_slots=start-begin,
                                      trial_g192_sha256=digest(trial), target_g192_sha256=digest(trial[-len(target):]),
                                      **compare_pcms(reference, pcm[-len(reference):], start*SAMPLES))
    return result


def overlap_summary(decoder, selection):
    raw = checked(selection.read_bytes(), "dbd04b4689018111f5d2d2b8635692efc300af0ff5e6cf3db0e39d039643041e")
    overlap = json.loads(raw)
    rows = []
    for group in overlap["groups"]:
        if group["supplied"] != 60:
            continue
        detail = measure(decoder, group["counter"])
        if detail["frames_csv_sha256"] != overlap["frames_csv_sha256"]:
            raise ValueError("overlap and state comparison reference different frame ledgers")
        labels = detail["chronology_source_counts"]
        if labels.get("text-supported", 0) != group["text_supported"] or labels.get("inferred", 0) != group["inferred"]:
            raise ValueError("overlap and state comparison disagree on supplied word labels")
        row = dict(counter=group["counter"], release_first_slot=detail["group_release_slots_half_open"][0])
        for name in ("cold_group_start", "one_prior_group"):
            trial = detail["trials"][name]
            row[name] = {k: trial[k] for k in ("differing_samples", "differing_20ms_slots",
                                               "first_last_differing_sample_in_group",
                                               "maximum_absolute_difference_pcm_counts")}
        rows.append(row)
    if len(rows) != overlap["fully_supplied_groups"]:
        raise ValueError("overlap counter inventory is inconsistent")
    totals = {}
    for name in ("cold_group_start", "one_prior_group"):
        counts = [r[name]["differing_samples"] for r in rows]
        slots = [r[name]["differing_20ms_slots"] for r in rows]
        totals[name] = dict(groups_differing=sum(bool(n) for n in counts), differing_samples=sum(counts),
                            differing_samples_per_group_range=[min(counts), max(counts)],
                            differing_20ms_slots=sum(slots), differing_20ms_slots_per_group_range=[min(slots), max(slots)])
    return dict(scope="PCM from fully supplied counters in the published programme and companion RF overlap",
                selection_sha256=digest(raw), decoder_sha256=digest(decoder.read_bytes()),
                release_g192_sha256=detail["full_g192_sha256"], release_pcm_sha256=detail["full_pcm_sha256"],
                selected_groups=len(rows), compared_slots=60*len(rows), compared_samples=60*SAMPLES*len(rows),
                trials=totals, groups=rows)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--decoder", type=Path, required=True, help="TS 26.443 floating-point EVS_dec")
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--counter", type=int, default=43854890)
    selection.add_argument("--overlap", type=Path, help="published music-overlap.json, all fully supplied groups")
    args = parser.parse_args()
    decoder = args.decoder.resolve()
    result = overlap_summary(decoder, args.overlap) if args.overlap else measure(decoder, args.counter)
    print(json.dumps(result, indent=2))
