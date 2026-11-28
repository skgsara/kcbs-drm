"""Check stock F9–F8 neighbor witnesses, optionally re-encoding the public 36-second input."""

import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile


def require(condition, message):
    if not condition:
        raise ValueError(message)


def g192_frames(raw):
    """Read complete little-endian G.192 words at the fixture's fixed 13.2 kb/s rate."""
    record = struct.Struct("<266H")
    require(len(raw) % record.size == 0, "truncated G.192 word")
    frames = []
    for sync, length, *bits in record.iter_unpack(raw):
        require(sync == 0x6B21 and length == 264, "expected a complete 264-bit G.192 word")
        require(set(bits) <= {0x7F, 0x81}, "invalid G.192 bit symbol")
        value = 0
        for symbol in bits:
            value = (value << 1) | (symbol == 0x81)
        frames.append(value.to_bytes(33, "big"))
    return frames


def eligible_modes(previous, center, successor):
    return previous == 0xF9 and center == 0xF8 and successor in (0xF8, 0xF9)


def eligible_centers(frames):
    for slot in range(1, len(frames) - 1):
        if eligible_modes(frames[slot - 1][0], frames[slot][0], frames[slot + 1][0]):
            yield slot


def check_detector_history(events, bits):
    """Check the frame-class bits against the non-narrowband transient detector."""
    require(len(events) == 3, "expected three native events")
    for index, (event, bit) in enumerate(zip(events, bits, strict=True)):
        require(event["input_frame_samples"] == 640, "input frame size changed")
        require(event["previous_extension"] == event["extension"] == -1, "extension changed")
        attack = event["attack"]
        incoming = event["incoming"]
        outgoing = event["outgoing"]
        returned = event["returned"]
        require({attack, incoming, outgoing, returned} <= {0, 1}, "nonbinary detector event")
        require(returned == bit == (incoming | attack), "transmitted transient bit differs")
        require(outgoing == attack, "outgoing hangover differs from attack")
        if index:
            require(event["previous_core"] == 3, "previous core was not HQ")
            require(incoming == events[index - 1]["outgoing"], "broken hangover history")


def verify(path, raw=None):
    evidence = json.loads(path.read_text(encoding="utf-8"))
    entries = evidence["triples"]
    frames = None
    if raw is not None:
        require(sha256(raw).hexdigest() == evidence["g192_sha256"], "full G.192 digest differs")
        frames = g192_frames(raw)
        expected_slots = [entry["center_zero_based_slot"] for entry in entries]
        require(list(eligible_centers(frames)) == expected_slots, "different qualifying slot list")

    counts = Counter()
    for row in entries:
        slot = row["center_zero_based_slot"]
        words = [bytes.fromhex(word) for word in row["full_words"]]
        require(len(words) == 3 and all(len(word) == 33 for word in words), "invalid full-word fixture")
        if frames is not None:
            require(words == frames[slot - 1:slot + 2], "fixture differs from source G.192")
        modes = [word[0] for word in words]
        require(eligible_modes(*modes), "ineligible mode triple")
        require(row["mode_hex"] == [f"{mode:02X}" for mode in modes], "incorrect mode label")
        bits = [word[1] >> 7 for word in words]
        require(row["center_b8"] == bits[1], "incorrect center b8 annotation")
        check_detector_history(row["native"], bits)
        successor = modes[2]
        if successor == 0xF9:
            require(bits == [0, 0, 0], "F9/F8/F9 rule violated")
        counts[f"F9_F8_{successor:02X}__center_{bits[1]}__successor_{bits[2]}"] += 1
    return {
        "tonal_bank_g192_sha256": evidence["g192_sha256"],
        "matched_full_stream": frames is not None,
        "checked_triples": len(entries),
        "counts": counts,
    }


def tonal_input(checkout):
    folder = checkout.resolve() / "examples/nov27/validation/hq-class"
    sys.path.insert(0, str(folder))
    from native import tonal_bank

    return folder, tonal_bank()


def encoder_command(encoder, pcm_path, output):
    return [encoder.resolve(), "-q", "-no_delay_cmp", "-max_band", "SWB", "13200", "32", pcm_path, output]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sources = parser.add_mutually_exclusive_group()
    sources.add_argument("--g192", type=Path, help="verify against this complete tonal G.192 stream")
    sources.add_argument("--encoder", type=Path, help="recreate the tonal stream with this EVS encoder")
    parser.add_argument("--checkout", type=Path, help="public checkout containing the tonal generator")
    parser.add_argument("--witnesses", type=Path, default=Path(__file__).with_name("witnesses.json"))
    args = parser.parse_args()

    raw = None
    if args.g192:
        raw = args.g192.read_bytes()
    elif args.encoder:
        if not args.checkout:
            parser.error("--encoder requires --checkout")
        _, pcm = tonal_input(args.checkout)
        witnesses = json.loads(args.witnesses.read_text(encoding="utf-8"))
        require(sha256(pcm).hexdigest() == witnesses["pcm_sha256"], "PCM differs")
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "input.s16"
            destination = Path(temporary) / "output.192"
            source.write_bytes(pcm)
            subprocess.run(encoder_command(args.encoder, source, destination), stdout=sys.stderr, check=True)
            raw = destination.read_bytes()
    print(json.dumps(verify(args.witnesses, raw), indent=2))


if __name__ == "__main__":
    main()
