"""Count complete native DUs near 05:01:40–50 KST using two previously published receiver captures."""
import argparse
from collections import defaultdict
from datetime import datetime, timedelta
from hashlib import sha256
from itertools import accumulate
import json
from pathlib import Path
import re
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from salvage_msc_packets import records

MS_PER_GROUP = 1200
MS_PER_DU = 400
TARGET_MS = 10000


def source_times(header, source_number):
    raw = header.read_bytes()
    text = raw.decode("utf-8-sig")
    names = re.findall(r"SND\.[^\s]+?_(\d{4}-\d{2}-\d{2}T\d\d_\d\d_\d\dZ)_", text)
    start = datetime.strptime(names[source_number], "%Y-%m-%dT%H_%M_%SZ")
    end = datetime.fromisoformat(re.search(r"Capture end\s*:\s*([\d -]+[\d:]+) UTC", text)[1])
    local_date = (start + timedelta(hours=9)).date()
    target = datetime.combine(local_date, datetime.min.time()).replace(hour=5, minute=1, second=40)
    target_utc = target - timedelta(hours=9)
    return start, end, target_utc, sha256(raw).hexdigest()


def window_coverage(offsets, left, c0, target_ms, slack_ms):
    # Each offset starts at the first phase of the first interior counter.
    first = (left + 1 - c0) * MS_PER_GROUP
    intervals = [(first + k * MS_PER_DU, first + (k+1) * MS_PER_DU) for k in offsets]
    target_end = target_ms + TARGET_MS
    changes = {0, slack_ms}
    for interval in intervals:
        for boundary in interval:
            for edge in (target_ms, target_end):
                offset = edge - boundary
                if 0 <= offset <= slack_ms:
                    changes.add(offset)

    def overlap(offset):
        return sum(max(0, min(target_end, b+offset) - max(target_ms, a+offset)) for a, b in intervals)

    points = sorted(changes)
    values = [overlap(offset) for offset in points]
    minimum, maximum = min(values), max(values)
    # Independent integer-millisecond integral of occupied relative DU coordinates.
    earliest = target_ms - slack_ms
    present = set(offsets)
    integral = list(accumulate((int((t-first)//MS_PER_DU in present)
                                for t in range(earliest, target_end)), initial=0))
    all_ms = [integral[i+TARGET_MS] - integral[i] for i in range(slack_ms+1)]
    if (min(all_ms), max(all_ms)) != (minimum, maximum):
        raise ValueError("Whole-millisecond enumeration differs from exact boundary evaluation")
    return dict(nominal_target_duration_ms=TARGET_MS, complete_du_min_ms=minimum, complete_du_max_ms=maximum,
                minimum_at_c0_offset_ms=points[values.index(minimum)], maximum_at_c0_offset_ms=points[values.index(maximum)],
                tested_boundary_offsets=len(points), integer_offsets_crosschecked=slack_ms+1)


def coverage(source, header_name, source_number):
    path = ROOT / source["file"]
    if sha256(path.read_bytes()).hexdigest() != source["sha256"]:
        raise ValueError(f"Unexpected packet file: {path}")
    header = path.parent / header_name
    start, end, target, header_hash = source_times(header, source_number)
    rows = list(records(path))
    full = {i: r for i, r in enumerate(rows) if r and r["complete"] and r["phase"] in (0, 1, 2)}
    if len(full) != source["accepted_complete_dus"]:
        raise ValueError("Input differs from previous complete-DU census")
    anchors = defaultdict(list)
    for i, r in full.items():
        if r["phase"] == 0:
            anchors[r["counter"]].append(i)
    c0, c1 = min(anchors), max(anchors)
    duration_ms = int((end-start).total_seconds()) * 1000
    target_ms = int((target-start).total_seconds()) * 1000
    slack_ms = duration_ms - (c1-c0) * MS_PER_GROUP
    if not 0 <= slack_ms <= target_ms or target_ms + 10000 > duration_ms:
        raise ValueError("Source timing and counter span do not bracket the nominal time")
    # At minimum the two observed phase-zero instants must both lie in the
    # recorded interval. No receiver timestamp per row is available.
    low = c0 + (target_ms - slack_ms) // MS_PER_GROUP
    high = c0 + (target_ms + 10000 - 1) // MS_PER_GROUP
    left = max(c for c in anchors if c < low)
    right = min(c for c in anchors if c > high)
    passes = []
    by_offset = {}
    for i in anchors[left]:
        j = i + 3 * (right - left)
        if j not in anchors[right]:
            continue
        # Exclude all three phases of the left group and the right endpoint.
        received = {row: full[row] for row in range(i + 3, j) if row in full}
        for row, unit in received.items():
            if unit["phase"] != (row - i) % 3:
                raise ValueError("An observed phase contradicts the bracket row sequence")
            if unit["phase"] == 0 and unit["counter"] != left + (row - i) // 3:
                raise ValueError("An interior phase-zero counter contradicts the bracket")
            offset = row - (i+3)
            if by_offset.setdefault(offset, unit["du"]) != unit["du"]:
                raise ValueError("Complete data units disagree at an overlapping bracket coordinate")
        passes.append(dict(anchor_rows=[i, j], interior_native_rows_half_open=[i+3, j],
                           complete_du_observations=len(received)))
    if not passes:
        raise ValueError("No native pass spans both phase-zero anchors at the expected row spacing")
    observations = sum(p["complete_du_observations"] for p in passes)
    return dict(file=source["file"], sha256=source["sha256"], contributor_header=str(header.relative_to(ROOT)),
                header_sha256=header_hash, source_file_start_utc=start.isoformat()+"Z",
                capture_end_utc=end.isoformat()+"Z", target_start_utc=target.isoformat()+"Z",
                native_rows=len(rows), complete_du_observations=len(full),
                distinct_complete_dus_in_file=len({r["du"] for r in full.values()}),
                observed_complete_phase_zero_counter_range=[c0, c1], duration_ms=duration_ms,
                nominal_earliest_phase_zero_offset_range_ms=[0, slack_ms],
                nominal_counter_envelope_inclusive=[low, high], outer_complete_phase_zero_counters=[left, right],
                interior_nominal_duration_ms=(right-left-1)*MS_PER_GROUP, interior_expected_dus=3*(right-left-1),
                passes=passes, distinct_complete_interior_dus=len(set(by_offset.values())),
                complete_interior_coordinate_count=len(by_offset), repeated_interior_observations=observations-len(by_offset),
                complete_du_offsets_from_first_interior=sorted(by_offset),
                ten_second_window=window_coverage(by_offset, left, c0, target_ms, slack_ms))


def run():
    prior = json.loads((HERE / "daily-p1.json").read_bytes())["morning_captures"]
    return dict(
        clock_scope="05:01:40–05:01:50 KST on each date. Korea is UTC+09:00. November 25 uses the "
                    "second 04:57:46 KST IQ filename in the contributor header. Filename starts and capture "
                    "ends are stated to whole seconds; neither file gives per-MSC-row UTC or sample times.",
        envelope="Assume the reported times enclose the phase-zero receptions and the counter advances "
                 "every 1,200 ms. If the recorded UTC duration is D and the observed counter extrema are "
                 "c0,c1, the start of c0 is between 0 and D−1200*(c1−c0) ms after the filename start. "
                 "The counter envelope includes every group intersecting the half-open ten-second interval "
                 "under that assumption. Absolute clock accuracy and receiver delay have not been calibrated.",
        counting="Choose the nearest complete phase-zero anchors strictly outside the counter envelope. "
                 "Count complete, header/CRC-checked native DUs on every pass spanning those anchors at "
                 "the expected three native rows per group. Overlapping 716-byte DUs must agree at each coordinate. "
                 "The interior can be longer than ten seconds. These are transport counts.",
        window="Each complete DU occupies 400 ms at its checked relative coordinate. For all possible offsets "
               "of the first observed counter within the nominal slack, overlap with the requested ten seconds "
               "is piecewise linear. Minima and maxima occur at the endpoints or where a DU boundary meets a "
               "window edge. Times use the nominal file clock; the calculation also checks every whole millisecond.",
        nov25=coverage(prior["left"][1], "KCBS2_text_2026-11-25_0448KST_3205kHz_hik.iptime.org.txt", 1),
        nov26=coverage(prior["right"][0], "KCBS2_text_2026-11-26_0500KST_3205kHz_hl5ntr-sdr.ddns.net.txt", 0))


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--check", action="store_true")
    args = cli.parse_args()
    result = run()
    if args.check and result != json.loads((HERE / "morning-coverage.json").read_bytes()):
        raise SystemExit("Result differs from morning-coverage.json")
    print(json.dumps(result, indent=2))
