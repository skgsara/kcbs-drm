"""Map each I and Q sample independently to +8192 for zero or positive, or −8192 for negative.

The output is a stereo PCM16 WAV with the input's sample rate, ordering and length.
"""
import argparse
from pathlib import Path
import wave

import numpy as np
import soundfile as sf


def quantize(source, destination):
    """Convert a real-valued pair of WAV channels without an adaptive threshold or gain."""
    with sf.SoundFile(source) as reader:
        if reader.format not in {"WAV", "WAVEX", "RF64"} or reader.channels != 2:
            raise ValueError("expected a stereo IQ WAV")
        if reader.subtype in {"FLOAT", "DOUBLE"}:
            dtype = "float64"
        elif reader.subtype in {"PCM_U8", "PCM_16", "PCM_24", "PCM_32"}:
            dtype = "int32"
        else:
            raise ValueError(f"unsupported WAV encoding: {reader.subtype}")
        if not 0 < reader.frames <= (0xffffffff - 36) // 4:
            raise ValueError("source must be nonempty and fit a stereo PCM16 RIFF WAV")

        with destination.open("xb") as output:
            try:
                with wave.open(output, "wb") as writer:
                    writer.setparams((2, 2, reader.samplerate, reader.frames, "NONE", "not compressed"))
                    count = 0
                    for values in reader.blocks(blocksize=65536, dtype=dtype, always_2d=True):
                        if dtype == "float64" and not np.isfinite(values).all():
                            raise ValueError("non-finite IQ sample")
                        pairs = np.where(values >= 0, 8192, -8192).astype("<i2")
                        writer.writeframesraw(pairs.tobytes())
                        count += len(pairs)
                    if count != reader.frames:
                        raise ValueError("incomplete source")
            except BaseException:
                output.close()
                destination.unlink()
                raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path, help="new WAV file")
    args = parser.parse_args()
    quantize(args.source, args.destination)
