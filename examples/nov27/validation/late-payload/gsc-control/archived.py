"""Replay the two archived, text-supported prefixes with a cold reference decoder."""
import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import struct
import subprocess
import tempfile

from bounded import build


def verify(native, directory):
    fixture = Path(__file__).with_name("archived-prefixes.json")
    receipt = json.loads(fixture.read_text())
    for row in receipt["words"]:
        prefix = bytes.fromhex(row["prefix_hex"])
        if len(prefix) != 16 or sha256(prefix).hexdigest() != row["prefix_sha256"]:
            raise ValueError("archived prefix digest mismatch")
        known = [0x81 if byte & (1 << bit) else 0x7f
                 for byte in prefix for bit in range(7, -1, -1)]
        # Only the bounded walk's P and N events are scored. Give the ordinary
        # file reader a nominal-length G.192 record in both padding regimes.
        for filler in (0x7f, 0x81):
            stream = directory / "word.192"
            stream.write_bytes(struct.pack("<266H", 0x6b21, 264, *known, *([filler] * 136)))
            process = subprocess.run([native, "-q", "-no_delay_cmp", "16", stream, os.devnull],
                                     check=True, capture_output=True, text=True)
            events = [line for line in process.stderr.splitlines() if line.startswith(("P,", "N,"))]
            if events != row["bounded_events"]:
                raise ValueError(f"slot {row['slot']} disagrees with the recorded bounded events")
            predicts = "N,0,142544,139,10,230" in events
            if ("00" if predicts else None) != row["predict_p27_low_pair"]:
                raise ValueError(f"slot {row['slot']} disagrees with the recorded decision")
    print(f"Verified cold prefix decisions for {len(receipt['words'])} archived slots")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="original TS 26.443 c-code directory")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as tmp:
        directory = Path(tmp)
        verify(build(directory, args.source.resolve()), directory)
