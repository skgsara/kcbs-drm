"""Transmit a separately seeded set of declared-clear EF0201 application groups to a local IQ file."""
import argparse
from binascii import crc_hqx
from collections import Counter
from difflib import SequenceMatcher
import gzip
from hashlib import sha256
import json
from pathlib import Path
import secrets
import subprocess
import sys
from tempfile import TemporaryDirectory
import wave

import numpy as np

HERE = Path(__file__).resolve().parent
CONTROL = HERE.parent
sys.path.insert(0, str(CONTROL))
from generate import FIRST_COUNTER, ORIGINAL_SHA256, PACKET_HEADERS, valid_crc
from verify import read_g192

SENDER_SHA256 = "18257ec9536cb2d2c88ee240f54bd866e2cbe90166605501b169cd40d22fef1f"
FRAME_BYTES = 532  # one 264-bit, supplied little-endian G.192 record
GUARDS_BEFORE, GUARDS_AFTER = 30, 24


def digest(data):
    return sha256(data).hexdigest()


def checked_template():
    rows = gzip.decompress((CONTROL / "fixture/sender-msc.bin.gz").read_bytes())
    g192 = gzip.decompress((CONTROL / "fixture/sender.192.gz").read_bytes())
    if digest(rows) != ORIGINAL_SHA256 or digest(g192) != SENDER_SHA256:
        raise ValueError("unexpected source fixture")
    return rows, g192, read_g192(g192)


def add_crc(body):
    return bytes(body) + (crc_hqx(body, 0xffff) ^ 0xffff).to_bytes(2, 'big')


def group_rows(raw, words, index, counter):
    """Check each of the 60 literal encoder words against the packetized sender, then change only phase-zero counter and dependent CRCs."""
    result = bytearray()
    for phase in range(3):
        offset = (index * 3 + phase) * 728
        row = raw[offset:offset + 728]
        packets = [row[q*182:(q+1)*182] for q in range(4)]
        if not all(valid_crc(v) for v in packets) or tuple(v[0] for v in packets) != PACKET_HEADERS:
            raise ValueError("source packet integrity")
        unit = bytearray(b''.join(v[1:-2] for v in packets))
        if not valid_crc(unit) or unit[1] >> 4 != phase:
            raise ValueError("source data unit integrity")
        for cycle in range(5):
            at = 7 + cycle*131
            parsed = [bytes(unit[2+cycle:3+cycle] + unit[at:at+32])]
            parsed.extend(bytes(unit[at+32+j*33:at+65+j*33]) for j in range(3))
            first = index*60 + phase*20 + cycle*4
            if parsed != words[first:first+4]:
                raise ValueError("source wire does not carry the exact four encoder words")
        if phase == 0:
            if int.from_bytes(unit[664:668], 'big') != FIRST_COUNTER + index:
                raise ValueError("source counter")
            unit[664:668] = counter.to_bytes(4, 'big')
            unit = add_crc(unit[:-2])
            row = b''.join(add_crc(bytes([header]) + unit[q*179:(q+1)*179])
                           for q, header in enumerate(PACKET_HEADERS))
        result.extend(row)
    return bytes(result)


def make(modulator, destination, seed=None):
    source, sender, words = checked_template()
    pin = json.loads((CONTROL / "transmitter-receipt.json").read_bytes())
    if digest(modulator.read_bytes()) != pin["modulator_sha256"]:
        raise ValueError("modulator differs from the pinned build")
    seed = secrets.token_hex(32) if seed is None else seed
    seed_bytes = bytes.fromhex(seed)
    if len(seed_bytes) != 32:
        raise ValueError("expected a 256-bit hex seed")

    def draw(label, limit):
        return int.from_bytes(sha256(seed_bytes + label.encode("ascii")).digest(), "big") % limit

    n = 10 + draw("distinct-groups", 8)
    first = (1 << 32) - (3 + draw("rollover", n-5))
    source_start = draw("source-start", 41-n)
    damaged = 1 + draw("damage-group", n-2)
    quarter = 1 + draw("damage-interior-quarter", 2)
    repeat_pool = [i for i in range(n//2) if i != damaged]
    repeat = repeat_pool[draw("repeat-group", len(repeat_pool))]
    insert = n//2 + 1 + draw("repeat-before", n-(n//2+1))
    indices = [*range(insert), repeat, *range(insert, n)]
    payload, original_words, sequence = bytearray(), bytearray(), []
    for i in indices:
        counter = (first + i) % (1 << 32)
        donor = source_start + i
        frame = bytearray(group_rows(source, words, donor, counter))
        if i == damaged:
            # Corrupt one bit of the recorded packet CRC; all payload bytes and DU CRC remain genuine.
            frame[728 + quarter*182 + 180] ^= 0x80
        bad = [k for k in range(12) if not valid_crc(frame[k*182:(k+1)*182])]
        if bad != ([4+quarter] if i==damaged else []):
            raise ValueError("unexpected sender corruption")
        group = sender[donor*60*FRAME_BYTES:(donor+1)*60*FRAME_BYTES]
        sequence.append(dict(counter=counter, source_group=donor, valid=(i!=damaged),
                             rows_sha256=digest(frame), g192_sha256=digest(group)))
        payload.extend(frame)
        original_words.extend(group)

    # The receiver is given only this WAV. It gets neither source/seed nor the unmodulated bitstreams.
    destination.mkdir(exist_ok=True, parents=True)
    answers = destination / "answers"
    answers.mkdir()
    challenge = destination / "challenge"
    challenge.mkdir()
    wav = challenge / "iq.wav"
    with TemporaryDirectory() as temp:
        msc = Path(temp) / "rows.bin"
        msc.write_bytes(payload)
        subprocess.run([modulator, msc, wav], cwd=temp, check=True, stdout=subprocess.PIPE)
    with wave.open(str(wav), "rb") as stream:
        frames = (GUARDS_BEFORE + len(indices)*3 + GUARDS_AFTER)*19200
        if stream.getparams()[:4] != (2,2,48000,frames):
            raise ValueError("incorrect transmitter IQ geometry")
    (answers / "sender.192").write_bytes(original_words)
    truth = dict(format="ef0201-private-sender-v1", seed=seed, source_template_sha256=ORIGINAL_SHA256,
                 source_g192_sha256=SENDER_SHA256, modulator_sha256=pin["modulator_sha256"],
                 submitted_wire_rows_sha256=digest(payload), private_g192_sha256=digest(original_words),
                 input_wav_sha256=digest(wav.read_bytes()), guard_rows=[GUARDS_BEFORE,GUARDS_AFTER],
                 wrong_crc_phase=1, wrong_crc_quarter=quarter, sequence=sequence)
    (answers / "truth.json").write_text(json.dumps(truth,indent=2)+"\n")
    return dict(input_wav=wav.name, input_wav_sha256=truth["input_wav_sha256"],
                private_truth_sha256=digest((answers/"truth.json").read_bytes()))


def symbols(group):
    frames = np.frombuffer(group, dtype="<u2")
    if len(frames) != 60*266:
        raise ValueError("group length is not sixty 264-bit frames")
    frames = frames.reshape(60,266)
    if not (np.all(frames[:,0] == 0x6b21) and np.all(frames[:,1] == 264)
            and np.isin(frames[:,2:], [0x7f,0x81]).all()):
        raise ValueError("invalid supplied G.192 frame")
    return frames[:,2:]


def occurrence_keys(counters):
    counts = Counter()
    result = []
    for counter in counters:
        result.append((counter, counts[counter]))
        counts[counter] += 1
    return result


def score(answers, truth_hash, catalog_path, catalog_hash):
    public_ledger = answers.is_file()
    raw_truth = (answers if public_ledger else answers / "truth.json").read_bytes()
    raw_catalog = catalog_path.read_bytes()
    if digest(raw_truth) != truth_hash or digest(raw_catalog) != catalog_hash:
        raise ValueError("sender or receiver seal mismatch")
    truth = json.loads(raw_truth)
    sequence = truth["sequence"]
    if public_ledger:
        source = gzip.decompress((CONTROL / "fixture/sender.192.gz").read_bytes())
        if digest(source) != truth["source_g192_sha256"]:
            raise ValueError("original stock encoder archive differs from sender receipt")
        group_size = 60 * FRAME_BYTES
        blocks = []
        for entry in sequence:
            start = entry["source_group"] * group_size
            blocks.append(source[start:start + group_size])
        stream = b"".join(blocks)
    else:
        stream = (answers / "sender.192").read_bytes()
    if digest(stream) != truth["private_g192_sha256"] or len(stream) != len(sequence)*60*FRAME_BYTES:
        raise ValueError("wrong sender timeline")
    expected = {}
    valid_keys = []
    for i,(entry,key) in enumerate(zip(sequence, occurrence_keys(r["counter"] for r in sequence), strict=True)):
        block = stream[i*60*FRAME_BYTES:(i+1)*60*FRAME_BYTES]
        if digest(block) != entry["g192_sha256"]:
            raise ValueError("sender group hash mismatch")
        expected[key] = symbols(block)
        if entry["valid"]:
            valid_keys.append(key)
    catalog = json.loads(raw_catalog)
    groups = catalog["groups"]
    positions = [r["phase0_row"] for r in groups]
    if positions != sorted(set(positions)):
        raise ValueError("receiver groups out of native order")
    guards_with_words = [r["phase0_row"] for r in groups if r["kind"] != "declared_clear" and "g192" in r]
    clear = [r for r in groups if r["kind"] == "declared_clear"]
    found_keys = occurrence_keys(r["counter"] for r in clear)
    good_words = np.zeros(4,dtype=int)
    bad_words = np.zeros(4,dtype=int)
    bad_bits = np.zeros(4,dtype=int)
    occurrences = []
    for r,key in zip(clear,found_keys,strict=True):
        leaf = Path(r["g192"])
        if leaf.name != r["g192"]:
            raise ValueError("unexpected group path")
        block = (catalog_path.parent / leaf).read_bytes()
        if digest(block) != r["g192_sha256"]:
            raise ValueError("receiver group hash mismatch")
        observed = symbols(block)
        row = dict(counter=key[0], occurrence=key[1], native_row=r["phase0_row"],
                   matches_expected_occurrence=key in valid_keys)
        if key in expected:
            differences = (observed != expected[key]).reshape(15,4,264)
            good_words += (~differences.any(axis=2)).sum(axis=0)
            bad_words += differences.any(axis=2).sum(axis=0)
            bad_bits += differences.sum(axis=(0,2))
            row["differing_bits"] = int(differences.sum())
        occurrences.append(row)
    def encode_keys(values):
        return [dict(counter=c, occurrence=k) for c,k in values]
    missing = [k for k in valid_keys if k not in found_keys]
    extra = [k for k in found_keys if k not in valid_keys]
    damaged = [r["counter"] for r in sequence if not r["valid"]]
    matching = SequenceMatcher(a=valid_keys,b=found_keys,autojunk=False)
    order_count = sum(block.size for block in matching.get_matching_blocks())
    return dict(sender_truth_sha256=truth_hash,receiver_catalog_sha256=catalog_hash,
                chronological_sender_counters=[r["counter"] for r in sequence],
                damaged_counters=damaged,expected_valid_occurrences=len(valid_keys),
                declared_clear_occurrences=len(clear),ordered_matching_occurrences=order_count,
                other_groups=dict(Counter(r["kind"] for r in groups if r["kind"]!="declared_clear")),
                receiver_occurrences=occurrences,missing_valid_occurrences=encode_keys(missing),
                unexpected_supplied_occurrences=encode_keys(extra),
                supplied_damage_slots=60*sum(k[0] in damaged for k in found_keys),
                guard_groups_with_words=guards_with_words,
                by_position={str(i+1):dict(original_words_matching=int(good_words[i]),
                              original_words_differing=int(bad_words[i]),differing_bits=int(bad_bits[i]))
                             for i in range(4)},
                exact_valid_chronology=valid_keys==found_keys,
                passed=bool(valid_keys==found_keys and not bad_words.any() and not guards_with_words))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    generate = commands.add_parser("generate", help="write IQ to challenge/ and a private answer key to answers/")
    generate.add_argument("modulator", type=Path)
    generate.add_argument("destination", type=Path)
    generate.add_argument("--seed", help="replay a previously disclosed 256-bit sender seed")
    evaluate = commands.add_parser("score", help="run only after sealing the receiver catalog")
    evaluate.add_argument("answers", type=Path, help="original sender output directory or published sender.json")
    evaluate.add_argument("catalog", type=Path)
    evaluate.add_argument("--truth-sha256", required=True)
    evaluate.add_argument("--catalog-sha256", required=True)
    args = parser.parse_args()
    if args.command == "generate":
        result = make(args.modulator.resolve(strict=True), args.destination.resolve(), args.seed)
    else:
        result = score(args.answers, args.truth_sha256, args.catalog, args.catalog_sha256)
    print(json.dumps(result, indent=2))
    if args.command == "score" and not result["passed"]:
        raise SystemExit(1)
