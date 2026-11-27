"""Reproduce the frozen mode-octet experiment on stock EVS controls and the published reconstruction."""
import argparse
from collections import Counter, defaultdict
import csv
from hashlib import sha256
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile

import numpy as np

from check_p2_codec_bits import OFFSETS, ROOT, synthetic_pcm
from build_evs_gcc_independent import linux_command
from compare_evs_group import read_words
from tail_fill_audit import crc


EXAMPLE = ROOT / "examples/nov27"
TRAINING_SHA = "18257ec9536cb2d2c88ee240f54bd866e2cbe90166605501b169cd40d22fef1f"
SOURCE_SHA = {"music": "73d6443ef90a7c022f164e5aa90e56c2291585930b39b1656d0765abbc1f1779",
              "speech": "f09254a0daf4b14b292868d46dc2e3c8e158d19fafff739ad4c3931e2ce7b1b0"}
SENDER_SHA = {"music": "302a44f00ee12d2110315f9dd6c404c276df734790572089e7283e6f5220df5b",
              "speech": "fb188fe607646bc31774b428ec5652fa210a0b4ecca7bbfd47f2bfd4cc1a1b3d"}
PREDICTION_SHA = {"release": "0ccf4ad541b4fbbdaf8829e43fe6317ff98072fcad8355e46c07867e19c8e74b",
                  "music": "0e7b26c10ce27193c02ad8895f21afaee3ab5b468845d0d2c9ed4d3ed071986a",
                  "speech": "56e78a695f85887c71a6de284082eb00ca6ad6f6ed59e73efefe41cf30a20986"}


def require(ok, message):
    if not ok:
        raise ValueError(message)


def encode(encoder, pcm, path):
    subprocess.run(linux_command(encoder, "-q", "-no_delay_cmp", "-max_band", "SWB", "13200", "32", pcm, path),
                   check=True, stdout=subprocess.DEVNULL)


def train(path):
    require(sha256(path.read_bytes()).hexdigest() == TRAINING_SHA, "Synthetic training G.192 differs from the frozen run")
    counts = defaultdict(lambda: [Counter() for _ in OFFSETS])
    for word in read_words(path):
        for hist, offset in zip(counts[word[0]], OFFSETS, strict=True):
            hist[word[1 + offset]] += 1
    model = {}
    for mode, cells in counts.items():
        plurality = [min(hist, key=lambda v: (-hist[v], v)) for hist in cells]
        unanimous = [v if len(hist) == 1 and sum(hist.values()) >= 15 else None
                     for v, hist in zip(plurality, cells, strict=True)]
        model[mode] = plurality, unanimous
    return model


def release_headers():
    evidence = json.loads((EXAMPLE / "validation/evidence.json").read_bytes())
    selected = {tuple(pair) for pair in evidence["inferred_counter_positions"]["position_two_signs"]}
    with np.load(EXAMPLE / "receiver/packets.npz", allow_pickle=False) as archive:
        units = {}
        for tick, row, flags in zip(archive["ticks"], archive["packets"], archive["packet_ok"], strict=True):
            unit = row.tobytes()
            require(flags.all() and len(unit) == 716 and crc(unit[:-2]) == int.from_bytes(unit[-2:], "big"),
                    "Incomplete or CRC-invalid released DU")
            units[int(tick)] = unit
    headers = []
    with (EXAMPLE / "frames.csv").open(newline="") as f:
        for slot, row in enumerate(csv.DictReader(f)):
            counter, phase, cycle, position = (int(row[k]) for k in ("counter", "phase", "cycle", "position"))
            if (counter, position) in selected and row["source"] == "inferred":
                require(position == 2, "Unexpected position in release selection")
                mode = units[3 * counter + phase][39 + 131 * cycle]
                headers.append((slot, counter, mode))
    return headers


def sender_headers(path):
    # A stock encoder frame has a four-byte G.192 header and 264 two-byte symbols.
    frames, remainder = divmod(path.stat().st_size, 532)
    require(not remainder, "Incomplete sender G.192 frame")
    with path.open("rb") as f:
        for slot in range(1, frames // 60 * 60, 4):
            f.seek(532 * slot)
            sync, length, *symbols = struct.unpack("<10H", f.read(20))
            require((sync, length) == (0x6b21, 264) and set(symbols) <= {0x7f, 0x81}, "Invalid mode octet")
            mode = sum((v == 0x81) << (7 - j) for j, v in enumerate(symbols))
            yield slot, slot // 60, mode


def frozen_predictions(headers, model, name):
    rows = []
    for slot, counter, mode in headers:
        abstentions = [None] * len(OFFSETS)
        plurality, unanimous = model.get(mode, (abstentions, abstentions))
        rows.append(dict(slot=slot, counter=counter, mode=mode, plurality=plurality, unanimous=unanimous))
    serialized = (json.dumps(rows, separators=(",", ":")) + "\n").encode()
    require(sha256(serialized).hexdigest() == PREDICTION_SHA[name], f"{name} predictions differ from frozen digest")
    return rows


def score(name, rows, words, writer):
    counters = np.array([r["counter"] for r in rows])
    targets = [words[r["slot"]] for r in rows]
    require(all(len(w) == 33 and w[0] == r["mode"] for w, r in zip(targets, rows, strict=True)),
            "Answer extent or mode disagrees with frozen coordinates")
    actual = np.array([[w[1 + offset] for offset in OFFSETS] for w in targets])
    full_groups = [c for c, count in Counter(counters).items() if count == 15]
    for rule in ("plurality", "unanimous", "zero"):
        estimates = np.zeros_like(actual) if rule == "zero" else np.array(
            [[-1 if v is None else v for v in r[rule]] for r in rows])
        issued, hits = estimates >= 0, estimates == actual
        exact_columns = sum(np.all(hits[counters == c], axis=0).sum() for c in full_groups)
        writer.writerow([name, rule, len(rows), hits.sum(), issued.sum(), actual.size - issued.sum(),
                         hits.all(axis=1).sum(), issued.all(axis=1).sum(), exact_columns, 6 * len(full_groups)])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--encoder", type=Path, default=ROOT / "work/evs_gcc_independent/EVS_cod")
    parser.add_argument("--music", type=Path, help="original librosa example Kevin_MacLeod_-_Vibe_Ace.hq.ogg")
    parser.add_argument("--speech", type=Path, help="original librosa example 5703-47212-0000.hq.ogg")
    args = parser.parse_args()
    encoder = args.encoder.resolve()
    with tempfile.TemporaryDirectory() as directory:
        tmp = Path(directory)
        pcm, training = tmp / "training.s16", tmp / "training.192"
        pcm.write_bytes(synthetic_pcm())
        encode(encoder, pcm, training)
        model = train(training)
        predictions = frozen_predictions(release_headers(), model, "release")
        sender_cases = {}
        for name, clip in (("music", args.music), ("speech", args.speech)):
            if clip is None:
                print(f"{name} control skipped; supply --{name} with the original OGG to include it.", file=sys.stderr)
                continue
            require(sha256(clip.read_bytes()).hexdigest() == SOURCE_SHA[name], f"Wrong {name} source OGG")
            pcm, stream = tmp / f"{name}.s16", tmp / f"{name}.192"
            trim = ["-af", "aresample=32000,atrim=end_sample=1536000"] if name == "music" else []
            subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-i", str(clip), "-map", "0:a:0", *trim,
                            "-ac", "1", "-ar", "32000", "-c:a", "pcm_s16le", "-f", "s16le", str(pcm)], check=True)
            encode(encoder, pcm, stream)
            sender_cases[name] = frozen_predictions(sender_headers(stream), model, name), stream

        writer = csv.writer(sys.stdout, delimiter="\t", lineterminator="\n")
        writer.writerow(["case", "rule", "words", "correct_bytes", "attempted_bytes", "abstained_bytes",
                         "all_six_exact", "all_six_attempted", "all_15_exact_columns", "eligible_15_word_columns"])
        for name, (rows, stream) in sender_cases.items():
            require(sha256(stream.read_bytes()).hexdigest() == SENDER_SHA[name],
                    f"{name} sender output differs from the frozen stream; check FFmpeg and encoder versions")
            score(name, rows, list(read_words(stream)), writer)
        stream = EXAMPLE / "programme.192.gz"
        release = json.loads((EXAMPLE / "replay.json").read_bytes())
        require(sha256(stream.read_bytes()).hexdigest() == release["streams"]["programme"]["compressed_sha256"],
                "Released reconstruction differs from its receipt")
        words = list(read_words(stream))
        score("reconstruction_30s", predictions, words, writer)
        score("reconstruction_12s", [r for r in predictions if 43854890 <= r["counter"] <= 43854899], words, writer)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        sys.exit(str(error))
