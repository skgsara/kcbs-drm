"""Rebuild a recorder's original PCM I/Q WAV from its published FLAC parts and verify it.

Usage, from the data branch root:  python restore.py <session>/<recording> out.wav
Each part's file SHA-256 and first sample pair are checked against parts.json. The
reassembled PCM must match the recorder's iq_pcm_sha256 and sample count in receipt.json.
Requires the Python SoundFile package.
"""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import wave

import soundfile as sf


def file_digest(path):
    h = sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def restore(folder, out):
    folder = Path(folder)
    parts = json.loads((folder / "parts.json").read_text(encoding="utf-8"))
    receipt = json.loads((folder / "receipt.json").read_text(encoding="utf-8"))
    if Path(out).exists():
        raise SystemExit(f"refusing to overwrite {out}")
    pcm, frames = sha256(), 0
    with wave.open(str(out), "wb") as dst:
        dst.setparams((2, 2, 48000, 0, "NONE", "not compressed"))
        for part in parts["parts"]:
            path = folder / part["file"]
            if file_digest(path) != part["sha256"] or frames != part["first_sample_pair"]:
                raise SystemExit(f"digest or order mismatch at {path.name}")
            with sf.SoundFile(str(path)) as src:
                if (src.samplerate, src.channels, src.frames) != (48000, 2, part["sample_pairs"]):
                    raise SystemExit(f"unexpected geometry in {path.name}")
                for block in src.blocks(blocksize=480000, dtype="int16"):
                    raw = block.astype("<i2", copy=False).tobytes()
                    pcm.update(raw)
                    dst.writeframesraw(raw)
                    frames += len(block)
    if frames != receipt["sample_pairs"] or pcm.hexdigest() != receipt["iq_pcm_sha256"]:
        raise SystemExit("reassembled sample count or PCM digest differs from the recorder receipt")
    print(json.dumps(dict(restored=str(out), sample_pairs=frames, iq_pcm_sha256=pcm.hexdigest())))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("recording", help="folder holding parts.json, receipt.json and part-NN.flac")
    ap.add_argument("out", help="new WAV path")
    a = ap.parse_args()
    restore(a.recording, a.out)
