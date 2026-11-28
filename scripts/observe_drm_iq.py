"""Observe deinterleaved MSC cells during one cold Wiener/MLC1 pass over an exact stereo IQ interval."""
import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys

import soundfile as sf

from demod_iq_window import input_info
from drm_msc_cells import read_blocks
from drm_row_alignment import read_msc


RUNNER = Path(__file__).with_name("demod_iq_window.py")
RUNNER_SHA256 = "fb3cc1cee294e995ee80220f55c8bd8931f53fece482c2b92f92754892eba662"
MAGIC = b"MSCObs1\n"


def file_hash(path):
    h = sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def selection(source, start, count):
    rate, frames = input_info(source, None)
    with sf.SoundFile(source) as audio:
        if audio.format not in ("WAV", "WAVEX", "RF64", "FLAC") or audio.subtype != "PCM_16":
            raise ValueError("expected lossless stereo PCM16 WAV or FLAC")
        if start < 0 or count <= 0 or count > 600 * rate or start + count > frames:
            raise ValueError("select a nonempty interval within the input, up to 600 seconds")
        audio.seek(start)
        remaining = count
        h = sha256()
        while remaining:
            data = audio.read(min(65536, remaining), dtype="int16", always_2d=True)
            if not len(data):
                raise ValueError("input ended before the selected sample extent")
            h.update(data.astype("<i2", copy=False).tobytes())
            remaining -= len(data)
        return dict(source_format=audio.format, source_subtype=audio.subtype, channels=2, sample_rate=rate,
                    source_frames=frames, start_sample=start, sample_count=count, end_sample_exclusive=start+count,
                    selected_pcm_s16le_sha256=h.hexdigest())


def count_cell_blocks(path):
    blocks = read_blocks(path.read_bytes())
    for block in blocks:
        if block.hard[-1] & ((1 << (-block.header[2] % 8)) - 1):
            raise ValueError("incorrectly padded original hard decisions")
    return len(blocks)


def identity(path):
    stat = path.stat()
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns


def observe(source, out, dream, *, start_sample, sample_count):
    source = Path(source).resolve(strict=True)
    dream = Path(dream).resolve(strict=True)
    out = Path(out).resolve()
    stamp = identity(source)
    selected = selection(source, start_sample, sample_count)
    runner_hash = file_hash(RUNNER)
    if runner_hash != RUNNER_SHA256:
        raise ValueError("demod_iq_window.py differs from the pinned Wiener/MLC1 runner")
    binary = dream.read_bytes()
    if not os.access(dream, os.X_OK) or b"DREAM_CELL_OBSERVATIONS\0" not in binary or MAGIC not in binary:
        raise ValueError("select a Dream executable built with the MSCObs1 observer patch")
    report = dict(format="drm-iq-observation-v1", status="running", source=str(source),
                  source_sha256=file_hash(source), **selected, dream_sha256=sha256(binary).hexdigest(),
                  demod_runner_sha256=runner_hash, reception_profile="wiener", mlc_iterations=1, offset_hz=0)
    out.mkdir(parents=True, exist_ok=False)
    manifest = out / "observation.json"
    manifest.write_text(json.dumps(report, indent=2) + "\n")
    wire, trace = out / "msc.bin", out / "cells.bin"
    rf = out / "receiver"
    env = os.environ | dict(KCBS_DREAM=str(dream), DREAM_CELL_OBSERVATIONS=str(trace))
    rate = selected["sample_rate"]
    try:
        with (out / "runner.log").open("xb") as log:
            subprocess.run([sys.executable, str(RUNNER), str(source), str(rf),
                            "--start", str(start_sample / rate), "--seconds", str(sample_count / rate),
                            "--reception-profile", "wiener", "--mlc-iterations", "1"],
                           env=env, stdout=log, stderr=subprocess.STDOUT, check=True)
        native = json.loads((rf / "manifest.json").read_text())
        if (native["returncode"] != 0 or native["status"] not in ("finished", "no_msc_output")
                or b"Reached end of input in offline mode." not in (rf / "dream.log").read_bytes()):
            raise ValueError("Dream did not report a clean finite-input EOF")
        if any(native[k] != v for k, v in (("start_sample", start_sample), ("sample_count", sample_count),
                ("source_frames", selected["source_frames"]), ("source_sample_rate", rate))):
            raise ValueError("native sample extent differs from requested input")
        if identity(source) != stamp:
            raise ValueError("source changed during observation")
        msc_emitted = (rf / "msc.bin").exists()
        cells_emitted = trace.exists()
        if msc_emitted:
            wire.hardlink_to(rf / "msc.bin")
        else:
            wire.touch(exist_ok=False)
        msc_rows = len(read_msc(wire))
        if not cells_emitted:
            if msc_rows:
                raise ValueError("native MSC rows were emitted without the required cell observer")
            with trace.open("xb") as fp:
                fp.write(MAGIC)
        cell_blocks = count_cell_blocks(trace)
        if msc_rows and not cell_blocks:
            raise ValueError("native MSC rows were emitted without a recorded cell block")
        status = "observed"
        if not msc_rows:
            status = "no_msc_output" if cell_blocks else "no_msc_or_cells"
        report.update(status=status, native_msc_file_emitted=msc_emitted, native_cells_file_emitted=cells_emitted,
                      native_msc_rows=msc_rows, cell_blocks=cell_blocks, msc_sha256=file_hash(wire),
                      cells_sha256=file_hash(trace), msc_bytes=wire.stat().st_size, cells_bytes=trace.stat().st_size)
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        report.update(status="failed", error=str(error))
        raise
    finally:
        manifest.write_text(json.dumps(report, indent=2) + "\n")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="stereo PCM16 I/Q WAV or FLAC at 48 kHz or nominal 12 kHz")
    parser.add_argument("--start-sample", required=True, type=int, help="zero-based stereo sample-pair index")
    parser.add_argument("--sample-count", required=True, type=int, help="exact positive count, up to 600 seconds")
    parser.add_argument("--dream", required=True, type=Path, help="offline Dream with the MSCObs1 observer patch")
    parser.add_argument("--out", type=Path, required=True, help="new output directory")
    args = parser.parse_args()
    try:
        report = observe(args.input, args.out, args.dream, start_sample=args.start_sample, sample_count=args.sample_count)
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        parser.exit(2, f"{parser.prog}: {error}\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
