"""Reproduce the frozen 60-word visibility test on two published synthetic sender streams."""
import argparse
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import tempfile

ROOT = Path(__file__).resolve().parents[5]
SENDER = ROOT / "examples/nov27/validation/swb-gsc/sender-pairs.json"
REPLAY = ROOT / "examples/nov28/evs-state-control/check.py"
RECEIPT_SHA256 = "e76dcd8b03b7df6f2200b905426a8c908affe9c805005025ef6ecb615eea7705"
START, STOP, TARGET, BIT = 180, 240, 205, 203
EVERY_THIRD = frozenset(range(0, 31, 3))
OMITTED = (frozenset(), frozenset((15, 18, 21, 24, 27, 30)), EVERY_THIRD, EVERY_THIRD)


def digest(data):
    return sha256(data).hexdigest()


def split_group(group):
    """Serialize each partition by slot, then original octet order; mode is at index zero."""
    visible, hidden, p2_hidden = bytearray(), bytearray(), bytearray()
    for slot, word in enumerate(group):
        for index, value in enumerate(word):
            if index - 1 in OMITTED[slot % 4]:
                hidden.append(value)
                if slot % 4 == 1:
                    p2_hidden.append(value)
            else:
                visible.append(value)
    return bytes(visible), bytes(hidden), bytes(p2_hidden)


def all_but_target_bit(group):
    bits = "".join(f"{value:08b}" for word in group for value in word)
    index = (TARGET - START) * 264 + BIT
    return (bits[:index] + bits[index + 1:]).encode("ascii")


def describe_pair(pair, length, equal):
    if any(len(side) != length for side in pair) or (pair[0] == pair[1]) != equal:
        raise ValueError("unexpected representation length or equality")
    return {"length": length, "equal": equal, "sha256_each": [digest(side) for side in pair]}


def check(encoder):
    raw = SENDER.read_bytes()
    if digest(raw) != RECEIPT_SHA256:
        raise ValueError("published sender receipt differs")
    published = json.loads(raw)
    spec = importlib.util.spec_from_file_location("evs_state_control", REPLAY)
    replay = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(replay)
    source = replay.sender_pairs.synthetic_source()
    if digest(source.tobytes()) != published["synthetic_source_sha256"]:
        raise ValueError("original synthetic source differs")
    with tempfile.TemporaryDirectory() as scratch:
        streams, _ = replay.encode_originals(encoder, source, published["p24"], Path(scratch))
        words = [list(replay.sender_pairs.read_words(path)) for path in streams]
        g192_sha256 = [digest(path.read_bytes()) for path in streams]

    different = [i for i, (left, right) in enumerate(zip(*words, strict=True)) if left != right]
    if different != [TARGET] or any(len(stream) != 240 for stream in words):
        raise ValueError("expected one differing original word among 240")
    groups = [stream[START:STOP] for stream in words]
    visible, hidden, p2_hidden = zip(*(split_group(group) for group in groups), strict=True)
    targets = [stream[TARGET] for stream in words]
    if [w.hex() for w in targets] != published["p24"]["complete_words_hex"]:
        raise ValueError("wrong sender words at the selected slot")
    mask = 128 >> (BIT % 8)
    values = [w[BIT // 8] for w in targets]
    if [(value & mask) != 0 for value in values] != [False, True]:
        raise ValueError("originals did not reproduce the opposite target bits")
    return {
        "published_sender_receipt_sha256": digest(raw),
        "g192_sha256_each": g192_sha256,
        "range_zero_based_half_open": [START, STOP],
        "stream_slot": TARGET, "group_slot": TARGET - START,
        "phase": 1, "cycle_in_phase": 1, "position": 2,
        "visible_octets_per_word_by_position": [33, 27, 22, 22],
        "group_visible_octets": describe_pair(visible, 1560, True),
        "group_hidden_octets": describe_pair(hidden, 420, False),
        "group_p2_hidden_octets": describe_pair(p2_hidden, 90, False),
        "group_all_except_b203_of_target_ascii_bits": describe_pair(
            [all_but_target_bit(group) for group in groups], 15839, True
        ),
        "group_full_octets": describe_pair([b"".join(group) for group in groups], 1980, False),
        "p2_payload_offset": BIT // 8 - 1, "physical_bit_msb_first": BIT,
        "original_octets_hex": [f"{value:02X}" for value in values],
        "original_bit_values": [int(bool(value & mask)) for value in values],
        "complete_matching_neighbors_in_group": [TARGET - START, STOP - TARGET - 1],
        "complete_matching_neighbors_in_stream": [TARGET, len(words[0]) - TARGET - 1],
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--encoder", type=Path, required=True, help="Path to the stock floating-point EVS_cod")
    args = parser.parse_args()
    print(json.dumps(check(args.encoder.resolve()), indent=2))
