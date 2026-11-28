"""Record or verify the per-cell observations for the published 12:32 UTC receiver pair."""
import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import struct
import subprocess
from tempfile import TemporaryDirectory

import numpy as np


HERE = Path(__file__).resolve().parent
CASE = HERE.parents[1]
HEADER = struct.Struct("<28i")
RECEIVER_INI = "[Receiver]\nfreqint=2\ntimeint=1\nmodmetric=0\nmlciter=1\n"
SITES = ("edogawa", "yokohama")


def digest(path):
    with path.open("rb") as source:
        h = sha256()
        for part in iter(lambda: source.read(65536), b""):
            h.update(part)
    return h.hexdigest()


def read_exact(stream, length):
    data = stream.read(length)
    if len(data) != length:
        raise ValueError("truncated cell trace or native MSC record")
    return data


def check_trace(cells_path, msc_path, *, require_trace_hash=False):
    expected = json.loads((HERE / "expected.json").read_text())
    msc_hash = digest(msc_path)
    station = next((site for site in SITES if expected["sites"][site]["msc_sha256"] == msc_hash), None)
    if station is None:
        raise ValueError("MSC input differs from both published 12:32 native files")
    original = expected["sites"][station]
    config = expected["constant_header"]
    rows = 0
    distinct_bodies = set()
    with cells_path.open("rb") as cells, msc_path.open("rb") as msc:
        if read_exact(cells, 8) != b"MSCObs1\n":
            raise ValueError("unrecognized cell trace version")
        while row_header := cells.read(HEADER.size):
            if len(row_header) != HEADER.size:
                raise ValueError("truncated cell block header")
            h = HEADER.unpack(row_header)
            if (h[0] != rows or h[10] not in (0, 1, 2)
                    or any(value is not None and value != h[i] for i, value in enumerate(config))):
                raise ValueError(f"unexpected field in block {rows} header")
            triples = np.frombuffer(read_exact(cells, 24*h[1]), dtype="<f8").reshape(-1, 3)
            if not np.isfinite(triples).all() or (triples[:, 2] < 0).any():
                raise ValueError(f"invalid cell or channel weight in block {rows}")
            hard = read_exact(cells, (h[2]+7)//8)
            if hard[-1] & ((1 << (-h[2] % 8)) - 1):
                raise ValueError(f"nonzero byte-alignment padding in block {rows}")
            length, = struct.unpack("<I", read_exact(msc, 4))
            if length != h[19]:
                raise ValueError(f"native MSC record {rows} length differs from the signalled stream")
            body = read_exact(msc, length)
            if body != hard[:length]:
                raise ValueError(f"decoded bits differ from native MSC row {rows}")
            distinct_bodies.add(body)
            rows += 1
        if msc.read(1) or rows != original["blocks"] or len(distinct_bodies) != rows:
            raise ValueError("native row count, trace extent or number of distinct MSC bodies differs")
    trace_hash = digest(cells_path)
    exact = trace_hash == original["cells_sha256"]
    if require_trace_hash and not exact:
        raise ValueError("full floating-point trace differs from the recorded build")
    return dict(site=station, blocks=rows, unique_ordered_native_matches=len(distinct_bodies),
                native_msc_sha256=msc_hash, cells_sha256=trace_hash, exact_trace_sha256_match=exact)


def replay(dream, out, require_trace_hash):
    import soundfile as sf

    dream = dream.resolve(strict=True)
    out = out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    sources = {row["site"]: row for row in json.loads((CASE / "iq/replay.json").read_text())}
    reports = {}
    for site in SITES:
        source = sources[site]
        archive = CASE / "iq" / f"{site}-6140khz-iq48.flac"
        if digest(archive) != source["flac_sha256"]:
            raise ValueError(f"{site} FLAC differs from its published hash")
        data, rate = sf.read(archive, dtype="int16", always_2d=True)
        if (rate != 48000 or data.shape != (4320000, 2)
                or sha256(data.astype("<i2", copy=False).tobytes()).hexdigest() != source["pcm_sha256"]):
            raise ValueError(f"{site} PCM differs from its published receipt")
        dest = out / site
        dest.mkdir()
        (dest / "Dream.ini").write_text(RECEIVER_INI, encoding="ascii")
        trace = dest / "cells.bin"
        wire = dest / "msc.bin"
        env = os.environ | dict(QT_QPA_PLATFORM="offscreen", DREAM_FILE_OFFLINE="1",
                                KCBS_DUMP_MSC=str(wire), DREAM_CELL_OBSERVATIONS=str(trace))
        with TemporaryDirectory(dir=dest) as temp, (dest / "receiver.log").open("wb") as log:
            wav = Path(temp) / "from-flac.wav"
            sf.write(wav, data, rate, subtype="PCM_16")
            subprocess.run([dream, "-c", "6", "--sigsrate", "48000", "-m", "1", "-f", wav, "--mlciter", "1"],
                           env=env, cwd=dest, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=180)
        reference = CASE / f"{site}-msc.bin"
        if wire.read_bytes() != reference.read_bytes():
            raise ValueError(f"{site} receiver emitted different hard MSC data")
        report = check_trace(trace, reference, require_trace_hash=require_trace_hash)
        if report["site"] != site:
            raise ValueError(f"wrong native MSC station for {site}")
        reports[site] = report
    reports["observer_binary_sha256"] = digest(dream)
    (out / "verification.json").write_text(json.dumps(reports, indent=2) + "\n")
    return reports


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest="action", required=True)
    run = actions.add_parser("run", help="run both published FLACs through the observer")
    run.add_argument("--dream", required=True, type=Path, help="built Dream executable with the observation patch")
    run.add_argument("--out", required=True, type=Path, help="new output directory")
    check = actions.add_parser("check", help="check every observed block against the published native rows")
    check.add_argument("cells", type=Path)
    check.add_argument("native_msc", type=Path)
    for action in (run, check):
        action.add_argument("--require-trace-hash", action="store_true",
                            help="also require the original binary64 observation digest")
    args = parser.parse_args()
    try:
        if args.action == "run":
            result = replay(args.dream, args.out, args.require_trace_hash)
        else:
            result = check_trace(args.cells, args.native_msc, require_trace_hash=args.require_trace_hash)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        parser.exit(1, f"{parser.prog}: {error}\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
