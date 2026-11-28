"""Test which stock EVS encodes of a repeated synthetic programme are bit-identical."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))
from check_evs_origin import PROJECTED_OCTETS
from compare_evs_group import read_words

RATE = 32000
FRAME = 640
SLOTS = 300
OPTIONS = ["-q", "-no_delay_cmp", "-max_band", "SWB", "13200", "32"]


def melody():
    """7 s of integer-synthesized melody with a fifth and a bass tone, enough for all cuts."""
    notes = (262, 330, 392, 523, 440, 392, 330, 294, 349, 440, 523, 587, 523, 440,
             392, 330, 294, 370, 440, 554, 494, 440, 370, 330, 262, 330, 392, 523)
    length = RATE // 4
    t = np.arange(length, dtype=np.int64)
    envelope = np.minimum(np.minimum(t + 1, length - t), 320)
    def triangle(frequency):
        phase = (t * frequency) % RATE
        return 2 * np.abs(2 * phase - RATE) - RATE
    chunks = []
    for note in notes:
        oscillators = 5 * triangle(note) + 2 * triangle(3 * note // 2) + triangle(note // 2)
        values = oscillators * envelope // (8 * 1280)
        chunks.append(values.astype("<i2"))
    return np.concatenate(chunks)


def encode(encoder, scratch, name, source):
    raw = source.astype("<i2", copy=False).tobytes()
    pcm, dest = scratch / (name + ".pcm"), scratch / (name + ".192")
    pcm.write_bytes(raw)
    process = subprocess.run([encoder, *OPTIONS, pcm, dest], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    if process.returncode:
        raise RuntimeError(process.stderr.decode(errors="replace"))
    words = list(read_words(dest))
    if len(words) != len(source) // FRAME or any(word is None or len(word) != 33 for word in words):
        raise ValueError(f"{name}: expected a good 264-bit word for every 640 input samples")
    return words, dict(pcm_samples=len(source), input_pcm_sha256=sha256(raw).hexdigest(),
                       g192_sha256=sha256(dest.read_bytes()).hexdigest(), encoded_words=len(words))


def compare(a, b, words_a, words_b, first, stop):
    """Samples and words here both use programme-relative frame indices."""
    full = []
    projected = []
    modes = 0
    for x, y in zip(words_a[first:stop], words_b[first:stop], strict=True):
        full.append(x == y)
        projected.append(all(x[i] == y[i] for i in PROJECTED_OCTETS))
        modes += int(x[0] == y[0])
    x = a[first * FRAME:stop * FRAME].reshape(-1, FRAME)
    y = b[first * FRAME:stop * FRAME].reshape(-1, FRAME)
    if not len(full) == len(x) == len(y) == stop - first:
        raise ValueError("word/sample extent mismatch")
    differing = [first + i for i, exact in enumerate(full) if not exact]
    return dict(slots_half_open=[first, stop], compared=len(full),
                equal_local_pcm_windows=int(np.all(x == y, axis=1).sum()),
                equal_modes=modes, equal_22_direct_octet_views=sum(projected), equal_full_33_octet_words=sum(full),
                first_different_full_word=differing[0] if differing else None,
                last_different_full_word=differing[-1] if differing else None)


def run(encoder):
    master = melody()
    end = SLOTS * FRAME
    original = master[:end]
    history = RATE
    signals = dict(
        original=original, exact_replay=original.copy(), grid_plus_1ms=master[32:32 + end],
        grid_plus_10ms=master[320:320 + end], half_amplitude=(original // 2).astype("<i2"),
        zero_history=np.concatenate((np.zeros(history, dtype="<i2"), original)),
        melody_history=np.concatenate((master[-history:], original)),
    )
    encodes, hashes = {}, {}
    with TemporaryDirectory() as tmp:
        for name, signal in signals.items():
            encodes[name], hashes[name] = encode(encoder, Path(tmp), name, signal)
    histories = {"zero_history": history // FRAME, "melody_history": history // FRAME}
    comparisons = {}
    for right in ("exact_replay", "grid_plus_1ms", "grid_plus_10ms", "half_amplitude", "melody_history"):
        left = "zero_history" if right == "melody_history" else "original"
        start_a, start_b = histories.get(left, 0), histories.get(right, 0)
        a, b = signals[left][start_a * FRAME:], signals[right][start_b * FRAME:]
        w_a, w_b = encodes[left][start_a:], encodes[right][start_b:]
        offset = {"grid_plus_1ms": 32, "grid_plus_10ms": 320}.get(right, 0)
        overlap = len(a) - offset
        comparisons[right] = dict(
            reference_stream=left, tested_stream=right, reference_first_programme_slot=start_a,
            tested_first_programme_slot=start_b, tested_pcm_origin_minus_reference_samples=offset,
            aligned_pcm_overlap_samples=overlap,
            aligned_overlap_pcm_exact=bool(np.array_equal(a[offset:], b[:overlap])),
            full=compare(a, b, w_a, w_b, 0, SLOTS), interior=compare(a, b, w_a, w_b, 50, 250),
        )
    exact = comparisons["exact_replay"]["full"]
    if exact["equal_full_33_octet_words"] != SLOTS or hashes["original"] != hashes["exact_replay"]:
        raise ValueError("identical fresh encoder runs gave different outputs")
    return dict(
        format="stock-evs-repeated-programme-v1", encoder_options=OPTIONS, pcm_rate_hz=RATE,
        samples_per_20ms_word=FRAME, programme_slots=SLOTS, direct_physical_word_octets=list(PROJECTED_OCTETS),
        encoder_executable_sha256=sha256(encoder.read_bytes()).hexdigest(), source_encodes=hashes,
        comparison_basis="All pairs use the same programme-relative slot ordinal, fixed without inspecting words. "
                         "A +32/+320 sample origin shifts every 20 ms encoder input window; those clocks have "
                         "no coincident boundary. The PCM overlap compares identical original sample coordinates. "
                         "At +320 samples, equal ordinals select the earlier of two equidistant reference boundaries. "
                         "The history comparison omits the first 50 encoded preamble words on both sides.",
        comparisons=comparisons,
    )


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--encoder", type=Path, default=ROOT / "work/evs_gcc_independent/EVS_cod")
    args = cli.parse_args()
    print(json.dumps(run(args.encoder.resolve(strict=True)), indent=2))
