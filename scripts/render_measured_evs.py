"""Replay measured November DRM frames into an uninterrupted 16 kHz EVS decode.

The results directory supplies packets.npz and keys.npz. A manifest entry has three
du_sha256 entries in phase order and a masks mapping from one-based positions
to eleven XOR bytes in hex. Each digest covers a complete 716-byte received
data unit including its trailing CRC. A null entry leaves that phase ineligible
for inference. An inferred first-position mask can supply a slot lacking a
text-supported key. Unavailable slots are G.192 erasures.
"""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import tempfile
import wave

import numpy as np

from build_evs_gcc_independent import linux_command
from render_continuous import KEYED, MODE_POSITIONS, PACKET_STARTS
from speech_presence_test import write_g192
from tail_fill_audit import crc

ROOT = Path(__file__).resolve().parents[1]
PACKET_BYTES = 179
SLOTS_PER_GROUP = 60
SAMPLES_PER_FRAME = 320
INFERRED_FIRST = 5


def hex_bytes(value, size, label):
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a hex string")
    raw = bytes.fromhex(value)
    if len(raw) != size:
        raise ValueError(f"{label} must contain {size} bytes")
    return raw


def measured_groups(document):
    groups = document["groups"]
    if not isinstance(groups, dict):
        raise ValueError("manifest groups must be a counter-to-group mapping")
    parsed = {}
    for key, group in groups.items():
        counter = int(key)
        if str(counter) != key or not 0 <= counter <= 0xffffffff:
            raise ValueError(f"invalid manifest counter {key}")
        hashes = group["du_sha256"]
        if not isinstance(hashes, list) or len(hashes) != 3:
            raise ValueError(f"group {counter} requires three phase digests")
        hashes = [hex_bytes(value, 32, f"group {counter} digest") if value is not None else None
                  for value in hashes]
        if not any(hashes):
            raise ValueError(f"group {counter} requires at least one phase digest")
        masks = group["masks"]
        if not isinstance(masks, dict) or not masks or masks.keys() - {"1", "2", "3", "4"}:
            raise ValueError(f"group {counter} masks must name one or more of positions 1 through 4")
        parsed[counter] = (hashes, {int(p): np.frombuffer(hex_bytes(value, len(KEYED), f"position {p} mask"), "u1")
                                    for p, value in masks.items()})
    return parsed


def match_group(counter, hashes, received):
    for phase, expected_hash in enumerate(hashes):
        if expected_hash is None:
            continue
        record = received.get(3 * counter + phase)
        if record is None or not record[1].all():
            return f"phase {phase} incomplete"
        unit = record[0].tobytes()
        if crc(unit[:-2]) != int.from_bytes(unit[-2:], "big"):
            return f"phase {phase} CRC mismatch"
        if unit[1] >> 4 != phase or (phase == 0 and int.from_bytes(unit[664:668], "big") != counter):
            return f"phase {phase} header mismatch"
        if sha256(unit).digest() != expected_hash:
            return f"phase {phase} SHA-256 mismatch"
    return None


def collect(directory, groups):
    with np.load(directory / "keys.npz") as data:
        counters, keys, flags = data["counters"], data["ks"], data["crc_supported"]
    if (counters.ndim != 1 or counters.dtype.kind not in "ui" or keys.dtype != np.uint8
            or flags.dtype != np.bool_ or keys.shape != flags.shape or keys.shape != (len(counters), 16)
            or len(np.unique(counters)) != len(counters)):
        raise ValueError("expected unique counters and 16 mask bytes with CRC support in keys.npz")
    established = {int(c): k[:len(KEYED)] for c, k, f in zip(counters, keys, flags, strict=True)
                   if f[:len(KEYED)].all()}

    with np.load(directory / "packets.npz") as data:
        ticks, bodies, present = data["ticks"], data["packets"], data["packet_ok"]
    if (ticks.ndim != 1 or not len(ticks) or ticks.dtype.kind not in "ui"
            or np.any(ticks[1:] <= ticks[:-1]) or int(ticks[0]) < 0 or int(ticks[-1]) // 3 > 0xffffffff
            or bodies.dtype != np.uint8 or bodies.shape != (len(ticks), 4, PACKET_BYTES)
            or present.dtype != np.bool_ or present.shape != bodies.shape[:2]):
        raise ValueError("expected increasing ticks, four 179-byte packet bodies and CRC flags per phase")
    received = {int(t): (packets.ravel(), flags) for t, packets, flags in zip(ticks, bodies, present, strict=True)}
    first, last = int(ticks[0]) // 3, int(ticks[-1]) // 3
    applied, rejected = {}, {}
    for c, (hashes, masks) in groups.items():
        if first <= c <= last:
            reason = match_group(c, hashes, received)
            if reason is None:
                applied[c] = masks
            else:
                rejected[c] = reason

    kinds = np.zeros((last - first + 1) * SLOTS_PER_GROUP, dtype=np.uint8)
    words = np.zeros((len(kinds), 33), dtype=np.uint8)
    for tick, (unit, flags) in received.items():
        c, phase = divmod(tick, 3)
        masks = applied.get(c, {})
        if masks and groups[c][0][phase] is None:
            masks = {}
        for slot, (mode, start) in enumerate(zip(MODE_POSITIONS, PACKET_STARTS, strict=True)):
            position = slot % 4 + 1
            known_first = position == 1 and c in established
            mask = established[c] if known_first else masks.get(position)
            if mask is None or not flags[mode // PACKET_BYTES]:
                continue
            if not flags[start // PACKET_BYTES:(start + 31) // PACKET_BYTES + 1].all():
                continue
            index = SLOTS_PER_GROUP * (c - first) + 20 * phase + slot
            words[index, 0] = unit[mode]
            words[index, 1:] = unit[start:start + 32]
            words[index, 1 + KEYED] ^= mask
            kinds[index] = INFERRED_FIRST if position == 1 and not known_first else position
    report = {"first_counter": first, "last_counter": last,
              "first_tick": int(ticks[0]), "last_tick": int(ticks[-1]),
              "applied_group_positions": {c: sorted(pos) for c, pos in applied.items()},
              "skipped_in_range_groups": rejected,
              "manifest_groups_outside_capture": len(groups) - len(applied) - len(rejected)}
    return words, kinds, report


def coverage(kinds):
    count = np.bincount(kinds, minlength=INFERRED_FIRST + 1)
    positions = {str(p): int(count[p]) for p in range(1, 5)}
    positions["1"] += int(count[INFERRED_FIRST])
    return {"total_slots": len(kinds), "established": int(count[1]), "inferred": int(count[2:].sum()),
            "erased": int(count[0]), "frames_by_position": positions,
            "inferred_first_position": int(count[INFERRED_FIRST])}


def write_wave(path, pcm):
    with wave.open(str(path), "wb") as out:
        out.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        out.writeframes(pcm)


def render(directory, manifest, out, decoder, excerpt=None, received_span=False):
    content = manifest.read_bytes()
    words, kinds, report = collect(directory, measured_groups(json.loads(content)))
    first, last = report["first_counter"], report["last_counter"]
    if excerpt and not first <= excerpt[0] <= excerpt[1] <= last:
        raise ValueError(f"excerpt counter range must be inside {first}..{last}")
    first_slot = 0
    if received_span:
        slots_per_phase = len(MODE_POSITIONS)
        first_slot = (report["first_tick"] % 3) * slots_per_phase
        stop = first_slot + (report["last_tick"] - report["first_tick"] + 1) * slots_per_phase
        words, kinds = words[first_slot:stop], kinds[first_slot:stop]
    report.update(coverage(kinds), manifest_sha256=sha256(content).hexdigest(), sample_rate_hz=16000)
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=out) as folder:
        stage = Path(folder)
        stream = stage / "programme.192"
        write_g192(stream, words, kinds != 0)
        raw = stage / "decoded.pcm"
        subprocess.run(linux_command(decoder, "-q", "-no_delay_cmp", "16", stream, raw),
                       check=True, stdout=subprocess.DEVNULL)
        pcm = raw.read_bytes()
        if len(pcm) != len(kinds) * SAMPLES_PER_FRAME * 2:
            raise ValueError("EVS decoder did not produce 320 signed 16-bit samples per slot")
        write_wave(stage / "programme.wav", pcm)
        report.update(bitstream_sha256=sha256(stream.read_bytes()).hexdigest(),
                      pcm_sha256=sha256(pcm).hexdigest())
        outputs = ["programme.192", "programme.wav"]
        if excerpt:
            lo = max(0, SLOTS_PER_GROUP * (excerpt[0] - first) - first_slot)
            hi = min(len(kinds), SLOTS_PER_GROUP * (excerpt[1] + 1 - first) - first_slot)
            write_wave(stage / "excerpt.wav", pcm[2 * SAMPLES_PER_FRAME * lo:2 * SAMPLES_PER_FRAME * hi])
            report["excerpt"] = {"first_counter": excerpt[0], "last_counter": excerpt[1], **coverage(kinds[lo:hi])}
            outputs.append("excerpt.wav")
        (stage / "coverage.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        for name in [*outputs, "coverage.json"]:
            (stage / name).replace(out / name)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results", type=Path)
    parser.add_argument("--masks", type=Path, default=ROOT / "dumps/nov19-measured-masks.json")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--decoder", type=Path, default=ROOT / "work/evs_gcc_independent/EVS_dec",
                        help="EVS reference decoder executable")
    parser.add_argument("--excerpt", type=int, nargs=2, metavar=("FIRST", "LAST"),
                        help="also export these inclusive counters from the continuously decoded PCM")
    parser.add_argument("--received-span", action="store_true",
                        help="start and end at the first and last recorded phases, including gaps between them")
    args = parser.parse_args()
    try:
        report = render(args.results, args.masks, args.out, args.decoder, args.excerpt, args.received_span)
    except (ValueError, KeyError, OSError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"{parser.prog}: {error}\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
