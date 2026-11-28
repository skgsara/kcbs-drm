"""Report the half-open IQ sample ranges supported by station timestamps for a UTC window."""
import argparse
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import wave


RATE = 48000
NS = 1_000_000_000
HEADER = ["sample_offset", "sample_pairs", "receiver_unix_ns"]


def utc_ns(value):
    match = re.fullmatch(r"(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)(?:\.(\d{1,9}))?(?:Z|\+00:00)", value)
    if not match:
        raise ValueError("expected a UTC timestamp like 2026-11-28T13:00:00.123456789Z")
    whole = datetime.fromisoformat(match[1]).replace(tzinfo=timezone.utc)
    epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
    delta = whole - epoch
    return (delta.days * 86400 + delta.seconds) * NS + int((match[2] or "").ljust(9, "0"))


def wav_pairs(path):
    with wave.open(str(path), "rb") as wav:
        if (wav.getnchannels(), wav.getsampwidth(), wav.getframerate(), wav.getcomptype()) != (2, 2, RATE, "NONE"):
            raise ValueError("expected a 48 kHz stereo PCM16 IQ WAV")
        count = wav.getnframes()
        if count:
            wav.setpos(count - 1)
            if len(wav.readframes(1)) != 4:
                raise ValueError("truncated final IQ pair")
        if wav.readframes(1):
            raise ValueError("WAV data ends with an incomplete IQ pair")
    return count


def cut_offset(boundary, stamp, count):
    """First local sample whose nominal time is at or after boundary, clamped to the packet."""
    return max(0, min(count, -(-(boundary - stamp) * RATE // NS)))


def update_edge(edge, packet):
    """Preserve all intersecting clock runs, plus the closest packet on either side of a gap."""
    stamp = packet["receiver_unix_ns"]
    count = packet["sample_pairs"]
    difference = (edge["unix_ns"] - stamp) * RATE
    if 0 <= difference < count * NS:
        cut = packet["sample_offset"] + cut_offset(edge["unix_ns"], stamp, count)
        edge["in_packets"].append(dict(packet=packet, first_sample_at_or_after=cut))
    elif difference < 0:
        other = edge["nearest_following_packet"]
        if other is None or stamp < other["receiver_unix_ns"]:
            edge["nearest_following_packet"] = packet
    else:
        other = edge["nearest_preceding_packet"]
        end = stamp * RATE + count * NS
        if other is None or end > other["receiver_unix_ns"] * RATE + other["sample_pairs"] * NS:
            edge["nearest_preceding_packet"] = packet


def bounds(wav, timing_csv, start_ns, end_ns):
    if start_ns >= end_ns:
        raise ValueError("UTC end must follow UTC start")
    expected = wav_pairs(wav)
    edges = {name: dict(unix_ns=t, in_packets=[], nearest_preceding_packet=None, nearest_following_packet=None)
             for name, t in (("start", start_ns), ("end_exclusive", end_ns))}
    selected, blanks, steps = [], [], []
    offset = packets = stamped = run = 0
    previous = None
    with Path(timing_csv).open(newline="", encoding="ascii") as f:
        reader = csv.reader(f)
        if next(reader, None) != HEADER:
            raise ValueError(f"timing CSV must have header {','.join(HEADER)}")
        for line, fields in enumerate(reader, 2):
            if (len(fields) != 3 or not fields[0].isdigit() or not fields[1].isdigit()
                    or (fields[2] and not fields[2].isdigit())):
                raise ValueError(f"invalid timing CSV row {line}")
            start, count = int(fields[0]), int(fields[1])
            if start != offset or count <= 0 or start + count > expected:
                raise ValueError(f"timing CSV row {line} has invalid WAV sample coverage")
            offset += count
            packets += 1
            if not fields[2]:
                if blanks and blanks[-1]["samples"][1] == start:
                    blanks[-1]["samples"][1] = offset
                else:
                    blanks.append(dict(samples=[start, offset], preceding_anchor=previous, following_anchor=None))
                continue
            stamp = int(fields[2])
            if stamp == 0:
                raise ValueError(f"expected blank for an absent receiver timestamp on row {line}")
            if previous:
                distance = start - previous["sample_offset"]
                nominal = (distance * NS + RATE // 2) // RATE
                jump = stamp - previous["receiver_unix_ns"] - nominal
                if abs(jump) * RATE > NS:
                    steps.append(dict(previous_anchor=previous, next_offset=start, next_unix_ns=stamp, signed_jump_ns=jump))
                    run += 1
            packet = dict(sample_offset=start, sample_pairs=count, receiver_unix_ns=stamp, clock_run=run)
            if blanks and blanks[-1]["samples"][1] == start:
                blanks[-1]["following_anchor"] = packet
            previous = packet
            stamped += 1
            for edge in edges.values():
                update_edge(edge, packet)
            lo = start + cut_offset(start_ns, stamp, count)
            hi = start + cut_offset(end_ns, stamp, count)
            if lo == hi:
                continue
            if selected and selected[-1]["samples"][1] == lo and selected[-1]["clock_run"] == run:
                selected[-1]["samples"][1] = hi
                selected[-1]["last_packet"] = packet
            else:
                selected.append(dict(samples=[lo, hi], clock_run=run, first_packet=packet, last_packet=packet))
    if offset != expected:
        raise ValueError(f"timing CSV covers {offset} pairs, WAV contains {expected}")
    return dict(rate_hz=RATE, wav_pairs=expected, timing_packets=packets, timestamped_packets=stamped,
                utc_boundaries=edges, directly_timed_in_window_ranges=selected,
                directly_timed_in_window_pairs=sum(r["samples"][1] - r["samples"][0] for r in selected),
                single_direct_range=selected[0]["samples"] if len(selected) == 1 else None,
                blank_time_ranges=blanks, all_file_samples_timestamped=not blanks, clock_steps=steps,
                interpretation="Sample ranges are half-open and retain WAV file order. Blank timestamps leave UTC "
                               "membership unresolved. Ranges split at blanks and clock steps. Receiver timestamps "
                               "anchor the first pair of each timed packet; offsets within a packet use the nominal rate.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wav", type=Path, help="original IQ WAV")
    parser.add_argument("timing_csv", type=Path, help="its recorder .timing.csv sidecar")
    parser.add_argument("--start", required=True, help="inclusive UTC start")
    parser.add_argument("--end", required=True, help="exclusive UTC end")
    args = parser.parse_args()
    try:
        print(json.dumps(bounds(args.wav, args.timing_csv, utc_ns(args.start), utc_ns(args.end)), indent=2))
    except (OSError, ValueError, EOFError, wave.Error, csv.Error) as error:
        parser.exit(1, f"{error}\n")
