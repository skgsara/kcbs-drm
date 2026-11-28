"""Download the nine selected official EVS test streams and decoded references by ZIP range."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import re
import struct
import subprocess
import tempfile
import zipfile
import zlib


URL = (
    "https://www.3gpp.org/ftp/Specs/archive/26_series/26.444/test_sequences/"
    "26444_ce0_da0_e60_f40_g50-TestSeq_BASOP_26442.zip"
)
ARCHIVE_BYTES = 1843592537
MAX_RANGE_BYTES = 4_000_000
NORMAL_MEMBERS = {
    f"testvec/testv/{folder}/{band}/stv{rate}{condition}_13200_{rate}kHz.{ext}"
    for band, rate in (("nb", 8), ("wb", 16), ("swb", 32))
    for condition in ("c", "n1", "n2")
    for folder, ext in (("bitstreams", "COD"), ("decoded", "OUT"))
}


def require(ok, message):
    if not ok:
        raise ValueError(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def read_range(start, end):
    length = end - start + 1
    require(0 <= start <= end < ARCHIVE_BYTES and length <= MAX_RANGE_BYTES,
            "range outside official archive or exceeds expected member size")
    with tempfile.TemporaryDirectory() as tmp:
        header_path = Path(tmp) / "headers"
        completed = subprocess.run([
            "curl", "--fail", "--silent", "--show-error", "--retry", "2",
            "--max-time", "60", "--max-filesize", str(length), "--range", f"{start}-{end}",
            "--dump-header", str(header_path), URL
        ], check=True, stdout=subprocess.PIPE)
        headers = header_path.read_text("latin-1").lower().splitlines()
        require(any(re.match(r"^http/\S+ 206(?:\s|$)", line) for line in headers),
                "server did not honor the range request")
        require(f"content-range: bytes {start}-{end}/{ARCHIVE_BYTES}" in headers,
                "server returned an unexpected ZIP range")
        require(len(completed.stdout) == length, "short ZIP range")
        return completed.stdout


def check_index(manifest):
    central = read_range(*manifest["central_range"])
    tail = read_range(*manifest["tail_range"])
    require(digest(central) == manifest["central_sha256"] and digest(tail) == manifest["tail_sha256"],
            "ZIP central directory or end record hash differs from the receipt")
    eocd = bytearray(tail[-22:])
    signature, disk, cd_disk, count, total, size, start, comment_len = struct.unpack("<4s4H2IH", eocd)
    require(signature == b"PK\x05\x06" and disk == cd_disk == comment_len == 0
            and count == total == manifest["file_count"] and size == len(central)
            and start == manifest["central_range"][0], "ZIP end-of-directory fields differ")
    # zipfile accepts the isolated central directory after adjusting its end-record offset.
    struct.pack_into("<I", eocd, 16, 0)
    with zipfile.ZipFile(io.BytesIO(central + eocd)) as archive:
        for member in manifest["members"]:
            info = archive.getinfo(member["name"])
            require(info.header_offset == member["local_header_offset"]
                    and info.CRC == int(member["zip_crc32_hex"], 16)
                    and info.compress_type == zipfile.ZIP_DEFLATED
                    and info.compress_size == member["compress_size"] and info.file_size == member["size"],
                    f"central directory mismatch for {info.filename}")


def fetch_member(member, output_root):
    name = member["name"]
    target = output_root / name
    if target.exists():
        require(digest(target.read_bytes()) == member["member_sha256"], f"existing file differs: {name}")
        return
    start = member["local_header_offset"]
    data_start = member["file_data_start"]
    end = member["file_data_end"]
    wire = read_range(start, end)
    require(digest(wire) == member["local_record_sha256"], f"ZIP record hash differs: {name}")
    fields = struct.unpack("<4s5H3I2H", wire[:30])
    magic, _, flags, codec, _, _, crc, csize, size, name_len, extra_len = fields
    require(magic == b"PK\x03\x04" and flags == 0 and codec == zipfile.ZIP_DEFLATED
            and wire[30:30 + name_len].decode("ascii") == name
            and start + 30 + name_len + extra_len == data_start
            and crc == int(member["zip_crc32_hex"], 16) and csize == member["compress_size"]
            and size == member["size"], f"ZIP member header differs: {name}")
    packed = wire[data_start-start:]
    require(len(packed) == csize and digest(packed) == member["compressed_sha256"],
            f"compressed bytes differ: {name}")
    raw = zlib.decompress(packed, wbits=-15)
    require(len(raw) == size and zlib.crc32(raw) == crc and digest(raw) == member["member_sha256"],
            f"member length, CRC or SHA-256 differs: {name}")
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as tmp:
        tmp.write(raw)
        tmp_path = Path(tmp.name)
    tmp_path.replace(target)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("output_dir", type=Path, help="directory for local reference vectors")
    args = p.parse_args()
    source = Path(__file__).with_name("reference-members.json")
    manifest = json.loads(source.read_text())
    members = manifest["members"]
    require(manifest["archive"] == URL and manifest["archive_bytes"] == ARCHIVE_BYTES,
            "unexpected archive source or size")
    require(len(members) == len(NORMAL_MEMBERS) and {m["name"] for m in members} == NORMAL_MEMBERS,
            "member list differs from the nine prescribed COD/OUT pairs")
    check_index(manifest)
    for member in members:
        fetch_member(member, args.output_dir)
    print(f"Verified {len(members)} members from the official 3GPP ZIP.")


if __name__ == "__main__":
    main()
