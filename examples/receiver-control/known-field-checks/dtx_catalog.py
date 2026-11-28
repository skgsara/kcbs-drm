"""Fetch the nine prescribed SWB DTX test streams by range from the official 3GPP ZIP."""
import argparse
from hashlib import sha256
from io import BytesIO
from pathlib import Path
import struct
from tempfile import NamedTemporaryFile
from urllib.request import Request, urlopen
from zipfile import ZipFile, ZIP_DEFLATED
import zlib


URL = ("https://www.3gpp.org/ftp/Specs/archive/26_series/26.444/test_sequences/"
       "26444_g50-TestSeq_Float_26443.zip")
ARCHIVE_BYTES = 2713276244
CENTRAL_START, CENTRAL_SIZE, CENTRAL_ENTRIES = 2711883212, 1393010, 11009
CENTRAL_SHA256 = "5e4b5d8e6f5b87f0df43a185aa874c72dd90b3cf29ac50dae0e17f4df1ae45f4"

# Each entry gives the uncompressed size and ZIP CRC-32 in clean, f06, b10 order.
SOURCES = {
    "c": (1302672, (0x94D0DCC9, 0xA22C588A, 0x02575B44)),
    "n1": (243664, (0x2FE722F3, 0x6CE1D71E, 0xA6F74926)),
    "n2": (335200, (0x5339AADB, 0x6F92197E, 0xF4A56B1F)),
}
MEMBERS = {
    f"testvec/testv/bitstreams/swb/stv32{source}_dtx_13200_32kHz{condition}.COD": (size, crc)
    for source, (size, crcs) in SOURCES.items()
    for condition, crc in zip(("", ".f06", ".b10"), crcs, strict=True)
}


def expected_names():
    """The full archive paths, grouped by input and then clean, f06 and b10."""
    return tuple(MEMBERS)


def validate_member(name, raw):
    if name not in MEMBERS or MEMBERS[name] != (len(raw), zlib.crc32(raw)):
        raise ValueError(f"unexpected member name, size or ZIP CRC-32: {name}")


def read_range(start, size):
    end = start + size - 1
    if not 0 <= start <= end < ARCHIVE_BYTES or size > CENTRAL_SIZE:
        raise ValueError("unexpected range for the official archive")
    request = Request(URL, headers={"Range": f"bytes={start}-{end}", "User-Agent": "EVS-vector-replay/1.0"})
    with urlopen(request, timeout=60) as response:
        if response.status != 206 or response.headers.get("Content-Range") != f"bytes {start}-{end}/{ARCHIVE_BYTES}":
            raise ValueError("server returned an unexpected ZIP range")
        raw = response.read(size + 1)
    if len(raw) != size:
        raise ValueError("incomplete ZIP range")
    return raw


def catalog(central):
    if len(central) != CENTRAL_SIZE or sha256(central).hexdigest() != CENTRAL_SHA256:
        raise ValueError("official ZIP directory differs from its published digest")
    # Let zipfile parse just the verified directory; the local header offsets in
    # its entries still refer to the complete archive. No payload is read here.
    end = struct.pack("<4s4H2IH", b"PK\x05\x06", 0, 0, CENTRAL_ENTRIES, CENTRAL_ENTRIES, CENTRAL_SIZE, 0, 0)
    with ZipFile(BytesIO(central + end)) as directory:
        rows = [i for i in directory.infolist() if i.filename in MEMBERS]
    if len(rows) != len(MEMBERS) or {i.filename for i in rows} != set(MEMBERS):
        raise ValueError("prescribed member set differs")
    for i in rows:
        if (i.flag_bits or i.compress_type != ZIP_DEFLATED or
                (i.file_size, i.CRC) != MEMBERS[i.filename]):
            raise ValueError(f"unexpected directory metadata: {i.filename}")
    return {i.filename: i for i in rows}


def unpack_member(info):
    header = read_range(info.header_offset, 30)
    magic, _, flags, compression, _, _, crc, packed_size, size, name_len, extra_len = struct.unpack("<4s5H3I2H", header)
    if (magic != b"PK\x03\x04" or flags != 0 or compression != ZIP_DEFLATED or
            (crc, packed_size, size) != (info.CRC, info.compress_size, info.file_size) or
            name_len != len(info.filename)):
        raise ValueError(f"local ZIP header differs: {info.filename}")
    data = read_range(info.header_offset + 30, name_len + extra_len + packed_size)
    if data[:name_len] != info.filename.encode("ascii"):
        raise ValueError(f"local ZIP member name differs: {info.filename}")
    inflater = zlib.decompressobj(-15)
    raw = inflater.decompress(data[name_len + extra_len:], size + 1)
    if not inflater.eof or inflater.unused_data or inflater.unconsumed_tail:
        raise ValueError(f"incomplete or excess DEFLATE data: {info.filename}")
    validate_member(info.filename, raw)
    return raw


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output_dir", type=Path, help="local directory for the testvec/ tree")
    args = parser.parse_args()
    entries = catalog(read_range(CENTRAL_START, CENTRAL_SIZE))
    for name in expected_names():
        path = args.output_dir / name
        if path.exists():
            raw = path.read_bytes()
            validate_member(name, raw)
        else:
            raw = unpack_member(entries[name])
            path.parent.mkdir(parents=True, exist_ok=True)
            with NamedTemporaryFile(dir=path.parent, delete=False) as target:
                target.write(raw)
                staged = Path(target.name)
            staged.replace(path)
        print(sha256(raw).hexdigest(), name)


if __name__ == "__main__":
    main()
