"""Compare stock decoder output for the selected nine cases with the official PCM."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory


HERE = Path(__file__).resolve().parent


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def verify(root, decoder):
    manifest = json.loads((HERE / "reference-members.json").read_text())
    hashes = {member["name"]: member["member_sha256"] for member in manifest["members"]}
    rows = {}
    with TemporaryDirectory() as temp:
        for name in manifest["primary"] + manifest["replication"]:
            coded = root / name
            ref_name = name.replace("/bitstreams/", "/decoded/").replace(".COD", ".OUT")
            reference = root / ref_name
            if digest(coded) != hashes[name] or digest(reference) != hashes[ref_name]:
                raise ValueError(f"changed official input for {name}")
            rate = {"nb": 8, "wb": 16, "swb": 32}[coded.parent.name]
            output = Path(temp) / reference.name
            subprocess.run([str(decoder), str(rate), str(coded), str(output)], check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            if output.read_bytes() != reference.read_bytes():
                raise ValueError(f"decoded PCM differs for {name}")
            rows[name] = dict(pcm_samples=output.stat().st_size // 2, pcm_sha256=digest(output))
    return dict(decoder_sha256=digest(decoder), total_pcm_samples=sum(r["pcm_samples"] for r in rows.values()),
                reference_pcm_exact=rows)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("vectors", type=Path)
    parser.add_argument("decoder", type=Path)
    args = parser.parse_args()
    print(json.dumps(verify(args.vectors.resolve(), args.decoder.resolve()), indent=2))
