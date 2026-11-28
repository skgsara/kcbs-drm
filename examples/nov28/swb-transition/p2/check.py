"""Rescore the supplied position-two labels and check their recorded text-witness locations."""
from collections import Counter
import csv
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[3] / "scripts"))
from evs_transition_tags import field


def main():
    records = json.loads((HERE / "witnesses.json").read_bytes())
    totals = Counter()
    with (HERE / "fixture.csv").open(newline="") as stream:
        for row in csv.DictReader(stream):
            count, phase, cycle = (int(row[k]) for k in ("counter", "phase", "cycle"))
            if int(row["slot"]) != 20 * phase + 4 * cycle + 1:
                raise ValueError("P2 coordinate differs")
            for location in row["record_counter_phase_byte_offsets"].split("|"):
                rc, rp, offset = map(int, location.split("/"))
                witness = records[f"{row['capture']}/{rc}/{rp}"]
                if offset % 16 != 11 or (3 * rc + rp + offset // 16) // 3 != count:
                    raise ValueError("text record and slot label column disagree")
                if not 0 <= offset < witness["checked_bytes"]:
                    raise ValueError("label falls outside the CRC-covered record")
            result = field(int(row["mode"], 16), int(row["p31"], 16))
            allowed = result["allowed_high_pairs"]
            frozen = [int(x) for x in row["allowed_pairs_decimal"].split("|") if x]
            if allowed != frozen:
                raise ValueError("receiver prediction differs from frozen alternatives")
            observed = int(row["observed_pair_decimal"])
            totals["slots"] += 1
            if len(allowed) < 4:
                totals["restricted"] += 1
                totals["pair_membership_matches"] += observed in allowed
            if len(allowed) == 1:
                totals["exact_pairs"] += 1
                totals["exact_pair_matches"] += observed == allowed[0]
            for b, v in result["fixed_word_bits"].items():
                totals["individual_bits"] += 1
                totals["individual_matches"] += (observed >> (9 - int(b)) & 1) == v
            if observed not in allowed:
                print(f"counter {count} slot {row['slot']} allowed {allowed}, observed {observed:02b}")
    print(json.dumps(totals, indent=2))


if __name__ == "__main__":
    main()
