"""Score the 40-group EF0201 synthetic packet-loss fixture against its sender."""
import argparse
import gzip
from hashlib import sha256
import io
import json
from pathlib import Path
import struct
import wave
import zlib


FIRST = 0x01020304
GROUPS = 40
SLOTS = GROUPS * 60
CLASSES = ("full", "partial", "absent")
OUTCOMES = ("exact_supplied", "correct_erasure", "wrong_word", "extra_erasure", "false_supply")


def digest(raw):
    return sha256(raw).hexdigest()


def read_bytes(path):
    raw = path.read_bytes()
    return gzip.decompress(raw) if raw.startswith(b"\x1f\x8b") else raw


def read_g192(raw):
    """Return one packed word or None for every slot, including BFI/NO_DATA."""
    at, words = 0, []
    while at < len(raw):
        if len(raw) - at < 4:
            raise ValueError(f"truncated G.192 header at slot {len(words)}")
        sync, size = struct.unpack_from("<HH", raw, at)
        at += 4
        if sync not in (0x6b20, 0x6b21) or size not in (0, 264) or at + size * 2 > len(raw):
            raise ValueError(f"invalid G.192 header or extent at slot {len(words)}")
        word = None
        if sync == 0x6b21 and size:
            symbols = struct.unpack_from("<264H", raw, at)
            if any(x not in (0x7f, 0x81) for x in symbols):
                raise ValueError(f"invalid supplied bit in slot {len(words)}")
            packed = bytearray(33)
            for i, x in enumerate(symbols):
                if x == 0x81:
                    packed[i // 8] |= 128 >> (i % 8)
            word = bytes(packed)
        words.append(word)
        at += size * 2
    if len(words) != SLOTS:
        raise ValueError(f"expected {SLOTS} consecutive slots from {FIRST}, got {len(words)}")
    return words


def coordinate(slot):
    group, offset = divmod(slot, 60)
    phase, offset = divmod(offset, 20)
    cycle, role = divmod(offset, 4)
    return dict(slot=slot, counter=FIRST + group, phase=phase, cycle=cycle, position=role + 1)


def planned_flags(group, phase):
    damaged = group - 8
    return [not (0 <= damaged < 12 and phase == damaged // 4 and q == damaged % 4)
            for q in range(4)]


def receipt(slot, overlay):
    c = coordinate(slot)
    group = c["counter"] - FIRST
    flags = overlay.get(3 * c["counter"] + c["phase"], planned_flags(group, c["phase"]))
    cycle, pos = c["cycle"], c["position"]
    start = 7 + 131 * cycle
    if pos == 1:
        offsets = [2 + cycle, *range(start, start + 32)]
    else:
        start += 32 + 33 * (pos - 2)
        offsets = range(start, start + 33)
    return sum(flags[offset // 179] for offset in offsets)


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key {key}")
        result[key] = value
    return result


def read_overlay(path):
    data = json.loads(path.read_text(), object_pairs_hook=unique_object)
    if not isinstance(data, dict):
        raise ValueError("transport mask must map decimal ticks to four boolean packet flags")
    overlay = {}
    for key, flags in data.items():
        tick = int(key)
        group, phase = divmod(tick - 3 * FIRST, 3)
        if str(tick) != key or not 0 <= group < GROUPS:
            raise ValueError(f"invalid transport tick {key}")
        if not isinstance(flags, list) or len(flags) != 4 or any(type(v) is not bool for v in flags):
            raise ValueError(f"invalid packet flags for {tick}")
        if any(got and not planned for got, planned in zip(flags, planned_flags(group, phase))):
            raise ValueError(f"transport mask credits scheduled bad packet at {tick}")
        overlay[tick] = flags
    return overlay


def word_digest(words):
    # A fixed marker (00 erasure, 01 followed by 33 bytes for supplied words)
    # binds every slot, even when adjacent words have identical content.
    return digest(b"".join(b"\0" if w is None else b"\1" + w for w in words))


def compare(actual, sender, coverage):
    expected = [word if received == 33 else None for word, received in zip(sender, coverage, strict=True)]
    positions = {str(i): dict.fromkeys(CLASSES + OUTCOMES, 0) for i in range(1, 5)}
    groups = {str(FIRST + i): dict.fromkeys(CLASSES + OUTCOMES, 0) for i in range(GROUPS)}
    mismatches, losses = [], []
    for i, (source, observed, wanted, received) in enumerate(zip(sender, actual, expected, coverage, strict=True)):
        coord = coordinate(i)
        counts = positions[str(coord["position"])]
        group = groups[str(coord["counter"])]
        cls = "full" if received == 33 else ("absent" if received == 0 else "partial")
        counts[cls] += 1
        group[cls] += 1
        if wanted is None:
            losses.append(dict(**coord, receipt=cls, received_octets=received))
            result = "correct_erasure" if observed is None else "false_supply"
        elif observed is None:
            result = "extra_erasure"
        else:
            result = "exact_supplied" if observed == wanted else "wrong_word"
        counts[result] += 1
        group[result] += 1
        if result in ("wrong_word", "extra_erasure", "false_supply"):
            diff = None if observed is None else sum((a ^ b).bit_count() for a, b in zip(observed, source))
            mismatches.append(dict(**coord, outcome=result, received_octets=received,
                                   received_word_bits_differing_from_sender=diff))
    totals = {key: sum(row[key] for row in positions.values()) for key in CLASSES + OUTCOMES}
    for pos, row in positions.items():
        role = int(pos) - 1
        row.update(expected_sha256=word_digest(expected[role::4]), actual_sha256=word_digest(actual[role::4]))
    return dict(exact=not mismatches, total=totals, by_position=positions, by_counter=groups,
                expected_sha256=word_digest(expected), actual_sha256=word_digest(actual),
                nonfull_slots=losses, mismatches=mismatches)


def negative_controls(sender, coverage):
    expected = [w if n == 33 else None for w, n in zip(sender, coverage)]
    good = next(i for i, n in enumerate(coverage) if n == 33)
    lost = next(i for i, n in enumerate(coverage) if n < 33)
    flipped = expected.copy()
    flipped[good] = bytes([sender[good][0] ^ 128]) + sender[good][1:]
    invented = expected.copy()
    invented[lost] = sender[lost]
    missing = expected.copy()
    missing[good] = None
    cases = {"changed_one_bit": (flipped, "wrong_word"), "one_slot_rotation": (expected[-1:] + expected[:-1], None),
             "supplied_sender_word_in_erasure": (invented, "false_supply"), "removed_good_word": (missing, "extra_erasure")}
    results = {}
    for name, (test, outcome) in cases.items():
        comparison = compare(test, sender, coverage)
        failures = comparison["mismatches"]
        if not failures or (outcome and (len(failures) != 1 or failures[0]["outcome"] != outcome)):
            raise ValueError(f"negative control passed unexpectedly: {name}")
        results[name] = dict(rejected=True, mismatches=len(failures), first_mismatch=failures[0])
    return results


def pcm_bytes(path):
    data = read_bytes(path)
    if data.startswith(b"RIFF") and data[8:12] == b"WAVE":
        with wave.open(io.BytesIO(data), "rb") as wav:
            if (wav.getframerate(), wav.getnchannels(), wav.getsampwidth()) != (16000, 1, 2):
                raise ValueError("expected mono PCM16 at 16 kHz")
            data = wav.readframes(wav.getnframes())
    if len(data) != SLOTS * 320 * 2:
        raise ValueError("expected 48 seconds of mono PCM16")
    return data


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("receiver", type=Path)
    cli.add_argument("sender", type=Path)
    cli.add_argument("--transport-mask", type=Path, help="optional extra losses, JSON mapping decimal ticks to four booleans")
    cli.add_argument("--receiver-pcm", type=Path)
    pcm = cli.add_mutually_exclusive_group()
    pcm.add_argument("--sender-pcm", type=Path)
    pcm.add_argument("--sender-pcm-sha256", help="SHA-256 of decoded raw PCM16 samples")
    cli.add_argument("--negative-controls", action="store_true")
    cli.add_argument("--out", type=Path)
    args = cli.parse_args()
    if bool(args.receiver_pcm) != bool(args.sender_pcm or args.sender_pcm_sha256):
        cli.error("PCM comparison requires --receiver-pcm and one sender PCM input or hash")
    inputs = (args.receiver, args.sender, args.transport_mask, args.receiver_pcm, args.sender_pcm)
    if args.out and any(args.out.resolve() == p.resolve() for p in inputs if p):
        cli.error("the report path must be distinct from the inputs")
    try:
        sender_raw, receiver_raw = read_bytes(args.sender), read_bytes(args.receiver)
        sender, actual = read_g192(sender_raw), read_g192(receiver_raw)
        if None in sender:
            raise ValueError("sender reference must supply every slot")
        coverage = [receipt(i, {}) for i in range(SLOTS)]
        result = dict(profile="EF0201 declared-clear synthetic 40-group loss control", groups=GROUPS,
                      first_counter=FIRST, slots=SLOTS, sender_g192_sha256=digest(sender_raw),
                      receiver_g192_sha256=digest(receiver_raw),
                      word_digest_format="In slot order, 00 for erasure or 01 followed by 33 packed MSB-first octets.",
                      primary=compare(actual, sender, coverage))
        if args.transport_mask:
            overlay = read_overlay(args.transport_mask)
            result["transport_overlay"] = dict(source_sha256=digest(args.transport_mask.read_bytes()),
                reported_ticks=len(overlay), comparison=compare(actual, sender, [receipt(i, overlay) for i in range(SLOTS)]))
        if args.negative_controls:
            result["negative_controls"] = negative_controls(sender, coverage)
        if args.receiver_pcm:
            expected_pcm = digest(pcm_bytes(args.sender_pcm)) if args.sender_pcm else args.sender_pcm_sha256.lower()
            if len(expected_pcm) != 64 or any(c not in "0123456789abcdef" for c in expected_pcm):
                raise ValueError("expected a SHA-256 digest for sender PCM")
            got = digest(pcm_bytes(args.receiver_pcm))
            result["pcm"] = dict(sender_sha256=expected_pcm, receiver_sha256=got, identical=got == expected_pcm,
                                 scope="Playback comparison only. Decoder concealment may change PCM after an erasure.")
        out = json.dumps(result, indent=2) + "\n"
        if args.out:
            args.out.write_text(out)
        else:
            print(out, end="")
        return 0 if result["primary"]["exact"] else 1
    except (ValueError, OSError, EOFError, wave.Error, zlib.error) as error:
        cli.error(str(error))


if __name__ == "__main__":
    raise SystemExit(main())
