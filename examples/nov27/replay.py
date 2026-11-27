"""Decode a supplied clear EVS stream and write the checked 30-second PCM WAV."""
import argparse
import gzip
import hashlib
import io
import json
import subprocess
import tempfile
import wave
from pathlib import Path

HERE = Path(__file__).resolve().parent


def verify(data, expected, label):
    actual = hashlib.sha256(data).hexdigest()
    if actual != expected:
        raise ValueError(f"{label} SHA-256 mismatch: expected {expected}, got {actual}")


def replay(stream, decoder, output):
    manifest = json.loads((HERE / "replay.json").read_text())
    entry = manifest["streams"][stream]
    packed = (HERE / entry["file"]).read_bytes()
    verify(packed, entry["compressed_sha256"], "Compressed input")
    words = gzip.decompress(packed)
    verify(words, entry["g192_sha256"], "G.192 input")

    with tempfile.TemporaryDirectory() as tmp:
        source = Path(tmp) / "programme.192"
        raw = Path(tmp) / "programme.pcm"
        source.write_bytes(words)
        subprocess.run([decoder.resolve(), "-q", "-no_delay_cmp", "16", source, raw], check=True)
        pcm = raw.read_bytes()

    verify(pcm, entry["pcm_sha256"], "Decoded PCM")
    header_and_samples = io.BytesIO()
    with wave.open(header_and_samples, "wb") as audio:
        audio.setparams((1, 2, manifest["sample_rate_hz"], 0, "NONE", "not compressed"))
        audio.writeframes(pcm)
    result = header_and_samples.getvalue()
    verify(result, entry["wav_sha256"], "WAV")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(result)
    print(f"{output}  {entry['wav_sha256']}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stream", choices=("programme", "text-supported"), default="programme")
    parser.add_argument("--decoder", type=Path, default=HERE.parents[1]/"work/evs_gcc_independent/EVS_dec")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    try:
        replay(args.stream, args.decoder, args.out)
    except (OSError, subprocess.CalledProcessError, ValueError) as exc:
        parser.exit(1, f"{parser.prog}: {exc}\n")
