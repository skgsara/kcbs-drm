"""Replay four fixed known-word controls against the receiver supplement's TCX spectral checker."""
import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
FIRST = 43865854
TARGET = 43865914
RECORD_BYTES = 4 + 15 * 33
SLOTS = (TARGET - FIRST + 1) * 60
TARGET_START = SLOTS - 60
FIXTURE_SHA256 = "d65fadf3e7a9ffd69cc33033d46b06231100759a2a7f3e18cb9a140f82ff9fb2"
ORIGINAL_SHA256 = "195b1f058143763a7478c0723d67747ad827cf94ba4d573dd333d72d7d3bb10e"
GOOD = struct.pack("<HH", 0x6b21, 264)
ERASED = struct.pack("<HH", 0x6b20, 0)
BYTE_SYMBOLS = tuple(struct.pack("<8H", *(0x81 if b & (128 >> i) else 0x7f for i in range(8)))
                     for b in range(256))
TRIALS = {"original": None, "p24_lsb": 24, "p27_lsb": 27, "p30_lsb": 30}


def read_fixture():
    packed = (HERE / "first-position.bin").read_bytes()
    if sha256(packed).hexdigest() != FIXTURE_SHA256 or len(packed) != 47 * RECORD_BYTES:
        raise ValueError("packed first-position fixture failed its length or digest check")
    groups = {}
    for i in range(0, len(packed), RECORD_BYTES):
        counter = int.from_bytes(packed[i:i + 4], "big")
        if counter in groups or not FIRST <= counter <= TARGET:
            raise ValueError(f"unexpected fixture counter {counter}")
        body = packed[i + 4:i + RECORD_BYTES]
        groups[counter] = [body[k:k + 33] for k in range(0, len(body), 33)]
    if TARGET not in groups:
        raise ValueError("target missing")
    return groups


def make_stream(groups, offset):
    stream = bytearray()
    for counter in range(FIRST, TARGET + 1):
        if counter not in groups:
            stream.extend(ERASED * 60)
            continue
        for original in groups[counter]:
            word = bytearray(original)
            if counter == TARGET and offset is not None:
                word[1 + offset] ^= 1
            stream.extend(GOOD)
            for b in word:
                stream.extend(BYTE_SYMBOLS[b])
            stream.extend(ERASED * 3)
    return bytes(stream)


def target_events(lines):
    target = {}
    for line in lines:
        if not line.startswith(b"T,"):
            continue
        fields = list(map(int, line[2:].split(b",")))
        if len(fields) != 11:
            raise ValueError("unrecognized T record from spectral checker")
        frame, begin, budget, nt, lastnz, mapping, overflow, differences, first, last, early = fields
        if frame < TARGET_START:
            continue
        relative = frame - TARGET_START
        if relative >= 60 or relative % 4 or relative // 4 in target:
            raise ValueError(f"unexpected or duplicate target T record at slot {frame}")
        if begin < 0 or budget <= 0 or begin + budget > 264:
            raise ValueError("spectral bit interval outside word")
        target[relative // 4] = (begin, begin + budget, differences)
    return target


def evaluate(decoder, directory, groups):
    results = {}
    baseline_pcm = None
    for name, offset in TRIALS.items():
        stream = make_stream(groups, offset)
        if offset is None and sha256(stream).hexdigest() != ORIGINAL_SHA256:
            raise ValueError("original G.192 differs from the frozen chronological slice")
        src = directory / "input.192"
        pcm = directory / "output.pcm"
        src.write_bytes(stream)
        env = {k: v for k, v in os.environ.items() if k != "KCBS_CONTEXT"}
        run = subprocess.run([decoder, "-q", "-no_delay_cmp", "16", src, pcm],
                             stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, env=env, check=True)
        target = target_events(run.stderr.splitlines())
        data = pcm.read_bytes()
        if len(data) != SLOTS * 320 * 2:
            raise ValueError(f"unexpected 16 kHz PCM length for {name}")
        p1_pcm = [data[s * 640:(s + 1) * 640] for s in range(TARGET_START, SLOTS, 4)]
        if offset is None:
            baseline_pcm = p1_pcm
        mismatches = [target[i][2] if i in target else None for i in range(15)]
        results[name] = dict(
            target_t_records=len(target), exact_spectral_slices=mismatches.count(0),
            differences_by_cycle=mismatches,
            slices_covering_p30_lsb=sum(start <= 255 < end for start, end, diff in target.values()),
            target_pcm_slots_changed=sum(a != b for a, b in zip(baseline_pcm, p1_pcm)),
        )
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--decoder", type=Path, required=True, help="EVS decoder with the handoff T-record observer")
    args = parser.parse_args()
    decoder = args.decoder.resolve()
    try:
        groups = read_fixture()
        expected = json.loads((HERE / "expected.json").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as temp:
            trials = evaluate(decoder, Path(temp), groups)
        match = trials == expected["trials"]
        report = dict(matches_expected=match, decoder_sha256=sha256(decoder.read_bytes()).hexdigest(),
                      original_g192_sha256=ORIGINAL_SHA256, packed_fixture_sha256=FIXTURE_SHA256, trials=trials)
        print(json.dumps(report, indent=2))
        return 0 if match else 1
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print(str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
