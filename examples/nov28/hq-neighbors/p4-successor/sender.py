"""Check the EVS HQ spectral-peak tracking rule on eight seconds of synthetic audio.

Run with Python, NumPy, GCC, and an official Nov 4, 2021 TS 26.443 c-code tree:
    python sender.py --source /path/to/c-code

The input is the first eight seconds of a deterministic tone-to-noise stimulus.
Two native builds encode it from reset. Frame and high-band numbers start at zero.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile

import numpy as np


RATE = 32000
SECONDS = 8
SEED = 217911 + 7919
FRAME = struct.Struct("<266H")
PCM_HASH = "16d5f66fc5baaa7001f4216dd7b1f77fcf13d54f09eddf54f5a3a9a9e243f294"
G192_HASH = "6db4c21f67d50acee1b928de3aee06a5d9f129ac5755ddd35a8772a2ba265dd2"
HQ_SOURCE_HASH = "d52cd45cda59c41e9ec0f14e6d3cb5a2dfc4b8024589d9bae6bee0fe7266bafa"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def normalize(x):
    return x / max(1e-10, np.mean(x * x) ** 0.5)


def write_stimulus(path):
    rng = np.random.default_rng(SEED)
    t = np.arange(RATE) / RATE
    hz = np.fft.rfftfreq(RATE, 1 / RATE)
    k = np.arange(1, 30)
    with path.open("wb") as output:
        for _ in range(SECONDS):
            spectrum = np.fft.rfft(rng.normal(size=RATE))
            lo = rng.uniform(200, 1300)
            hi = rng.uniform(5500, 12000)
            lows = normalize(np.fft.irfft(spectrum / (1 + (hz / lo) ** 4)))
            middle = np.exp(-0.5 * ((hz - rng.uniform(1200, 3700)) / 900) ** 2)
            middle += 0.15 * np.exp(-0.5 * ((hz - 5000) / 1000) ** 2)
            middles = normalize(np.fft.irfft(spectrum * middle))
            upper = np.exp(-0.5 * ((hz - hi) / rng.uniform(700, 1900)) ** 2)
            highs = normalize(np.fft.irfft(spectrum * upper))
            phase = rng.uniform(0, 2 * np.pi)
            f0 = rng.uniform(85, 290)
            glide = rng.uniform(-0.13, 0.13)
            pitch = f0 * (t + 0.5 * glide * t * t)
            pitch += rng.uniform(0.01, 0.09) * np.sin(2 * np.pi * 4 * t + phase)
            peaks = rng.uniform([350, 1100, 2100], [900, 2000, 3100])
            formants = np.exp(-((k[:, None] * f0 - peaks) / 210) ** 2)
            weights = (1 + 2.9 * np.sum(formants, axis=1)) / k ** 0.8
            harmonics = np.sin(2 * np.pi * k[:, None] * pitch + phase)
            voiced = normalize(np.sum(weights[:, None] * harmonics, axis=0))
            # The original generator drew two unused envelope parameters here.
            rng.uniform(1.8, 6.5)
            rng.uniform(1, 3)
            high = rng.uniform(0.25, 1.1) * highs
            mix = (0.5 + 0.5 * np.sin(2 * np.pi * rng.uniform(0.6, 3.0) * t + phase)) ** 2
            tone = 0.8 * voiced + 0.22 * np.sin(2 * np.pi * 7000 * t)
            signal = tone * (1 - mix) + (middles + high + 0.5 * lows) * mix
            samples = np.rint(np.clip(rng.uniform(1200, 6400) * signal, -30000, 30000))
            output.write(samples.astype("<i2").tobytes())
    require(digest(path.read_bytes()) == PCM_HASH, "Generated PCM differs from the archived prefix")


def instrument(original, patched):
    source = original.read_text(encoding="latin1")
    require(digest(source.encode("latin1")) == HQ_SOURCE_HASH, "Unexpected hq_lr_enc.c revision")
    emit = "push_indice( st, IND_HQ2_SPT_SHORTEN, spt_shorten_flag[j], 1 );"
    gate = "if( p2a_flags[bands-SPT_SHORTEN_SBNUM+k] == 0 || npulses[bands-SPT_SHORTEN_SBNUM+k] == 0 )"
    require(source.count(emit) == source.count(gate) == 1, "Trace anchors differ")
    trace_emit = r'fprintf(stderr,"SPT,%ld,S,%d,%d,%d\n",frame,j,spt_shorten_flag[j],st->prev_SWB_peak_pos[kpos]);'
    trace_gate = (r'fprintf(stderr,"SPT,%ld,P,%d,%d,%d,%d\n",frame,k,p2a_flags[bands-SPT_SHORTEN_SBNUM+k],'
                  r'npulses[bands-SPT_SHORTEN_SBNUM+k],prev_SWB_peak_pos_tmp[k]);')
    source = source.replace(emit, emit + "\n            " + trace_emit)
    source = source.replace(gate, trace_gate + "\n                    " + gate)
    patched.write_text("extern long frame;\n" + source, encoding="latin1")


def gcc(temp, args):
    # A GCC response file also supports source directories containing spaces.
    response = temp / "args.rsp"
    response.write_text("\n".join('"' + str(arg).replace("\\", "/").replace('"', '\\"') + '"'
                                  for arg in args), encoding="utf-8")
    subprocess.run(["gcc", "@args.rsp"], cwd=temp, check=True)


def build(source, temp):
    includes = ["-I" + str(source / d) for d in ("lib_enc", "lib_dec", "lib_com")]
    flags = ["-O0", "-std=gnu99", "-fno-strict-aliasing", *includes]
    files = sorted(p for d in ("lib_com", "lib_enc") for p in (source / d).glob("*.c"))
    objects = [p.with_suffix(".o").name for p in files]
    require(len(objects) == len(set(objects)), "Source files have duplicate object names")
    original = source / "lib_enc" / "hq_lr_enc.c"
    patched = temp / original.name
    instrument(original, patched)
    suffix = ".exe" if os.name == "nt" else ""
    stock = temp / ("EVS_stock" + suffix)
    traced = temp / ("EVS_traced" + suffix)
    gcc(temp, [*flags, "-c", *files])
    gcc(temp, [*objects, "-lm", "-o", stock])
    gcc(temp, [*flags, "-c", patched])
    gcc(temp, [*objects, "-lm", "-o", traced])
    return stock, traced


def encode(binary, pcm, output):
    command = [binary, "-q", "-no_delay_cmp", "-max_band", "SWB", "13200", "32", pcm, output]
    return subprocess.run(command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE).stderr


def measure(encoded, trace):
    fields = {}
    for record in trace.splitlines():
        if record.startswith(b"SPT,"):
            _, slot, operation, band, *values = record.split(b",")
            key = int(slot), operation, int(band)
            require(key not in fields, "Duplicate native trace row")
            fields[key] = tuple(map(int, values))
    rows = list(FRAME.iter_unpack(encoded))
    require(len(rows) == SECONDS * 50, "Unexpected G.192 length")
    for frame in rows:
        require(frame[:2] == (0x6B21, 264) and set(frame[2:]) <= {127, 129}, "Invalid G.192 word")
    modes = [sum((v == 129) << (7 - i) for i, v in enumerate(frame[2:10])) for frame in rows]
    zeros = {"prior_p2a_0": 0, "prior_p2a_1": 0, "prior_transient": 0}
    successes = []
    pairs = 0
    for slot in range(1, len(rows)):
        if modes[slot - 1] != 0xF8 or modes[slot] != 0xF8:
            continue
        pairs += 1
        for band in range(4):
            current = fields.get((slot, b"S", band))
            if current is None:
                continue
            spt, memory = current
            require(rows[slot][10] == 127 and spt in (0, 1), "Invalid current normal HQ flag")
            previous = fields.get((slot - 1, b"P", band))
            if previous is None:
                require(rows[slot - 1][10] == 129 and spt == memory == 0, "Unexpected predecessor")
                zeros["prior_transient"] += 1
                continue
            p2a, pulses, peak = previous
            require(rows[slot - 1][10] == 127 and p2a in (0, 1), "Invalid prior normal HQ flag")
            expected_memory = peak if p2a and pulses else 0
            require(memory == expected_memory, "Previous saved peak differs from current memory")
            if spt == 1:
                require(p2a == 1 and pulses > 0 and memory > 0, "SPT implication failed")
                successes.append([slot - 1, slot, band, pulses, memory])
            else:
                zeros[f"prior_p2a_{p2a}"] += 1
    require(pairs == 14 and len(successes) == 4, "Unexpected positive count or F8-pair denominator")
    require(zeros == {"prior_p2a_0": 5, "prior_p2a_1": 2, "prior_transient": 1},
            "Unexpected native negative-control counts")
    return {"frames": len(rows), "consecutive_f8_pairs": pairs,
            "spt_flags": len(successes) + sum(zeros.values()), "spt_one": len(successes),
            "spt_zero": zeros, "positive_columns": ["prior_slot", "slot", "band", "prior_pulses", "prior_peak"],
            "positive_rows": successes}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path, help="TS 26.443 c-code directory")
    args = parser.parse_args()
    require(sys.byteorder == "little", "This pinned stock G.192 comparison uses a little-endian host")
    with tempfile.TemporaryDirectory() as tmp:
        temp = Path(tmp).resolve()
        pcm = temp / "stimulus.s16"
        write_stimulus(pcm)
        stock, traced = build(args.source.resolve(), temp)
        original = temp / "stock.192"
        observed = temp / "trace.192"
        encode(stock, pcm, original)
        trace = encode(traced, pcm, observed)
        encoded = original.read_bytes()
        require(digest(encoded) == G192_HASH, "Stock G.192 differs from the archived prefix")
        require(observed.read_bytes() == encoded, "Logging changed the encoded words")
        report = measure(encoded, trace)
        report.update(seed=SEED, pcm_sha256=PCM_HASH, g192_sha256=G192_HASH, traced_equals_stock=True)
    print(json.dumps(report))


if __name__ == "__main__":
    main()
