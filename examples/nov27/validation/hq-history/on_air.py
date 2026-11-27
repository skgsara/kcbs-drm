"""Count NB/WB HQ history opportunities in complete received 13.2 kbit/s groups.

The mode octet can identify an update to the two high-band pulse-presence flags
and, for an unswitched word, whether the word carries a history report. The
report's two values are at variable payload addresses and are not read here.
"""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np


# Each phase contains five cycles of four words. These are the four clear
# mode octets in each cycle, in transmission order.
MODE_OFFSETS = [offset for i in range(5)
                for offset in (2+i, 39+131*i, 72+131*i, 105+131*i)]


def count_modes(slots):
    """Count header-visible reports and possible predecessors in ordered received runs."""
    bandwidth = dict(NB=0, WB=0, SWB=0)
    switched = transient = reports = linked = adjacent = p2_to_p3 = words = 0
    previous_word = previous_update = None
    for coordinate, mode in slots:
        if previous_word is not None:
            if coordinate <= previous_word:
                raise ValueError("expected unique word coordinates in increasing order")
            if coordinate != previous_word+1:
                previous_update = None
        previous_word = coordinate
        words += 1
        index = mode >> 3
        if index < 29 or mode & 4:
            continue
        bandwidth[("NB", "WB", "SWB")[index-29]] += 1
        if index == 31:
            continue
        if mode & 2:
            # Bit 7 gives prior ACELP frame length. The transient flag is bit 8.
            switched += 1
        elif mode & 1:
            transient += 1
        else:
            reports += 1
            if previous_update is not None:
                linked += 1
                if previous_update+1 == coordinate:
                    adjacent += 1
                    if coordinate % 4 == 2:
                        p2_to_p3 += 1
        # TS 26.443 hq_lr_enc.c stores the new flags for both transient and
        # nontransient NB/WB HQ words. Ineligible modes can intervene.
        previous_update = coordinate
    return dict(words=words, hq_by_bandwidth=bandwidth, nb_wb_updates=bandwidth["NB"]+bandwidth["WB"],
                unswitched_transient=transient, switched_transient_class_unknown=switched,
                unswitched_nontransient_reports=reports, reports_with_observed_previous_update=linked,
                immediately_adjacent_pairs=adjacent, immediately_adjacent_p2_to_p3_pairs=p2_to_p3)


def inspect_archive(path):
    with np.load(path, allow_pickle=False) as archive:
        counters, phases, du = (archive[k] for k in ("counters", "phases", "du"))
        if (counters.ndim != 1 or counters.dtype.kind not in "iu"
                or phases.shape != counters.shape or phases.dtype.kind not in "iu"
                or du.shape != (len(counters), 716) or du.dtype != np.uint8):
            raise ValueError("expected complete data_units.npz from CRC-checked packet salvage")
        mode_octets = du[:, MODE_OFFSETS]
    groups = {}
    for counter, phase, octets in zip(counters, phases, mode_octets, strict=True):
        counter, phase = int(counter), int(phase)
        rows = groups.setdefault(counter, {})
        if not 0 <= counter <= 0xffffffff or phase not in (0, 1, 2) or phase in rows:
            raise ValueError(f"invalid or duplicate counter/phase {counter}/{phase}")
        rows[phase] = octets
    complete = sorted(counter for counter, rows in groups.items() if len(rows) == 3)
    # Unfold all 60 slots per counter. Sorting raw slot ordinals alone would
    # merge positions from unrelated groups or silently bridge reception gaps.
    slots = ((60*counter + 20*phase + i, int(mode))
             for counter in complete for phase in range(3)
             for i, mode in enumerate(groups[counter][phase]))
    return dict(archive_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                complete_groups=len(complete), **count_modes(slots))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data_units", type=Path, help="data_units.npz from CRC-checked packet salvage")
    args = parser.parse_args()
    try:
        print(json.dumps(inspect_archive(args.data_units), indent=2))
    except (OSError, KeyError, ValueError) as error:
        parser.exit(2, f"{parser.prog}: {error}\n")
