"""Independently verify complete public FAC/SDC codeword matches across the two station pairs."""
import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path


def crc(bits, width, polynomial):
    mask = (1 << width) - 1
    state = mask
    for bit in bits:
        feedback = ((state >> (width - 1)) & 1) ^ int(bit)
        state = (state << 1) & mask
        if feedback:
            state ^= polynomial
    return state ^ mask


def patterns(path, receipt):
    """Count the complete binary codewords, including transmitted CRC and AFS."""
    data = path.read_bytes()
    if sha256(data).hexdigest() != receipt["source_sha256"]:
        raise ValueError(f"Unexpected callback digest for {path.name}")
    words = {"FAC": Counter(), "SDC": Counter()}
    total = Counter()
    for line in data.decode("ascii").splitlines():
        channel, bits = line.split()
        width, polynomial = {"FAC": (8, 0x1d), "SDC": (16, 0x1021)}[channel]
        length = 72 if channel == "FAC" else 628
        if len(bits) != length or set(bits) - {"0", "1"}:
            raise ValueError(f"Unexpected {channel} record geometry")
        total[channel] += 1
        # SDC AFS occupies the low nibble of its first CRC input byte.
        encoded = ("0000" if channel == "SDC" else "") + bits
        if crc(encoded[:-width], width, polynomial) == int(encoded[-width:], 2):
            word = int(encoded, 2).to_bytes(len(encoded) // 8, "big")
            words[channel][word] += 1
    for channel, counts in words.items():
        stats = receipt["blocks"][channel]
        if (total[channel], sum(counts.values())) != (stats["observed"], stats["crc_passed"]):
            raise ValueError(f"Independent {channel} CRC totals differ for {path.name}")
    return words


def compare(directory):
    receipts = json.loads((directory / "receipt.json").read_text())["cases"]
    sources = {site: patterns(directory / (site + ".bits"), receipt) for site, receipt in receipts.items()}
    pairs = {}
    for trial in ("1228", "1232"):
        first, second = (sources[f"{trial}-{site}"] for site in ("yokohama", "edogawa"))
        channels = {}
        for ch in ("FAC", "SDC"):
            left, right = first[ch], second[ch]
            channels[ch] = [dict(sha256=sha256(word).hexdigest(), yokohama=left[word], edogawa=right[word])
                            for word in sorted(left.keys() | right.keys())]
        pairs[trial] = channels
    return dict(counts="CRC-valid occurrences of each entire codeword in its own file. "
                       "SDC hashes include a leading zero nibble before AFS. Repetition can produce identical "
                       "codeword bytes at different times.", pairs=pairs)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path, nargs="?", default=Path(__file__).resolve().parent)
    print(json.dumps(compare(parser.parse_args().directory), indent=2))
