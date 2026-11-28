"""Compare the released music reconstruction with directly transmitted octets in the paired MSC."""
import argparse
from collections import Counter
import csv
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
DEMO = ROOT / "examples/nov27"
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(HERE.parent / "four-frequency"))
from compare_evs_group import read_words
from digital import digest, load_reference, original_epoch
from locate_evs_slots import PROJECTED_OCTETS, unit_locations


def compare(msc):
    dual = json.loads((HERE.parent / "four-frequency/nov27-digital.json").read_bytes())
    if digest(msc) != dual["contributor_msc_sha256"]:
        raise ValueError("companion MSC differs from the two-frequency replay")
    packets, _ = original_epoch(msc, load_reference(), padded=False)
    direct = {}
    for tick, wires in packets.items():
        unit = b"".join(w[1:-2] for w in wires)
        direct.update(unit_locations(*divmod(tick, 3), unit))

    ledger = DEMO / "frames.csv"
    programme = DEMO / "programme.192.gz"
    supported = DEMO / "text-supported.192.gz"
    sums = Counter()
    labels_by_counter = {}
    by_position = {p: Counter() for p in range(1, 5)}
    equal_direct_bits = Counter()
    seen = set()
    with ledger.open(newline="") as source:
        streams = zip(csv.DictReader(source), read_words(programme), read_words(supported), strict=True)
        for row, word, text_word in streams:
            coord = tuple(int(row[key]) for key in ("counter", "phase", "cycle", "position"))
            label = "text-supported" if text_word else "inferred" if word else "erasure"
            if row["source"] != label or (text_word and word != text_word) or coord in seen:
                raise ValueError(f"inconsistent stream or duplicate slot at {coord}")
            seen.add(coord)
            if coord not in direct:
                continue
            counter = coord[0]
            labels_by_counter.setdefault(counter, Counter())[label] += 1
            by_position[coord[3]][label] += 1
            sums[label] += 1
            if word:
                observed = direct[coord]
                supplied = bytes(word[i] for i in PROJECTED_OCTETS)
                equal_direct_bits[counter] += sum(8 - (a ^ b).bit_count()
                                                  for a, b in zip(observed, supplied, strict=True))
    if not direct.keys() <= seen:
        raise ValueError("some received slots are outside the release ledger")
    groups = []
    for counter, counts in sorted(labels_by_counter.items()):
        if counts.total() != 60:
            raise ValueError(f"incomplete companion counter {counter}")
        supplied = counts["text-supported"] + counts["inferred"]
        compared = supplied * 8 * len(PROJECTED_OCTETS)
        groups.append(dict(counter=counter, supplied=supplied, text_supported=counts["text-supported"],
                           inferred=counts["inferred"], erasures=counts["erasure"],
                           direct_bits_compared=compared, direct_bit_disagreements=compared-equal_direct_bits[counter]))
    return dict(companion_msc_sha256=digest(msc), programme_gzip_sha256=digest(programme),
                text_supported_gzip_sha256=digest(supported), frames_csv_sha256=digest(ledger),
                companion_groups=len(groups), fully_supplied_groups=sum(g["supplied"] == 60 for g in groups),
                labels_in_overlap=dict(sorted(sums.items())), labels_by_position=by_position,
                direct_bits_compared=sum(g["direct_bits_compared"] for g in groups),
                direct_bit_disagreements=sum(g["direct_bit_disagreements"] for g in groups),
                independent_clear_reference_words=0, whole_word_accuracy=None, groups=groups)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("companion_msc", type=Path)
    print(json.dumps(compare(parser.parse_args().companion_msc), indent=2))
