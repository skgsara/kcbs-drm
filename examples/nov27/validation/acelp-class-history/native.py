"""Check the frozen ACELP class rule on clear output from a stock EVS encoder."""
import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
import tempfile

from check import score

VALIDATION = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(VALIDATION))
from check_p2_codec_bits import ROOT, synthetic_pcm
from build_evs_gcc_independent import linux_command
from compare_evs_group import read_words


def check_cap(encoder, cap, source, stream, expected_slots):
    command = linux_command(encoder, "-q", "-no_delay_cmp", "-max_band", cap,
                            "13200", "32", source, stream)
    # Retain encoder diagnostics on stderr and keep stdout machine-readable.
    subprocess.run(command, check=True, stdout=sys.stderr)
    words = list(read_words(stream))
    if len(words) != expected_slots or len(words) % 60 or any(len(word) != 33 for word in words):
        raise ValueError(f"{cap} control requires a complete 264-bit word in every 20 ms slot")
    counts = Counter()
    for start in range(0, len(words), 60):
        observations = [(word[0], word[6]) for word in words[start:start + 60]]
        counts.update(score(start // 60, observations)["counts"])
    return dict(words=len(words), groups=len(words) // 60,
                g192_sha256=sha256(stream.read_bytes()).hexdigest(), counts=dict(counts))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--encoder", type=Path, default=ROOT / "work/evs_gcc_independent/EVS_cod")
    encoder = parser.parse_args().encoder.resolve()
    pcm = synthetic_pcm()
    # The generator produces 32 kHz mono signed 16-bit samples.
    slots, remainder = divmod(len(pcm), 640 * 2)
    if remainder or not slots:
        raise ValueError("synthetic input must contain complete 20 ms slots")
    with tempfile.TemporaryDirectory() as directory:
        source = Path(directory) / "source.s16"
        source.write_bytes(pcm)
        caps = {cap: check_cap(encoder, cap, source, source.with_suffix(f".{cap}.192"), slots)
                for cap in ("NB", "WB", "SWB")}
    print(json.dumps(dict(pcm_sha256=sha256(pcm).hexdigest(), caps=caps), indent=2))
    return int(any(not result["counts"]["restrictive_pairs"] or result["counts"]["contradictions"]
                   or result["counts"]["wrong_msb"] for result in caps.values()))


if __name__ == "__main__":
    sys.exit(main())
