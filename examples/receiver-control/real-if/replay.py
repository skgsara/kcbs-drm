"""Replay the two published +6 kHz real-IF development controls with patched Dream."""
import argparse
from collections import Counter
from hashlib import sha256
import json
import os
from pathlib import Path
import struct
import subprocess
import sys

import numpy as np
from scipy.signal import hilbert, resample_poly
import soundfile as sf

HERE = Path(__file__).resolve().parent
CONTROL = HERE.parent
SCRIPTS = HERE.parents[2] / "scripts"
sys.path[:0] = [str(CONTROL), str(SCRIPTS)]
from receive import unpack_fixture
from received_evs_packets import read_packet_snapshot
from tail_fill_audit import crc
from verify import read_bytes, read_g192

HISTORICAL = "5cc0b4df2094a1347c0b3e0ae616e1f5305e176fdf460f3afd766fb261da9590"
SYNTHETIC = "ae12fed7ed9aab2c583b6ad1aefdbd32cecc52b20adebd16a4939c9aa48931c6"
CARRIER = np.exp(2j * np.pi * np.arange(8) / 8)


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def run_receiver(source, out, dream, real_if=False):
    options = ["--real-if-hz", "6000"] if real_if else []
    command = [sys.executable, str(SCRIPTS / "demod_iq_window.py"), str(source), str(out),
               "--start", "0", "--seconds", "90", "--reception-profile", "wiener", "--mlc-iterations", "1"]
    env = dict(os.environ, KCBS_DREAM=str(dream))
    subprocess.run(command + options, env=env, check=True, stdout=sys.stderr)
    manifest = json.loads((out / "manifest.json").read_text())
    if manifest["returncode"] or not manifest["dump_bytes"]:
        raise ValueError("Dream did not finish with a nonempty MSC dump")
    subprocess.run([sys.executable, str(SCRIPTS / "salvage_msc_packets.py"), str(out / "msc.bin"),
                    "--transport-only", "--save-packets", "--out", str(out / "transport")],
                   check=True, stdout=sys.stderr)


def native_rows(path):
    raw = path.read_bytes()
    if len(raw) % 732:
        raise ValueError("incomplete MSC record")
    rows = []
    for off in range(0, len(raw), 732):
        if struct.unpack_from("<I", raw, off)[0] != 728:
            raise ValueError("unexpected MSC record size")
        rows.append(tuple(raw[off+4+i:off+4+i+182] for i in range(0, 728, 182)))
    return rows


def valid_crc(payload):
    return crc(payload[:-2]) == int.from_bytes(payload[-2:], "big")


def archives(out):
    ticks, units, flags = read_packet_snapshot(out / "transport/packets.npz")
    packets = {(int(t), int(q)): row[179*q:179*(q+1)].tobytes()
               for t, row, known in zip(ticks, units, flags, strict=True) for q in np.flatnonzero(known)}
    with np.load(out / "transport/data_units.npz") as archive:
        dus = {(int(c), int(p)): u.tobytes() for c, p, u in
               zip(archive["counters"], archive["phases"], archive["du"], strict=True)}
        if len(dus) != len(archive["du"]):
            raise ValueError("duplicate data unit")
    for (counter, phase), du in dus.items():
        if (len(du) != 716 or not valid_crc(du) or du[1] >> 4 != phase
                or phase == 0 and int.from_bytes(du[664:668], "big") != counter):
            raise ValueError("invalid data unit or coordinates")
    return packets, dus


def historical(source, out, dream):
    with sf.SoundFile(source) as f:
        if (f.channels, f.samplerate, f.subtype) != (1, 48000, "PCM_16"):
            raise ValueError("expected 48 kHz mono PCM16")
        x = f.read(90 * 48000, dtype="int16")
    analytic = hilbert(x.astype(float) / 32768) * np.resize(CARRIER.conj(), len(x))
    z = resample_poly(analytic, up=1, down=4, window=("kaiser", 8.6))
    iq_path = out / "analytic-iq12.wav"
    sf.write(iq_path, np.column_stack((z.real, z.imag)), 12000, subtype="FLOAT")
    ref, new = out / "analytic", out / "real-if"
    run_receiver(iq_path, ref, dream)
    run_receiver(source, new, dream, real_if=True)
    packets, dus = archives(ref)
    if (packets, dus) != archives(new):
        raise ValueError("the two DSP paths produced different assigned coordinates or bytes")
    a, b = (native_rows(d / "msc.bin") for d in (ref, new))
    pairs = [(u, v) for row, other in zip(a, b, strict=True) for u, v in zip(row, other, strict=True) if u != v]
    counts = Counter(c for c, phase in dus)
    joined = sha256()
    for (counter, phase), payload in sorted(dus.items()):
        joined.update(struct.pack(">IB", counter, phase) + payload)
    return dict(source_frames_examined=[0, len(x)], cut_s16le_sha256=sha256(x.astype("<i2").tobytes()).hexdigest(),
                native_rows=len(a), raw_msc_sha256=[digest(d / "msc.bin") for d in (ref, new)],
                differing_rows=sum(x != y for x, y in zip(a, b)), differing_physical_packets=len(pairs),
                differing_packets_with_either_crc_valid=sum(valid_crc(u) or valid_crc(v) for u, v in pairs),
                identical_assigned_packet_bodies=len(packets), identical_assigned_data_units=len(dus),
                sorted_counter_phase_du_sha256=joined.hexdigest(),
                first_counter=min(counts), last_counter=max(counts),
                all_three_phase_groups=sum(n == 3 for n in counts.values()))


def synthetic(source, out, dream):
    x, fs = sf.read(source, dtype="int16")
    if fs != 48000 or x.ndim != 2 or x.shape[1] != 2:
        raise ValueError("expected 48 kHz stereo PCM")
    iq, mono = out / "original-iq.wav", out / "if6k.wav"
    sf.write(iq, x, fs, subtype="PCM_16")
    carrier = np.resize(CARRIER, len(x))
    y = np.rint(((x[:, 0] + 1j * x[:, 1]) * carrier).real * 0.5)
    if (y < -32768).any() or (y > 32767).any():
        raise ValueError("synthetic IF clipped")
    sf.write(mono, y.astype("int16"), fs, subtype="PCM_16")
    stereo, real = out / "stereo", out / "real-if"
    run_receiver(iq, stereo, dream)
    run_receiver(mono, real, dream, real_if=True)
    if (stereo / "msc.bin").read_bytes() != (real / "msc.bin").read_bytes():
        raise ValueError("different stereo and real-IF receiver dumps")
    packets, _ = archives(real)
    wire = read_bytes(CONTROL / "fixture/sender-msc.bin.gz")
    truth = read_g192(read_bytes(CONTROL / "fixture/sender.192.gz"))
    first = 16909060
    scored = 0
    for (tick, q), received in packets.items():
        index = tick - 3*first
        if 0 <= index < 120:
            offset = 728*index + 182*q + 1
            if received != wire[offset:offset+179]:
                raise ValueError(f"packet differs from sender at tick {tick}, packet {q}")
            scored += 1
    words, known, records, transport, _ = unpack_fixture(real / "transport/packets.npz", first, 40)
    full = known.all(axis=1)
    for slot in np.flatnonzero(full):
        if words[slot].tobytes() != truth[slot]:
            raise ValueError(f"word differs from sender at slot {slot}")
    return dict(source_pairs=len(x), mono_gain=0.5, mono_wav_sha256=digest(mono),
                identical_native_msc_sha256=digest(real / "msc.bin"), records=len(records),
                scored_phases=120, complete_scored_data_units=transport["complete_data_units"],
                packet_bodies_equal_to_sender=scored, supplied_words_equal_to_sender=int(full.sum()),
                missing_or_partial_words=int((~full).sum()))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("control", choices=["historical", "synthetic"])
    parser.add_argument("source", type=Path)
    parser.add_argument("--dream", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True, help="fresh local directory")
    args = parser.parse_args()
    historical_run = args.control == "historical"
    source_hash = digest(args.source)
    if source_hash != (HISTORICAL if historical_run else SYNTHETIC):
        parser.error("input SHA-256 differs from the published control")
    args.out.mkdir(parents=True, exist_ok=False)
    fn = historical if historical_run else synthetic
    results = fn(args.source.resolve(), args.out.resolve(), args.dream.resolve())
    report = dict(control=args.control, source_sha256=source_hash, dream_sha256=digest(args.dream), results=results)
    text = json.dumps(report, indent=2) + "\n"
    (args.out / "receipt.json").write_text(text)
    print(text, end="")


if __name__ == "__main__":
    main()
