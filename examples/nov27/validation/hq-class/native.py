"""Check the SWB HQ class restriction on stock EVS words from three generated signals."""
import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
import tempfile

import numpy as np

from observe import restriction

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from check_p2_codec_bits import ROOT, synthetic_pcm
from build_evs_gcc_independent import linux_command
from compare_evs_group import read_words
sys.path.insert(0, str(HERE.parent / "tcx-zero-pair"))
from control import make_pcm


def tonal_bank():
    """36 seconds of harmonic chords, pitched percussion and pulsed broadband noise."""
    rng = np.random.default_rng(27112026)
    t = np.arange(32000) / 32000
    frames = []
    for second in range(36):
        root = (220, 330, 440, 550)[second % 4]
        chord = np.zeros_like(t)
        for ratio in (1, 1.25, 1.5):
            harmonics = range(1, int(14900 / (root * ratio)) + 1)
            for h in harmonics:
                chord += np.sin(2 * np.pi * root * ratio * h * t + h * 0.7) / h**0.6
        chord /= np.max(np.abs(chord))
        beat = np.exp(-17 * np.remainder(t * (2 + second % 4), 1))
        noise = rng.uniform(-1, 1, len(t))
        choices = (chord, chord * (.03 + .97 * beat), .85 * chord + .45 * noise * beat,
                   .35 * chord + .60 * noise, .5 * chord * beat + .35 * noise * beat,
                   .60 * noise * beat)
        samples = np.rint(17000 * choices[second // 6])
        frames.append(np.clip(samples, -32768, 32767).astype("<i2"))
    return np.concatenate(frames).tobytes()


def run(encoder):
    results = {}
    with tempfile.TemporaryDirectory() as tmp:
        source, stream = Path(tmp) / "source.s16", Path(tmp) / "clean.192"
        for name, generate in (("synthetic_pcm", synthetic_pcm), ("tcx_zero_pair", make_pcm),
                               ("tonal_bank", tonal_bank)):
            pcm = generate()
            source.write_bytes(pcm)
            subprocess.run(linux_command(encoder, "-q", "-no_delay_cmp", "-max_band", "SWB",
                                         "13200", "32", source, stream), check=True, stdout=sys.stderr)
            words = list(read_words(stream))
            if len(words) * 1280 != len(pcm) or any(len(word) != 33 for word in words):
                raise ValueError(f"{name} requires one complete 264-bit word per 20 ms")
            modes = {f"{mode:02X}": Counter() for mode in range(0xF8, 0xFC)}
            classes = Counter()
            violations = 0
            for word in words:
                mode = word[0]
                if not 0xF8 <= mode <= 0xFB:
                    continue
                prefix = word[1] >> 6
                modes[f"{mode:02X}"][f"{prefix:02b}"] += 1
                # With an ACELP predecessor, the extra length bit moves class start to b8.
                hq_class = prefix if mode & 2 else ((mode & 1) << 1) | (prefix >> 1)
                classes[str(hq_class)] += 1
                accepted = restriction(mode)
                if accepted is not None and prefix not in accepted:
                    violations += 1
            results[name] = dict(words=len(words), pcm_sha256=sha256(pcm).hexdigest(),
                                 g192_sha256=sha256(stream.read_bytes()).hexdigest(),
                                 payload_high_two_by_mode=modes, swb_hq_classes=classes,
                                 conditional_words=sum(sum(modes[m].values()) for m in ("F9", "FA", "FB")),
                                 violations=violations)
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--encoder", type=Path, default=ROOT / "work/evs_gcc_independent/EVS_cod")
    result = run(parser.parse_args().encoder.resolve())
    print(json.dumps(result, indent=2))
    if result != json.loads((HERE / "native-expected.json").read_text()):
        raise SystemExit("sender fixture digests or observations differ from native-expected.json")
    if any(row["violations"] for row in result.values()):
        raise SystemExit("the supplied stock sender contradicted the restriction")
