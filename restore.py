"""Restore the original three PCM I/Q WAVs and timing CSVs, then verify each sealed digest."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
import wave


HERE = Path(__file__).resolve().parent
MANIFEST_SHA256 = "ce3cc49ed15bed848e9a3d7324b8ada328bfb207c607093af51de48377ef6bc5"


def digest(path):
    with path.open("rb") as source:
        h = sha256()
        for block in iter(lambda: source.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def restore_wave(path, recording, parts):
    frames = 0
    pcm = sha256()
    with wave.open(str(path), "wb") as out:
        out.setparams((2, 2, 48000, 0, "NONE", "not compressed"))
        for part in parts:
            source = HERE / part["file"]
            if frames != part["first_sample_pair"] or digest(source) != part["sha256"]:
                raise ValueError(f"part order or digest mismatch at {source.name}")
            with wave.open(str(source), "rb") as inp:
                if (inp.getnchannels(), inp.getsampwidth(), inp.getframerate(), inp.getnframes(),
                    inp.getcomptype()) != (2, 2, 48000, part["sample_pairs"], "NONE"):
                    raise ValueError(f"unexpected WAV geometry in {source.name}")
                for block in iter(lambda: inp.readframes(262144), b""):
                    if len(block) % 4:
                        raise ValueError(f"incomplete I/Q sample in {source.name}")
                    pcm.update(block)
                    out.writeframesraw(block)
                    frames += len(block) // 4
    if frames != recording["sample_pairs"] or pcm.hexdigest() != recording["pcm_sha256"]:
        raise ValueError("reassembled sample count or PCM digest mismatch")


def restore(destination):
    if destination.exists():
        raise ValueError(f"choose a new destination directory: {destination}")
    manifest = HERE / "recordings.json"
    if digest(manifest) != MANIFEST_SHA256:
        raise ValueError("recordings.json differs from the sealed manifest")
    rows = json.loads(manifest.read_bytes())["source_recordings"]
    parts = json.loads((HERE / "parts.json").read_bytes())
    destination.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=destination.parent) as temp:
        files = Path(temp) / "recordings"
        files.mkdir()
        for row in rows:
            for kind in ("wav", "timing"):
                item = row[kind]
                path = files / item["name"]
                if path.name == parts["wav"]:
                    restore_wave(path, row, parts["parts"])
                else:
                    shutil.copyfile(HERE / "iq" / path.name, path)
                if path.stat().st_size != item["size"] or digest(path) != item["sha256"]:
                    raise ValueError(f"restored file differs from the sealed original: {path.name}")
                print(f'{item["sha256"]}  {path.name}')
        shutil.copyfile(manifest, files / manifest.name)
        files.rename(destination)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path, help="new directory for the three recordings and sidecars")
    args = parser.parse_args()
    try:
        restore(args.destination.resolve())
    except (OSError, ValueError, KeyError, wave.Error, EOFError) as error:
        parser.exit(1, f"{error}\n")
