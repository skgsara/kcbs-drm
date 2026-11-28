"""Measure six EVS checks on controlled substitutions in unmasked 3GPP words."""
import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path

from score import HERE, RULES, observations, read_words


# Half-open, MSB-first bit intervals of the full 264-bit EVS word.
FIELDS = {
    "wb_gsc_audio": (40, 41),
    "swb_gsc_inactive": (44, 48),
    "audio_noisy": (40, 41),
    "inactive_nibble": (40, 44),
    "noisy_pitch_fill": (223, 224),
    "swb_transition_pair": (8, 10),
}


def replace_field(word, start, end, value):
    octet, offset = divmod(start, 8)
    width = end - start
    shift = 8 - offset - width
    changed = bytearray(word)
    mask = ((1 << width) - 1) << shift
    changed[octet] = (word[octet] & ~mask) | value << shift
    return bytes(changed)


def check_fields(index, word, original, counts):
    for name, observed, allowed, _ in original:
        start, end = FIELDS[name]
        row = counts[name]
        row["words"] += 1
        for value in range(1 << (end - start)):
            if value == observed:
                continue
            changed = replace_field(word, start, end, value)
            updates = {check: (actual, choices) for check, actual, choices, _ in observations(index, changed)}
            actual, choices = updates[name]
            if actual != value or choices != allowed:
                raise ValueError(f"{name}: field substitution changed its own test or bit coordinates")
            row["excluded" if value not in choices else "still_allowed"] += 1


def check_payload_bits(index, word, original, counts):
    changed = bytearray(word)
    for offset, row in enumerate(counts):
        for bit in range(8):
            changed[offset + 1] = word[offset + 1] ^ (0x80 >> bit)
            trial = list(observations(index, changed))
            if trial != original:
                row["changed_field_report"] += 1
            if any(value not in allowed for _, value, allowed, _ in trial):
                row["rejected"] += 1
        changed[offset + 1] = word[offset + 1]
        row["trials"] += 8


def summarize(root):
    manifest = json.loads((HERE / "reference-members.json").read_text())
    members = {entry["name"]: entry["member_sha256"] for entry in manifest["members"]}
    fields = {name: Counter(words=0, excluded=0, still_allowed=0) for name in RULES}
    payload = [Counter(trials=0, changed_field_report=0, rejected=0) for _ in range(32)]
    files = {}
    for name in manifest["primary"] + manifest["replication"]:
        path = root / name
        if sha256(path.read_bytes()).hexdigest() != members[name]:
            raise ValueError(f"unexpected file digest: {name}")
        count = 0
        for index, word in enumerate(read_words(path)):
            if not word:
                continue
            original = list(observations(index, word))
            if any(value not in allowed for _, value, allowed, _ in original):
                raise ValueError(f"{name} word {index}: original word already fails a check")
            check_fields(index, word, original, fields)
            check_payload_bits(index, word, original, payload)
            count += 1
        files[name] = count
    return dict(
        schema="official-clear-evs-substitutions-v1",
        files=files,
        original_words=sum(files.values()),
        alternative_field_values=fields,
        payload_bit_changes=[{"payload_offset": offset, **row} for offset, row in enumerate(payload)],
        payload_totals=dict(sum(payload, Counter())),
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("official", type=Path, help="directory containing the official testvec tree")
    print(json.dumps(summarize(parser.parse_args().official), indent=2))
