"""Fetch the nine official floating-point vectors and reproduce the separate fixed-point Annex A encode."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import struct
import subprocess
from tempfile import TemporaryDirectory
from urllib.request import Request, urlopen
import zlib

HERE = Path(__file__).resolve().parent


def digest(data):
    return sha256(data).hexdigest()


def verified_member(corpus, member):
    start, end = member["local_header_offset"], member["last_byte"]
    request = Request(corpus["archive"], headers={"Range": f"bytes={start}-{end}", "User-Agent": "EVS-vector-replay/1.0"})
    with urlopen(request, timeout=60) as response:
        if response.status != 206 or response.headers.get("Content-Range") != f"bytes {start}-{end}/{corpus['archive_bytes']}":
            raise ValueError("official archive returned an unexpected byte range")
        record = response.read(end - start + 2)
    if len(record) != end - start + 1 or digest(record) != member["local_record_sha256"]:
        raise ValueError("ZIP member record differs from the source receipt")
    magic, _, flags, compression, _, _, crc, packed_size, size, name_len, extra_len = struct.unpack(
        "<4s5H3I2H", record[:30])
    if (magic != b"PK\x03\x04" or flags != 0 or compression != 8 or
            (crc, packed_size, size) != (int(member["crc32"], 16), member["compress_size"], member["size"]) or
            record[30:30 + name_len].decode("ascii") != member["name"]):
        raise ValueError("ZIP member header differs from the source receipt")
    packed = record[30 + name_len + extra_len:]
    content = zlib.decompress(packed, wbits=-15)
    if (len(packed) != packed_size or len(content) != size or zlib.crc32(content) != crc or
            digest(content) != member["sha256"]):
        raise ValueError("uncompressed member differs from the source receipt")
    return content


def fetch(corpus, member, root):
    path = root / member["relative_path"]
    if path.exists():
        if digest(path.read_bytes()) != member["sha256"]:
            raise ValueError(f"existing input differs: {path}")
        return
    content = verified_member(corpus, member)
    path.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=path.parent) as tmp:
        staged = Path(tmp) / "verified"
        staged.write_bytes(content)
        staged.replace(path)


def encode_annex(corpus, encoder, root):
    item = corpus["annex_encode"]
    path = root / item["relative_path"]
    if path.exists():
        if digest(path.read_bytes()) != item["sha256"]:
            raise ValueError(f"existing Annex encode differs: {path}")
        return
    with TemporaryDirectory(dir=path.parent) as tmp:
        staged = Path(tmp) / "encoded.192"
        subprocess.run([str(encoder), *item["options"], str(root / item["input_relative_path"]), str(staged)],
                       check=True)
        if digest(staged.read_bytes()) != item["sha256"]:
            raise ValueError("fixed-point encoder output differs from the reference digest")
        staged.replace(path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--fixed", required=True, type=Path, help="TS 26.442 fixed-point EVS_cod executable")
    args = parser.parse_args()
    corpus = json.loads((HERE / "corpus.json").read_bytes())
    for member in corpus["members"]:
        fetch(corpus, member, args.output_dir)
    encode_annex(corpus, args.fixed.resolve(strict=True), args.output_dir)
    print("Verified nine floating-point vectors, the Annex A PCM and the fixed-point Annex A encode.")
