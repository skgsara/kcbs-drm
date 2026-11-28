"""Verify digital RF diversity in the November 27 06:17 dual-receiver IQ release.

python digital.py --source-dir EXTRACTED_0617 --dream /path/to/dream --out result.json

Requires the original pair of 12 kHz IQ WAVs, capture.json, the contributor's MSC
file, the project's packet snapshot, and a finite-file Dream with MSC output.
"""
import argparse
from binascii import crc_hqx
from datetime import datetime
from hashlib import sha256
from itertools import groupby
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

PROJECT = Path(__file__).resolve().parents[3]
FREQUENCIES = (3205, 6140)
HEADERS = (0x80, 0x01, 0x02, 0x43)
IQ_HASHES = {
    3205: "c3a47ab1cbe110e3cb428660273dc3204acad4dd489a1a2d0509b5c49fa7190c",
    6140: "9f708e4e206605ad934d9dcddeb183b7f0a011f631b7a998674aa74c5662c6ab",
}
CAPTURE_HASH = "4c48fbb4e6fc28e53b1d61ceb3d7c47abef4b5182862eecf96bd437a6639765b"
REFERENCE_HASH = "85986684749e84fb33434cccb39c9a994ddeb091ed01f20d62adfb2edc4f35ed"


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def valid_crc(data):
    return (crc_hqx(data[:-2], 0xffff) ^ 0xffff) == int.from_bytes(data[-2:], "big")


def load_reference():
    path = PROJECT / "examples/nov27/receiver/packets.npz"
    require(digest(path) == REFERENCE_HASH, "release packet snapshot hash differs")
    with np.load(path, allow_pickle=False) as snap:
        require(snap["packet_ok"].all(), "incomplete packet in release snapshot")
        by_du = {row.tobytes(): int(tick) for tick, row in zip(snap["ticks"], snap["packets"], strict=True)}
    require(len(by_du) == 75 and len(set(by_du.values())) == 75, "ambiguous release coordinate or DU")
    return by_du


def read_rows(path):
    """Retain whole 182-byte packets including all over-air header and checksum bytes."""
    rows = []
    with path.open("rb") as stream:
        while header := stream.read(4):
            require(len(header) == 4 and struct.unpack("<I", header)[0] == 728, "unexpected MSC length")
            body = stream.read(728)
            require(len(body) == 728, "short MSC row")
            packets = tuple(body[n:n+182] for n in range(0, 728, 182))
            du = b"".join(p[1:-2] for p in packets)
            checked = [valid_crc(p) for p in packets]
            complete = all(checked) and tuple(p[0] for p in packets) == HEADERS and valid_crc(du)
            rows.append((complete, (du, packets), sum(checked)))
    return rows


def align_epoch(rows, reference):
    """Assign ticks from physical phase tags and phase-zero counters before comparing DU identities."""
    anchors = [(i, int.from_bytes(du[664:668], "big"))
               for i, (_, (du, _), _) in rows if du[1] >> 4 == 0]
    require(len(anchors) >= 2, "epoch lacks successive physical counter anchors")
    origin = 3 * anchors[0][1] - anchors[0][0]
    frames = {}
    for i, (_, (du, packets), _) in rows:
        tick = i + origin
        counter, phase = divmod(tick, 3)
        require(du[1] >> 4 == phase, f"phase sequence break at row {i}")
        if phase == 0:
            require(int.from_bytes(du[664:668], "big") == counter, f"counter break at row {i}")
        require(reference.get(du) == tick, f"DU identity differs from its release coordinate at row {i}")
        frames[tick] = packets
    return frames, anchors


def original_epoch(path, reference, padded):
    rows = read_rows(path)
    runs = [(valid, list(entries)) for valid, entries in groupby(enumerate(rows), lambda pair: pair[1][0])]
    pattern = [True, False, True, False, True] if padded else [True]
    require([valid for valid, _ in runs] == pattern, "unexpected shape of receiver epochs")
    good = [align_epoch(entries, reference) for valid, entries in runs if valid]
    seams = []
    for left, (_, barrier), right in zip(good, runs[1::2], good[1:]):
        before, after = left[1][-1], right[1][0]
        require(before[1] > after[1], "missing backward phase-zero counter jump at repeated IQ")
        require(all(obs[2] == 0 for _, obs in barrier), "splice has candidate packet requiring separate review")
        seams.append({"last_phase_zero_before": before, "first_phase_zero_after": after,
                      "rejected_raw_rows": [i for i, _ in barrier]})
    idx = 1 if padded else 0
    frames, anchors = good[idx]
    retained = runs[2 * idx][1]
    return frames, dict(msc_sha256=digest(path), raw_rows=len(rows),
                        retained_raw_row_range=[retained[0][0], retained[-1][0]],
                        retained_first_last=[list(divmod(t, 3)) for t in (min(frames), max(frames))],
                        phase_zero_anchors=len(anchors), counter_rollovers_in_retained_epoch=0,
                        excluded_splice_rows=sum(len(entries) for complete, entries in runs if not complete),
                        crc_valid_packets_in_excluded_splice_rows=sum(r[2] for complete, entries in runs
                                                                     if not complete for _, r in entries),
                        excluded_complete_repeated_rows=sum(len(a) for a, _ in good) - len(frames),
                        splice_barriers=seams)


def summarize(a, b, reference):
    common = a.keys() & b.keys()
    differences = []
    for tick in sorted(common):
        for q, (left, right) in enumerate(zip(a[tick], b[tick], strict=True)):
            if left != right:
                differences.append([*divmod(tick, 3), q])
    require(not differences, f"CRC-valid packet disagreements: {differences}")
    all_ticks = a.keys() | b.keys()

    def groups(ticks):
        return {c for c in {t // 3 for t in ticks} if all(3*c+p in ticks for p in range(3))}

    ga, gb, gu = groups(a), groups(b), groups(all_ticks)
    du_sets = [a.keys(), b.keys(), a.keys()-b.keys(), b.keys()-a.keys(), common, all_ticks]
    group_sets = [ga, gb, ga-gb, gb-ga, ga & gb, gu]
    names = ("3205", "6140", "3205_only", "6140_only", "both", "union")
    table = {name: dict(physical_packets=4*len(dus), complete_dus=len(dus),
                        complete_counter_groups=len(counters), transported_evs_slots=20*len(dus))
             for name, dus, counters in zip(names, du_sets, group_sets, strict=True)}
    gain = {k: table["union"][k] - max(table["3205"][k], table["6140"][k]) for k in table["union"]}
    return dict(counts=table, union_gain_over_better_single_frequency=gain,
                full_packet_bytes_compared_on_overlapping_coordinates=4 * 182 * len(common),
                union_complete_group_counter_range=[min(gu), max(gu)] if gu else [],
                newly_complete_groups_requiring_both=sorted(gu - (ga | gb)),
                same_coordinate_full_packet_disagreements=differences,
                only_3205_du_coordinates=[list(divmod(t, 3)) for t in sorted(a.keys()-b.keys())],
                only_6140_du_coordinates=[list(divmod(t, 3)) for t in sorted(b.keys()-a.keys())],
                union_gaps_inside_observed_tick_span=sorted(set(range(min(all_ticks), max(all_ticks)+1))-all_ticks),
                published_dus_missing_from_union=[list(divmod(t, 3)) for t in sorted(set(reference.values())-all_ticks)])


def receive(iq, out, dream, seconds):
    cmd = [sys.executable, str(PROJECT / "scripts/demod_iq_window.py"), str(iq), str(out),
           "--seconds", str(seconds), "--reception-profile", "wiener", "--mlc-iterations", "1"]
    subprocess.run(cmd, env={**os.environ, "KCBS_DREAM": str(dream)}, check=True, stdout=subprocess.DEVNULL)
    log = (out / "dream.log").read_text(errors="replace")
    require(json.loads((out / "manifest.json").read_text())["returncode"] == 0 and
            "Reached end of input in offline mode." in log, "receiver did not reach physical EOF")
    return out / "msc.bin"


def run(src, dream, work):
    reference = load_reference()
    metadata_file = src / "capture.json"
    require(digest(metadata_file) == CAPTURE_HASH, "capture metadata hash differs")
    metadata = json.loads(metadata_file.read_text())
    captures = {}
    modes = {"ordinary": {}, "preview_and_drain": {}}
    for khz in FREQUENCIES:
        iq = src / f"KCBS2_20261127T061722Z_{khz}kHz_IQ.wav"
        require(digest(iq) == IQ_HASHES[khz], f"source hash differs at {khz} kHz")
        with sf.SoundFile(iq) as stream:
            require((stream.channels, stream.samplerate, len(stream), stream.subtype) ==
                    (2, 12000, 360000, "PCM_16"), "unexpected IQ geometry")
            samples = stream.read(dtype="float32", always_2d=True)
        # Quantize the resampled original exactly once; both edges repeat the resulting PCM.
        flat = work / f"{khz}-48.wav"
        sf.write(flat, resample_poly(samples, 4, 1, axis=0), 48000, subtype="PCM_16")
        pcm, _ = sf.read(flat, dtype="int16", always_2d=True)
        padded = work / f"{khz}-54s.wav"
        edge = 12 * 48000
        sf.write(padded, np.concatenate((pcm[:edge], pcm, pcm[-edge:])), 48000, subtype="PCM_16")
        info = metadata["frequencies_khz"][str(khz)]
        captures[khz] = dict(iq_sha256=IQ_HASHES[khz], started_utc=info["started_utc"],
                             driver_drops_reported=info["driver_drops"], clipped_pcm_samples_reported=info["pcm_clips"])
        for mode, path, duration in (("ordinary", iq, 30), ("preview_and_drain", padded, 54)):
            dump = receive(path, work / f"{khz}-{mode}", dream, duration)
            frames, detail = original_epoch(dump, reference, mode != "ordinary")
            modes[mode][khz] = frames
            captures[khz][mode] = detail

    contributor = src / "KCBS2_CRC_verified.msc.bin"
    require(digest(contributor) == metadata["file_sha256"][contributor.name], "contributor MSC hash differs")
    contributed, _ = original_epoch(contributor, reference, False)
    for observations in modes.values():
        for frames in observations.values():
            require(all(frames.get(t) == packets for t, packets in contributed.items()),
                    "contributor packet differs from independent reception")
    a, b = (datetime.fromisoformat(captures[f]["started_utc"]) for f in FREQUENCIES)
    return dict(capture="2026-11-27 06:17 UTC", receiver="Two Airspy HF+ units on the same antenna splitter.",
                original_iq_per_frequency=dict(seconds=30, sample_pairs=360000, complex_sample_rate_hz=12000),
                host_start_separation_reported_ms=metadata["host_start_separation_ms"],
                utc_label_6140_minus_3205_us=round((b-a).total_seconds() * 1e6),
                timing="Recorder host start labels. No common sample clock or sample-level UTC is established.",
                coordinate="(phase-zero counter, phase 0..2, packet ordinal 0..3). Headers 80/01/02/43 carry ordinals via the continuity index.",
                integrity="Each retained row has four CRC-valid physical packets, matching headers, native DU CRC and a unique whole-DU match after phase/counter assignment. No ambiguous, conflicting or rollover coordinates were accepted.",
                coverage="20 transported EVS slots per complete DU; 3 DUs per full counter group. A slot counts carriage only.",
                replay="Original-only and 12 s preview + untouched original + 12 s repeated tail. Only the middle epoch is counted.",
                dream_sha256=digest(dream), capture_metadata_sha256=CAPTURE_HASH, published_packets_sha256=REFERENCE_HASH,
                contributor_msc_sha256=digest(contributor), contributor_packets_agree_on_each_frequency=4*len(contributed),
                receivers=captures, runs={k:summarize(v[3205], v[6140], reference) for k,v in modes.items()})


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source-dir", type=Path, required=True)
    ap.add_argument("--dream", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True, help="write the JSON receipt to this new file")
    args = ap.parse_args()
    try:
        with tempfile.TemporaryDirectory() as tmp:
            result = run(args.source_dir.resolve(), args.dream.resolve(), Path(tmp))
        with args.out.open("x", encoding="utf-8") as out:
            json.dump(result, out, indent=2)
            out.write("\n")
    except (OSError, ValueError, subprocess.SubprocessError) as e:
        ap.exit(1, f"{ap.prog}: {e}\n")


if __name__ == "__main__":
    main()
