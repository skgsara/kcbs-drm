"""Replay five frozen IQ windows and inspect only the public DRM control channels."""
import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

import soundfile as sf

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from inspect_drm_signalling import inspect_file


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(path):
    with path.open("rb") as stream:
        h = sha256()
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def check_input(case):
    iq = ROOT / case["iq"]
    require(digest(iq) == case["flac_sha256"], f"{iq.name}: FLAC hash mismatch")
    h = sha256()
    with sf.SoundFile(iq) as stream:
        require((stream.format, stream.channels, stream.subtype) == ("FLAC", 2, "PCM_16"), "Unexpected IQ format")
        require((stream.samplerate, stream.frames) == (case["rate_hz"], case["sample_pairs"]), "Unexpected IQ geometry")
        for chunk in stream.blocks(65536, dtype="int16", always_2d=True):
            h.update(chunk.astype("<i2", copy=False).tobytes())
    require(h.hexdigest() == case["pcm_sha256"], f"{iq.name}: decoded sample hash mismatch")
    if case["timing"]:
        require(digest(ROOT / case["timing"]) == case["timing_sha256"], "Timing file hash mismatch")
    return iq


def receive(case, observer, out):
    iq = check_input(case)
    bits = out / (case["id"] + ".bits")
    # A completed pass can emit zero control callbacks. Keep the original empty
    # file in that case, provided the receiver reaches EOF and reproduces its MSC.
    bits.touch(exist_ok=False)
    env = dict(os.environ, KCBS_DREAM=str(observer), KCBS_SIGNALLING_BITS=str(bits),
               QT_QPA_PLATFORM="offscreen", PYTHONDONTWRITEBYTECODE="1", OPENBLAS_NUM_THREADS="1")
    count, rate = case["sample_pairs"], case["rate_hz"]
    require(count % rate == 0, "Frozen input must contain whole seconds")
    with tempfile.TemporaryDirectory(prefix="drm-services-") as scratch:
        trial = Path(scratch) / "receiver"
        command = [sys.executable, "-B", str(ROOT / "scripts/demod_iq_window.py"), str(iq), str(trial),
                   "--start", "0", "--seconds", str(count // rate), "--reception-profile", "wiener",
                   "--mlc-iterations", str(case["iterations"])]
        subprocess.run(command, cwd=scratch, env=env, check=True, stdout=sys.stderr)
        manifest = json.loads((trial / "manifest.json").read_text())
        require(manifest["returncode"] == 0 and "Reached end of input in offline mode." in
                (trial / "dream.log").read_text(), "Receiver did not finish at EOF")
        settings = dict(freqint=2, timeint=1, modmetric=0, mlciter=case["iterations"])
        require(manifest["receiver_settings"] == settings and manifest["channel_offset_hz"] == 0, "Wrong RF settings")
        require((manifest["start_sample"], manifest["sample_count"], manifest["source_frames"]) ==
                (0, count, count), "Wrong sample interval")
        native = trial / "msc.bin"
        require(digest(native) == case["msc_sha256"], f"{case['id']}: native MSC differs")
        rows, remainder = divmod(native.stat().st_size, 732)
        require(remainder == 0, "Incomplete MSC record")
        shutil.copyfile(native, out / (case["id"] + ".msc.bin"))
    return rows


def shared_entities(first, second):
    def counts(report):
        return {s["raw_hex"]: s["count"] for s in report["sdc_entities"]}
    left, right = counts(first), counts(second)
    return [dict(type=int(raw[2], 16), raw_hex=raw, first_count=left[raw], second_count=right[raw])
            for raw in sorted(left.keys() & right.keys())]


def main(observer, out):
    plan = json.loads((HERE / "protocol.json").read_text())
    for rel, pinned in plan["source_tools"].items():
        require(digest(ROOT / rel) == pinned, f"Pinned source changed: {rel}")
    observer_hash = digest(observer)
    reference = observer_hash == plan["observer_sha256"]
    if not reference:
        require(all((HERE / (c["id"] + ".bits")).is_file() for c in plan["cases"]),
                "An independent build requires the published callback files for comparison")
    out.mkdir(parents=True, exist_ok=False)
    reports = {}
    for case in plan["cases"]:
        name = case["id"]
        rows = receive(case, observer, out)
        bits = out / (name + ".bits")
        if not reference:
            require(digest(bits) == digest(HERE / bits.name), f"{name}: callback stream differs")
        result = inspect_file(bits, components=True)
        reports[name] = dict(native_msc_sha256=case["msc_sha256"], native_msc_rows=rows, **result)
    pairs = []
    for time in ("1228", "1232"):
        sites = [time + "-yokohama", time + "-edogawa"]
        pairs.append(dict(sites=sites, shared_sdc_envelopes=shared_entities(*(reports[s] for s in sites))))
    result = dict(protocol_sha256=digest(HERE / "protocol.json"), observer_sha256=observer_hash,
                  cases=reports, pair_comparisons=pairs)
    with (out / "receipt.json").open("x", encoding="utf-8") as stream:
        print(json.dumps(result, ensure_ascii=False, indent=2), file=stream)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("observer", type=Path, help="finite-input Dream with KCBS_SIGNALLING_BITS")
    parser.add_argument("out", type=Path, help="fresh destination for the five raw ledgers and JSON receipt")
    args = parser.parse_args()
    main(args.observer.resolve(), args.out.resolve())
