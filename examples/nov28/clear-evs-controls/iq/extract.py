"""Extract the preregistered 12 kHz stereo interval from the contributor's original WAV."""
import argparse
from hashlib import sha256
from pathlib import Path
import wave

import numpy as np
import soundfile as sf

START = 2880000
STOP = 4320000
SOURCE_SHA256 = "8ba5576dc9ab560c14a1de3b7def1a176c2f3e95010dfabe890ab002f40bb624"


def extract(source, output):
    if sha256(source.read_bytes()).hexdigest() != SOURCE_SHA256:
        raise ValueError("Original WAV differs from the published digest")
    with wave.open(str(source), "rb") as reader:
        if (reader.getframerate(), reader.getnchannels(), reader.getsampwidth(), reader.getnframes()) != (12000, 2, 2, 7330304):
            raise ValueError("Unexpected source WAV format or length")
        reader.setpos(START)
        raw = reader.readframes(STOP - START)
    if len(raw) != (STOP - START) * 4:
        raise ValueError("Truncated selected IQ interval")
    with output.open("xb") as target:
        sf.write(target, np.frombuffer(raw, dtype="<i2").reshape(-1, 2), 12000, format="FLAC", subtype="PCM_16")
    decoded, rate = sf.read(output, dtype="int16", always_2d=True)
    if rate != 12000 or decoded.shape != (STOP - START, 2) or decoded.astype("<i2", copy=False).tobytes() != raw:
        raise ValueError("FLAC reconstruction differs from the source samples")
    print("PCM SHA-256", sha256(raw).hexdigest())
    print("FLAC SHA-256", sha256(output.read_bytes()).hexdigest())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    extract(args.source, args.output)
