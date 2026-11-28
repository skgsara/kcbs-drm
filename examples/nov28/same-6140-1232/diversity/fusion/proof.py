"""Independently check the two released combined wire rows against the original hard decisions."""
import argparse
from binascii import crc_hqx
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import struct

HERE = Path(__file__).resolve().parent
ORDINAL_HEADERS = (0x80, 0x01, 0x02, 0x43)
CASES = ((106, 109), (117, 120))


def wire_rows(raw):
    stream = BytesIO(raw)
    result = []
    while length := stream.read(4):
        if len(length) != 4 or struct.unpack("<I", length)[0] != 728:
            raise ValueError("expected a length-prefixed 728-byte MSC wire row")
        wire = stream.read(728)
        if len(wire) != 728:
            raise ValueError("truncated MSC wire row")
        result.append(wire)
    return result


def crc(data):
    return crc_hqx(data, 0xffff) ^ 0xffff


def valid(data):
    return crc(data[:-2]) == int.from_bytes(data[-2:], "big")


def accepted(wire):
    packets = [wire[start:start+182] for start in range(0, 728, 182)]
    return [p if p[0] == header and valid(p) else None for p, header in zip(packets, ORDINAL_HEADERS, strict=True)]


def data_unit(packets):
    if None in packets:
        return None
    unit = b"".join(p[1:-2] for p in packets)
    return unit if valid(unit) else None


def fingerprint(wire):
    q0 = wire[:182]
    packets = accepted(wire)
    unit = data_unit(packets)
    return dict(wire_sha256=sha256(wire).hexdigest(), good_packets=[i for i, p in enumerate(packets) if p],
                q0_computed_crc=f"{crc(q0[:-2]):04X}", q0_transmitted_crc=q0[-2:].hex().upper(),
                q0_sha256=sha256(q0).hexdigest(), du_crc=unit[-2:].hex().upper() if unit else None,
                du_sha256=sha256(unit).hexdigest() if unit else None)


def receipts(originals, recovered):
    if len(originals) != 4 or len(recovered) != 2:
        raise ValueError("the proof requires four original wire rows and two combined rows")
    results = []
    for index, (left_row, right_row) in enumerate(CASES):
        left, right = originals[2*index:2*index+2]
        combined = recovered[index]
        a, b, out = map(accepted, (left, right, combined))
        if a[0] or b[0] or data_unit(out) is None:
            raise ValueError("expected q0 missing at both stations and a valid combined DU")
        if not any(p == q and p is not None for p, q in zip(a, b)):
            raise ValueError("wire pair lacks a shared intact packet")
        for q in (1, 2, 3):
            if not (a[q] or b[q]) or any(p != out[q] for p in (a[q], b[q]) if p):
                raise ValueError("another quarter differs from its original independently received bytes")
        results.append(dict(edogawa_row=left_row, yokohama_row=right_row, edogawa=fingerprint(left),
                            yokohama=fingerprint(right), combined=fingerprint(combined)))
    return results


def verify(directory, msc_paths):
    originals = wire_rows((directory / "original-witnesses.msc.bin").read_bytes())
    recovered = wire_rows((directory / "recovered.msc.bin").read_bytes())
    result = receipts(originals, recovered)
    if result != json.loads((directory / "proof.json").read_bytes()):
        raise ValueError("wire bytes differ from the published proof")
    if msc_paths:
        left, right = [wire_rows(path.read_bytes()) for path in msc_paths]
        from_stations = [row for a, b in CASES for row in (left[a], right[b])]
        if originals != from_stations:
            raise ValueError("original witnesses differ from station dumps at the documented indices")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dir", type=Path, default=HERE)
    parser.add_argument("--msc", nargs=2, type=Path, metavar=("EDOGAWA", "YOKOHAMA"),
                        help="also check all four original excerpts against the full native dumps")
    args = parser.parse_args()
    try:
        print(json.dumps(verify(args.dir, args.msc), indent=2))
    except (OSError, ValueError) as error:
        parser.exit(1, f"{error}\n")
