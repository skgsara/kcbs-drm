"""Replay the frozen 22-second November 19 interval from its original CS8 bytes."""
import argparse
from collections import Counter
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys
import wave

import numpy as np
from scipy.signal import periodogram
import soundfile as sf

SCRIPTS = Path(__file__).resolve().parents[3] / "scripts"
sys.path.insert(0, str(SCRIPTS))
from extract_iq_channel import extract
from project_evs_group import checked_units, project_group
from evs_intra_word import intra_word

SOURCE_BYTES = 40128000
REGISTRY_SHA = "e427fc185468a067f6cfe477ab3cee8d600d699685efb69c3cafb9d35c53411d"


def digest(path):
    with path.open("rb") as f:
        return sha256(f.read()).hexdigest()

def sample_digest(path):
    samples, rate = sf.read(path, dtype="float32", always_2d=True)
    return sha256(samples.astype("<f4", copy=False).tobytes()).hexdigest()


def wrap_cs8(source, output):
    if source.stat().st_size != SOURCE_BYTES:
        raise ValueError("the source must be the exact 22-second CS8 interval")
    # Translate signed 8-bit CS8 to unsigned 8-bit PCM without quantization.
    table = bytes(n ^ 128 for n in range(256))
    with source.open("rb") as f, wave.open(str(output), "wb") as wav:
        wav.setparams((2, 1, 912000, 0, "NONE", "not compressed"))
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            wav.writeframesraw(chunk.translate(table))


def am_carrier(path):
    x, rate = sf.read(path)
    z = x[:, 0] + 1j * x[:, 1]
    windows = []
    for second in range(1, len(z) // rate - 1):
        freq, power = periodogram(z[second * rate:(second + 1) * rate], fs=rate,
                                  window="hann", detrend=False, return_onesided=False)
        candidates = np.flatnonzero(abs(freq) <= 200)
        peak = candidates[power[candidates].argmax()]
        background = np.median(power[(abs(freq) >= 300) & (abs(freq) <= 2400)])
        windows.append(dict(second=second, offset_hz=float(freq[peak]),
                            carrier_db_over_background=round(float(10 * np.log10(power[peak] / background)), 3)))
    return windows


def run(args):
    out = args.output.resolve()
    registry = args.inventory.read_bytes()
    if sha256(registry).hexdigest() != REGISTRY_SHA:
        raise ValueError("expected the frozen historical registry")
    old = set(json.loads(registry)["counter_ids"])
    out.mkdir(parents=True, exist_ok=False)
    wide = out / "input.wav"
    wrap_cs8(args.cs8, wide)
    digital, analog = out / "6140.wav", out / "6100.wav"
    extract(wide, digital, 0)
    extract(wide, analog, -40000)
    env = dict(os.environ, KCBS_DREAM=str(args.dream.resolve()))
    for args_list in [
        [SCRIPTS / "demod_iq_window.py", digital, out / "rf", "--seconds", "22",
         "--reception-profile", "wiener", "--mlc-iterations", "1"],
        [SCRIPTS / "salvage_msc_packets.py", out / "rf/msc.bin", "--transport-only", "--out", out / "du"],
    ]:
        subprocess.run([sys.executable, "-B", *map(str, args_list)], env=env, check=True)
    archive = out / "du/data_units.npz"
    phases = {}
    for count, phase, unit in checked_units(archive):
        phases.setdefault(count, set()).add(phase)
    provenance = json.loads((out / "du/provenance.json").read_bytes())
    assigned = sorted({int(key.split(",")[0]) for key in provenance})
    overlap = sorted(old.intersection(assigned))
    starts = {int(key.split(",")[0]): min(v[1] for v in rows)
              for key, rows in provenance.items() if key.endswith(",0,0")}
    complete = sorted((count for count in phases if len(phases[count]) == 3), key=starts.__getitem__)
    primary = complete[0] if complete and not overlap else None
    rows = []
    counts = {str(pos): Counter() for pos in range(1, 5)}
    for count in complete:
        group = project_group(archive, count)
        fields = [r for r in intra_word(group["slots"])["slots"] if r["check"] == "swb_hq_class"]
        for f in fields:
            mode = group["slots"][f["slot"]]["octets"][:2].upper()
            counts[str(f["position"])][mode] += 1
            rows.append(dict(counter=count, slot=f["slot"], position=f["position"], mode=mode,
                             word_bits=f["word_bits"], allowed=f["allowed"]))
    if primary is not None:
        projection = project_group(archive, primary)
        (out / "primary.json").write_text(json.dumps(projection, indent=2) + "\n")
    receipt = dict(source_cs8_sha256=digest(args.cs8), source_byte_range=[280896000, 321024000],
                   digital_iq_sha256=digest(digital), am_iq_sha256=digest(analog),
                   digital_float32_iq_sha256=sample_digest(digital), am_float32_iq_sha256=sample_digest(analog),
                   digital_iq_frames=sf.info(digital).frames, am_iq_frames=sf.info(analog).frames,
                   inventory_sha256=REGISTRY_SHA, assigned_counters=assigned, previously_seen=overlap,
                   checked_du_count=sum(map(len, phases.values())), complete_in_time_order=complete, primary=primary,
                   class_by_position=counts, class_cases=rows, am_interior_seconds=am_carrier(analog),
                   digital_msc_sha256=digest(out / "rf/msc.bin"), archive_sha256=digest(archive))
    (out / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("cs8", "inventory", "dream", "output"):
        p.add_argument(name, type=Path)
    run(p.parse_args())
