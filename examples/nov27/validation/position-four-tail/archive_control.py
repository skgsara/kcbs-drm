"""Cross-date comparison of payload octet 30 with text-supported November 25–26 P1 observations.

The donor matches only the raw mode and the specified directly carried payload octets.
All equality tests leave P4 as received. Counts describe a corpus, not a per-frame answer.
Run with Python and NumPy from any directory. Standard output is the aggregate JSON.
"""
from collections import Counter, defaultdict
from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import sys

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "hq-class"))
from archived import CONTRIB, INPUTS, transport
from render_continuous import MODE_POSITIONS, PACKET_STARTS
from review_supplied_records import review


DIRECT = tuple(i for i in range(32) if i % 3 != 0)
SIGNATURES = {
    "all_direct": DIRECT, "tail5": (25, 26, 28, 29, 31),
    "tail3": (28, 29, 31), "tail2": (29, 31), "terminal": (31,),
}
DATES = ("2026-11-25", "2026-11-26")


@dataclass(frozen=True)
class Slot:
    coord: tuple  # counter, phase, cycle, position (1..4)
    date: str
    mode: int
    payload: bytes
    p1_column: int | None

    def signature(self, offsets):
        return bytes([self.mode, *(self.payload[i] for i in offsets)])

    def matches(self, donor, use_p1_support):
        # Forward equality with a previously published P1 column. Only P1 has a label.
        if use_p1_support:
            return (self.payload[30] ^ donor.payload[30]) == (self.p1_column ^ donor.p1_column)
        return (self.payload[30] ^ donor.p1_column) == donor.payload[30]

    def donor_index(self, size):
        text = "%d,%d,%d,%d" % self.coord
        return int.from_bytes(sha256(text.encode("ascii")).digest()[:8], "big") % size


def verified_columns(units, origins):
    """Retain column 10 after ordinary review, recording direct header or body coverage separately."""
    labels, receipts = {}, {}
    for tag in sorted(set(INPUTS.values())):
        path = CONTRIB / "keys" / f"keys_{tag}.npz"
        names = {name for name, label in INPUTS.items() if label == tag}
        ticks = sorted(t for t, sources in origins.items() if names.intersection(sources))
        with np.load(path, allow_pickle=False) as archive:
            counters, prefixes, flags = (archive[k] for k in ("counters", "ks", "crc_supported"))
        du = np.array([units[t] for t in ticks], dtype=np.uint8)
        checked, records = review(counters, prefixes, flags, np.array([t[0] for t in ticks]),
                                  np.array([t[1] for t in ticks]), du)
        covered = set()
        for record in records:
            first = 3 * record["counter"] + record["phase"]
            # The record starts on a 16-byte boundary. Column 10 of each physical
            # block is included only if it precedes the two stored CRC octets.
            for relative in range(10, 2 + record["body_length"], 16):
                covered.add((first + relative // 16) // 3)
        labels[tag] = {
            int(c): (int(prefix[10]), int(c) in covered)
            for c, prefix, mask, confirmed in zip(counters, prefixes, flags, checked, strict=True)
            if mask[10] and confirmed[10]
        }
        receipts[tag] = {
            "label_file": path.name, "sha256": sha256(path.read_bytes()).hexdigest(),
            "ordinary_records": len(records), "reviewed_column10_counters": len(labels[tag]),
            "header_body_column10_counters": sum(body for _, body in labels[tag].values()),
        }
    return labels, receipts


def slots(units, origins, labels, strict):
    rows = []
    for (counter, phase), du in sorted(units.items()):
        tags = {INPUTS[n] for n in origins[counter, phase]}
        dates = {tag[:10] for tag in tags}
        if len(dates) != 1:
            raise ValueError("ambiguous source date")
        date = dates.pop()
        old = [labels[tag][counter] for tag in tags if counter in labels[tag]]
        values = {v for v, covered in old if covered or not strict}
        if len(values) > 1:
            raise ValueError("conflicting contributor P1 column")
        label = next(iter(values), None)
        for index, (header, start) in enumerate(zip(MODE_POSITIONS, PACKET_STARTS, strict=True)):
            cycle, pos = divmod(index, 4)
            if pos == 0 and label is None:
                continue
            rows.append(Slot((counter, phase, cycle, pos + 1), date, int(du[header]),
                             du[start:start + 32].tobytes(), label if pos == 0 else None))
    return rows


def shuffle(rows):
    partitions = defaultdict(list)
    for target in rows:
        partitions[target.date, target.mode, target.coord[3]].append(target)
    rotated = {}
    for members in partitions.values():
        shift = max(1, len(members) // 2)
        for j, target in enumerate(members):
            rotated[target.coord] = members[(j + shift) % len(members)]
    return rotated


def fraction(hit, n):
    return {"matches": int(hit), "compared": int(n), "percent": round(100 * hit / n, 3) if n else None}


def interval(events):
    """Descriptive crossed 64-counter-block resampling of the difference to the shuffled control."""
    if not events:
        return None
    coords = np.array([[e[0] // 64, e[1] // 64] for e in events], dtype=np.int64)
    blocks, indices = np.unique(coords, return_inverse=True)
    indices = indices.reshape(coords.shape)
    differences = np.array([int(e[2]) - int(e[3]) for e in events])
    rng = np.random.default_rng(20261125)
    estimates = []
    for _ in range(2000):
        block_weights = rng.poisson(1, size=len(blocks))
        w = block_weights[indices[:, 0]] * block_weights[indices[:, 1]]
        if w.sum():
            estimates.append(100 * np.average(differences, weights=w))
    return {
        "target_counters": len({e[0] for e in events}), "donor_counters": len({e[1] for e in events}),
        "target_64_counter_blocks": len(set(coords[:, 0])), "donor_64_counter_blocks": len(set(coords[:, 1])),
        "matched_minus_shuffled_percentage_points": round(100 * differences.mean(), 3),
        "descriptive_block_interval_2p5_97p5": np.round(np.percentile(estimates, [2.5, 97.5]), 3).tolist(),
    }


def measure(rows):
    refs = [s for s in rows if s.coord[3] == 1]
    rotated = shuffle(rows)
    result = {}
    for name, offsets in SIGNATURES.items():
        donors = defaultdict(list)
        for donor in refs:  # Sorted counter, phase, cycle by construction.
            donors[donor.date, donor.signature(offsets)].append(donor)
        totals, dates, modes = defaultdict(Counter), defaultdict(Counter), defaultdict(Counter)
        events = defaultdict(list)
        for target in rows:
            other = DATES[1] if target.date == DATES[0] else DATES[0]
            candidates = donors.get((other, target.signature(offsets)))
            if not candidates:
                continue
            reference = candidates[target.donor_index(len(candidates))]
            assert reference.date != target.date and reference.coord[0] != target.coord[0]
            pos = target.coord[3]
            tests = [("P1_supported", True), ("P1_raw", False)] if pos == 1 else [(f"P{pos}_raw", False)]
            for role, supported in tests:
                hit = target.matches(reference, supported)
                null = rotated[target.coord].matches(reference, supported)
                for counts in [totals[role], dates[role, target.date], modes[role, target.mode]]:
                    counts.update(n=1, hit=int(hit), shuffled=int(null))
                if name == "tail3":
                    events[role].append((target.coord[0], reference.coord[0], hit, null))
        def rates(vals):
            return {"matched": fraction(vals["hit"], vals["n"]), "shuffled": fraction(vals["shuffled"], vals["n"])}
        score = {"payload_offsets_in_addition_to_mode": offsets, "totals": {k: rates(v) for k,v in totals.items()}}
        if name == "tail3":
            score.update(by_date={f"{role}/{day}": rates(v) for (role, day),v in dates.items()},
                         by_mode={f"{role}/{mode:02x}": rates(v) for (role, mode),v in modes.items()},
                         counter_block_resampling={k: interval(e) for k,e in events.items()})
        result[name] = score
    return result


def main():
    units, origins, sources, _ = transport()
    labels, receipts = verified_columns(units, origins)
    report = {
        "coordinate_format": "counter,phase,cycle,one-based position; zero-based 32-byte payload offsets",
        "selection": "Deduplicate physical counter/phase. For each target, index supported P1 donors on the OTHER calendar date by mode and exact directly received context. Sort counter/phase/cycle; choose unsigned big-endian first 8 SHA256 bytes of the ASCII decimal target coordinate modulo donor count. Withhold p30 from selection.",
        "shuffled_control": "Keep donor fixed. Rotate target with its P1 support if applicable within position, date and exact mode by max(1, floor(N/2)) in acquisition order.",
        "interval_scope": "2,000 fixed-seed Poisson(1) replicates, multiplying weights for the target and donor 64-counter blocks. The descriptive intervals measure sensitivity to repeated local groups within these two days, with no population extrapolation.",
        "observability": "Both dates use only contributor-authored P1 text labels. Equal P4 and P1 values are pairwise coincidences, with no independent P4 plaintext. No mask is fitted or emitted.",
        "transport_sources": {k: v["source_sha256"] for k,v in sources.items()}, "label_sources": receipts,
    }
    for name, strict in [("reviewed_original_rule", False), ("header_body_only", True)]:
        rows = slots(units, origins, labels, strict)
        report[name] = {"distinct_slots_by_position": dict(Counter(r.coord[3] for r in rows)), "scores": measure(rows)}
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
