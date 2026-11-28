"""Receive a file-only, declared-clear DRM IQ TEST packet service at 48 kHz."""
import argparse
from contextlib import ExitStack, redirect_stdout
import csv
import gzip
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys
import wave

import numpy as np
import soundfile as sf

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS))
from build_evs_gcc_independent import linux, linux_command
from inspect_drm_signalling import inspect_file
from parse_text_records import scan_records
from received_evs_packets import PACKET_BYTES, read_packet_snapshot
from render_continuous import MODE_POSITIONS, PACKET_STARTS
from render_measured_evs import write_wave
from salvage_msc_packets import salvage
from speech_presence_test import write_g192


def digest(path):
    h = sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def save(path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def fixture_service(signals):
    services = signals["fac_services"]
    if not services or any((s["service_id"], s["short_id"], s["service"], s["data_ca"]) !=
                           ("EF0201", 0, "data", 0) for s in services):
        raise ValueError("FAC did not identify the clear data service EF0201")
    entities = signals["sdc_entities"]
    labels = {e.get("label") for e in entities if e["type"] == 1 and e.get("short_id") == 0}
    if labels != {"DRM IQ TEST"}:
        raise ValueError("SDC service 0 must be labelled DRM IQ TEST")
    allocations = [e.get("streams") for e in entities if e["type"] == 0]
    if not allocations or any(s != [{"stream_id": 0, "part_a_bytes": 0, "part_b_bytes": 728}]
                              for s in allocations):
        raise ValueError("expected one SDC stream 0 with 728 bytes per frame")
    packets = {(e.get("packet_mode"), e.get("stream_id"), e.get("packet_id"),
                e.get("data_unit_indicator"), e.get("packet_data_bytes"))
               for e in entities if e["type"] == 5 and e.get("short_id") == 0}
    if packets != {(True, 0, 0, 1, 179)}:
        raise ValueError("SDC did not identify the fixture's 179-byte data-unit packet format")


def unpack_fixture(packet_path, first, groups):
    ticks, units, flags = read_packet_snapshot(packet_path)
    ticks_in_span = 3 * groups
    present = (ticks >= 3 * first) & (ticks < 3 * first + ticks_in_span)
    index = (ticks[present] - 3 * first).astype(np.intp)
    packet_flags = np.zeros((ticks_in_span, 4), bool)
    packet_flags[index] = flags[present]
    offsets = np.column_stack((MODE_POSITIONS, np.asarray(PACKET_STARTS)[:, None] + np.arange(32)))
    words = np.zeros((ticks_in_span, 20, 33), np.uint8)
    observed = np.zeros(words.shape, bool)
    observed[index] = flags[present][:, offsets // PACKET_BYTES]
    words[index] = np.where(observed[index], units[present][:, offsets], 0)

    blocks = np.zeros((ticks_in_span, 16), np.uint8)
    known = np.zeros(blocks.shape, np.uint8)
    tails = flags[present, 3]
    blocks[index[tails]] = units[present][tails, 698:714]
    known[index[tails]] = 1
    raw = blocks.tobytes()
    records = []
    for r in scan_records(raw, known_bytes=known.tobytes()):
        tick = 3 * first + r.offset // 16
        end = r.offset + 2 + r.body_length
        records.append(dict(start_tick=tick, counter=tick // 3, phase=tick % 3,
                            text=r.text, header_hex=r.header_hex, text_crc=raw[end:end + 2].hex(),
                            body_length=r.body_length, size=r.size,
                            record_sha256=sha256(raw[r.offset:r.offset + r.size]).hexdigest()))
    transport = dict(scored_data_units=ticks_in_span, packets_received=int(flags[present].sum()),
                     complete_data_units=int(flags[present].all(axis=1).sum()), text_blocks_received=int(tails.sum()))
    return words.reshape(-1, 33), observed.reshape(-1, 33), records, transport, packet_flags


def write_frames(audio, first, words, observed):
    keep = observed.all(axis=1)
    stream = audio / "programme.192"
    write_g192(stream, words, keep)
    with gzip.open(audio / "frames.csv.gz", "wt", encoding="ascii", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(("slot", "counter", "phase", "cycle", "position", "input", "missing_word_octets",
                         "word_octets_hex"))
        for i, (word, known, complete) in enumerate(zip(words, observed, keep, strict=True)):
            group, slot = divmod(i, 60)
            phase, local = divmod(slot, 20)
            cycle, role = divmod(local, 4)
            status = "declared_clear" if complete else "partial" if known.any() else "missing"
            octets = "".join(f"{value:02X}" if ok else "--" for value, ok in zip(word, known, strict=True))
            writer.writerow((i, first + group, phase, cycle, role + 1, status, int(33 - known.sum()), octets))
    return keep


def prepare_iq(source, out):
    pcm = sha256()
    with sf.SoundFile(source) as f, ExitStack() as files:
        if f.format not in {"FLAC", "WAV", "WAVEX"} or f.subtype != "PCM_16" or (
                f.samplerate, f.channels) != (48000, 2):
            raise ValueError("expected a lossless 48 kHz stereo PCM16 I/Q WAV or FLAC")
        if not 0 < f.frames <= 600 * 48000:
            raise ValueError("the finite-input receiver accepts at most 600 seconds per file")
        out.mkdir(parents=True, exist_ok=False)
        effective = source
        restored = None
        if f.format == "FLAC":
            effective = out / "demod-input.wav"
            restored = files.enter_context(wave.open(str(effective), "wb"))
            restored.setparams((2, 2, 48000, 0, "NONE", "not compressed"))
        for block in f.blocks(blocksize=65536, dtype="int16", always_2d=True):
            data = block.astype("<i2", copy=False).tobytes()
            pcm.update(data)
            if restored is not None:
                restored.writeframesraw(data)
        return effective, dict(source_format=f.format, sample_pairs=f.frames, sample_rate_hz=f.samplerate,
                               interleaved_pcm16le_sha256=pcm.hexdigest())


def demodulate_test_service(iq, dream, out):
    effective, input_receipt = prepare_iq(iq, out)
    demod = out / "demod"
    bits = demod / "signalling.bits"
    env = dict(os.environ, KCBS_DREAM=str(dream), KCBS_SIGNALLING_BITS=linux(bits))
    subprocess.run([sys.executable, "-B", str(SCRIPTS / "demod_iq_window.py"), str(effective), str(demod),
                    "--seconds", "600", "--reception-profile", "wiener", "--mlc-iterations", "1"],
                   env=env, check=True, stdout=subprocess.DEVNULL)
    manifest = json.loads((demod / "manifest.json").read_bytes())
    if manifest["returncode"] != 0 or manifest["sample_count"] != manifest["source_frames"]:
        raise ValueError("Dream did not finish the entire input file")
    if not bits.is_file() or not bits.stat().st_size:
        raise ValueError("Dream produced no KCBS_SIGNALLING_BITS trace")
    signals = inspect_file(bits)
    save(demod / "signalling.json", signals)
    fixture_service(signals)
    return effective, input_receipt, signals, demod / "msc.bin"


def receive_discovered(iq, dream, out):
    from discover import discover

    effective, input_receipt, signals, msc = demodulate_test_service(iq, dream, out)
    discover(msc, out / "groups")
    paths = dict(source_iq=iq, demod_input_wav=effective, dream=dream, msc=msc,
                 catalogue=out / "groups/catalog.json")
    report = dict(profile="Declared-clear synthetic EF0201 / DRM IQ TEST", input=input_receipt,
                  signalling_crc=signals["blocks"], catalogue="groups/catalog.json",
                  sha256={name: digest(path) for name, path in paths.items()})
    save(out / "report.json", report)
    return report


def receive(iq, dream, decoder, out, first, groups):
    if not (0 < groups <= 500 and 0 <= first <= 2**32 - groups):
        raise ValueError("expected 1–500 groups within the unsigned 32-bit counter range")
    effective, input_receipt, signals, msc = demodulate_test_service(iq, dream, out)
    with (out / "salvage.log").open("w", encoding="utf-8") as log, redirect_stdout(log):
        salvage([msc], out / "receiver", transport_only=True, save_packets=True)
    packet_path = out / "receiver/packets.npz"
    words, observed, records, transport, packet_flags = unpack_fixture(packet_path, first, groups)
    save(out / "receiver/transport-mask.json",
         {str(3 * first + i): row.tolist() for i, row in enumerate(packet_flags)})
    save(out / "records.json", records)
    audio = out / "audio"
    audio.mkdir()
    keep = write_frames(audio, first, words, observed)
    stream = audio / "programme.192"
    raw = audio / "programme.pcm"
    with (audio / "decoder.log").open("wb") as log:
        subprocess.run(linux_command(decoder, "-q", "-no_delay_cmp", "16", stream, raw),
                       stdout=log, stderr=subprocess.STDOUT, check=True)
    pcm = raw.read_bytes()
    timeline_samples = len(keep) * 320
    if len(pcm) == 2 * timeline_samples:
        rendered = pcm
        source = "stock_decoder"
    elif not len(pcm) and not keep.any():
        rendered = bytes(2 * timeline_samples)
        source = "silence_for_all_erased_timeline"
    else:
        raise ValueError("stock decoder PCM length differs from the slot timeline")
    write_wave(audio / "programme.wav", rendered)
    coverage = dict(first_counter=first, last_counter=first + groups - 1, groups=groups,
                    total_slots=len(keep), supplied=int(keep.sum()), erased=int((~keep).sum()),
                    partial_word_slots=int((observed.any(axis=1) & ~keep).sum()),
                    missing_word_slots=int((~observed.any(axis=1)).sum()),
                    supplied_by_position={str(i + 1): int(keep[i::4].sum()) for i in range(4)},
                    missing_word_octets=int((~observed).sum()), native_pcm_samples=len(pcm) // 2,
                    wav_samples=len(rendered) // 2, wav_source=source)
    save(audio / "coverage.json", coverage)
    paths = dict(source_iq=iq, demod_input_wav=effective, dream=dream, evs_decoder=decoder, msc=msc, packets=packet_path,
                 receiver_g192=stream, native_pcm=raw, records=out / "records.json")
    report = dict(profile="Declared-clear synthetic EF0201 / DRM IQ TEST", input=input_receipt,
                  signalling_crc=signals["blocks"], transport=transport, text_records=len(records),
                  coverage=coverage, sha256={name: digest(path) for name, path in paths.items()})
    save(out / "report.json", report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("iq", type=Path, help="48 kHz stereo PCM16 I/Q WAV or lossless FLAC")
    parser.add_argument("--dream", required=True, type=Path, help="finite-input Dream with KCBS_SIGNALLING_BITS")
    parser.add_argument("--decoder", type=Path, help="stock floating-point EVS_dec for the scored timeline")
    parser.add_argument("--out", required=True, type=Path, help="fresh output directory")
    parser.add_argument("--discover", action="store_true", help="write complete received EVS groups in native row order")
    parser.add_argument("--first-counter", type=lambda s: int(s, 0),
                        help="first scored phase-zero counter (default 0x01020304)")
    parser.add_argument("--groups", type=int, help="number of 60-slot groups (default 40)")
    args = parser.parse_args()
    if args.discover and (args.first_counter is not None or args.groups is not None):
        parser.error("--discover reads counter boundaries from the received data; omit --first-counter and --groups")
    if not args.discover and args.decoder is None:
        parser.error("--decoder is required to render the scored timeline")
    try:
        iq, dream, out = args.iq.resolve(strict=True), args.dream.resolve(strict=True), args.out.resolve()
        if args.discover:
            report = receive_discovered(iq, dream, out)
        else:
            first = 0x01020304 if args.first_counter is None else args.first_counter
            groups = 40 if args.groups is None else args.groups
            report = receive(iq, dream, args.decoder.resolve(strict=True), out, first, groups)
        print(json.dumps(report, indent=2))
    except (OSError, ValueError, KeyError, wave.Error, subprocess.CalledProcessError) as exc:
        parser.exit(1, f"{exc}\n")
