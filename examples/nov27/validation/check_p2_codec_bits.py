"""Measure single-bit variation at six payload offsets in synthetic, clear EVS words."""
import argparse
from collections import defaultdict
from hashlib import sha256
from pathlib import Path
import subprocess
import sys
import tempfile

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))
from build_evs_gcc_independent import linux_command
from compare_evs_group import read_words

OFFSETS = (15, 18, 21, 24, 27, 30)


def synthetic_pcm():
    rng = np.random.default_rng(13200)
    t = np.arange(32000) / 32000
    envelope = (0.5 + 0.5 * np.sin(2 * np.pi * 3.2 * t)) ** 2
    chunks = []
    for second in range(48):
        frequency = (128, 165, 230, 320, 115, 145)[second % 6]
        phase = frequency * t + 0.5 * (5 + second % 17) * t * t
        harmonic = sum(np.cos(2 * np.pi * j * phase) / j**0.8 for j in range(1, 80))
        noise = rng.normal(size=len(t))
        choices = (harmonic * envelope, 0.4 * noise * envelope,
                   harmonic * 0.05 + 0.1 * noise, np.zeros_like(t))
        chunks.append(np.clip(3500 * choices[second % 4], -32000, 32000).astype("<i2"))
    return np.concatenate(chunks).tobytes()


def check(encoder):
    with tempfile.TemporaryDirectory() as tmp:
        source, stream = Path(tmp) / "input.s16", Path(tmp) / "clear.192"
        source.write_bytes(synthetic_pcm())
        subprocess.run(linux_command(encoder, "-q", "-no_delay_cmp", "-max_band", "SWB", "13200", "32",
                                     source, stream), check=True)
        print("Clear G.192 SHA-256", sha256(stream.read_bytes()).hexdigest())
        cases = defaultdict(list)
        for slot, word in enumerate(read_words(stream)):
            if slot % 4 != 1:
                continue
            # Selected SWB entries of the 13.2 kb/s acelp_sig_tbl in TS 26.443.
            index = word[0] >> 3
            if index == 31:
                family = "TCX20" if word[0] & 4 else "HQ"
            elif index in (13, 14):
                family = "GSC AUDIO" if index == 13 else "GSC INACTIVE"
            else:
                continue
            cases[family].append([word[1 + offset] for offset in OFFSETS])
    for family, rows in sorted(cases.items()):
        values = np.array(rows, dtype=np.uint8)
        varied = np.bitwise_or.reduce(values) ^ np.bitwise_and.reduce(values)
        print(f"{family}: {len(rows)} second-position words, "
              f"{sum(int(bits).bit_count() for bits in varied)}/48 bits took both values")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--encoder", type=Path, default=ROOT / "work/evs_gcc_independent/EVS_cod")
    check(parser.parse_args().encoder.resolve())
