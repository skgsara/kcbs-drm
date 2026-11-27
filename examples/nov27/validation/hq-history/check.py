"""Check two previous-band pulse flags on locally generated 13.2 kb/s EVS words."""
import argparse
from collections import Counter, defaultdict
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory

from build_observers import build_observers

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from check_p2_codec_bits import synthetic_pcm
from compare_evs_group import read_words


def require(condition, message):
    if not condition:
        raise ValueError(message)


def run(executable, *arguments):
    result = subprocess.run([executable, *arguments], check=True, capture_output=True)
    events = defaultdict(list)
    for line in result.stderr.decode().splitlines():
        tag, _, fields = line.partition(",")
        if tag in ("PULSE", "WRITE", "READ"):
            events[tag].append(tuple(map(int, fields.split(","))))
    return events


def encoded_bit(word, address):
    octet, offset = divmod(address, 8)
    return (word[octet] >> (7 - offset)) & 1


def verify_history(words, sender, receiver):
    hq_slots = [i for i, word in enumerate(words) if word[0] >> 3 >= 29 and not (word[0] & 4)]
    pulses = sender["PULSE"]
    require([row[0] for row in pulses] == hq_slots, "Sender trace does not cover exactly HQ slots")
    require(pulses == receiver["PULSE"], "Native receiver and sender differ on the top two pulse counts")

    writes = defaultdict(list)
    for slot, start, width, value in sender["WRITE"]:
        require(width == 1 and value in (0, 1), "Unexpected history write")
        writes[slot].append((start, value))
    reads = {slot: (start, first, second) for slot, start, first, second in receiver["READ"]}
    require(len(reads) == len(receiver["READ"]) and set(reads) == set(writes),
            "Receiver and sender history coordinates differ")

    counts = Counter()
    flags = Counter()
    starts = []
    previous = None
    previous_pair = (0, 0)
    for slot, length, transient, n1, n2 in pulses:
        updates = length in (160, 320)
        reports = updates and not transient
        require((slot in writes) == reports, f"Unexpected report eligibility in slot {slot}")
        if reports:
            position, first, second = reads[slot]
            require((first, second) == previous_pair, f"Decoded history bits differ in slot {slot}")
            starts.append(position)
            lows = (position, position + 1)
            expected_write = list(zip(lows, previous_pair))
            require(writes[slot] == expected_write, f"Prior pulse history differs at slot {slot}")
            require(tuple(encoded_bit(words[slot], b) for b in lows) == previous_pair,
                    f"Serialized report differs at slot {slot}")
            visible = sum((b // 8 - 1) % 3 != 0 for b in lows)
            counts["both_bits_in_first_128"] += lows[-1] < 128
            counts[f"direct_bits_{visible}"] += 1
            counts["immediately_previous_slot"] += previous == slot - 1
            if slot % 4 == 2 and previous == slot - 1:
                counts["p3_reports_of_previous_p2"] += 1
                counts["p3_reports_of_previous_p2_both_direct"] += visible == 2
            counts["reports"] += 1
            flags["".join(map(str, previous_pair))] += 1
        if updates:
            counts["updates"] += 1
            previous, previous_pair = slot, (int(n1 > 0), int(n2 > 0))

    return dict(hq_words=len(pulses), reports=counts["reports"], updates=counts["updates"],
                observed_pairs=dict(flags), report_starts_min_max=[min(starts), max(starts)] if starts else [],
                reports_from_immediately_previous_slot=counts["immediately_previous_slot"],
                p3_reports_of_immediate_p2=counts["p3_reports_of_previous_p2"],
                p3_reports_of_immediate_p2_both_direct=counts["p3_reports_of_previous_p2_both_direct"],
                report_both_bits_inside_first_128=counts["both_bits_in_first_128"],
                directly_visible_bits_0_1_2=[counts[f"direct_bits_{n}"] for n in (0, 1, 2)])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("codec_source", type=Path, help="unmodified floating TS 26.443 c-code directory")
    args = parser.parse_args()
    expected = json.loads((HERE / "expected.json").read_text())
    with TemporaryDirectory() as name:
        tmp = Path(name)
        pcm = tmp / "input.s16"
        pcm.write_bytes(synthetic_pcm())
        require(sha256(pcm.read_bytes()).hexdigest() == expected["input_pcm_sha256"], "Stimulus hash mismatch")
        encoder, decoder = build_observers(args.codec_source.resolve(), tmp)
        for band in ("WB", "SWB"):
            stream, output = tmp / (band + ".192"), tmp / (band + ".pcm")
            sender = run(encoder, "-q", "-no_delay_cmp", "-max_band", band, "13200", "32", pcm, stream)
            receiver = run(decoder, "-q", "-no_delay_cmp", "16", stream, output)
            words = list(read_words(stream))
            require(len(words) == 2400 and all(len(w) == 33 for w in words), "Unexpected word count or length")
            actual = verify_history(words, sender, receiver)
            actual["g192_sha256"] = sha256(stream.read_bytes()).hexdigest()
            actual["pcm_sha256"] = sha256(output.read_bytes()).hexdigest()
            require(actual == expected[band], f"{band} differs from expected.json: {actual}")
            print(f"{band}: {len(words)} words, {actual['hq_words']} HQ, "
                  f"{actual['reports']} history reports matched, G.192 and PCM hashes matched")


if __name__ == "__main__":
    main()
