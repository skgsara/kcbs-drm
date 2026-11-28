"""Compare changes of packet continuity index inside independently counter-anchored four-row sequences."""
import argparse
from collections import Counter, defaultdict
from hashlib import sha256
import json
from pathlib import Path

from packet_census import HERE, crc, fields, parse_msc


def valid_crc(wire):
    return crc(wire[:-2]) == int.from_bytes(wire[-2:], "big")


def quarters(row):
    return [row[start:start + 182] for start in range(0, 728, 182)]


def coordinates(row):
    if len(row) != 728:
        return None
    wires = quarters(row)
    if not all(valid_crc(wire) for wire in wires):
        return None
    # Skip each physical header after checking its CRC. Its flags/ID/CI never select a sequence.
    unit = b"".join(wire[1:-2] for wire in wires)
    if not valid_crc(unit):
        return None
    phase = unit[1] >> 4
    return phase, int.from_bytes(unit[664:668], "big") if phase == 0 else None


def sequences(rows):
    coords = [coordinates(row) for row in rows]
    starts = defaultdict(list)
    for start in range(len(rows) - 3):
        four = coords[start:start + 4]
        if any(c is None for c in four) or [c[0] for c in four] != [0, 1, 2, 0]:
            continue
        counter = four[0][1]
        if four[-1][1] == (counter + 1) % (1 << 32):
            starts[counter].append(start)
    return starts


def transitions(rows, start):
    parsed = [[fields(wire) for wire in quarters(row)] for row in rows[start:start + 4]]
    stats = {"inside_first_three_rows": Counter(), "three_row_boundaries": Counter()}
    for index in range(3):
        row = parsed[index]
        for a, b in zip(row, row[1:]):
            stats["inside_first_three_rows"][f"{a['packet_id']}:{a['ci']}->{b['packet_id']}:{b['ci']}"] += 1
        a, b = row[-1], parsed[index + 1][0]
        stats["three_row_boundaries"][f"{a['packet_id']}:{a['ci']}->{b['packet_id']}:{b['ci']}"] += 1
    return stats


def run(paths):
    entries = json.loads((HERE / "protocol.json").read_bytes())["cases"]
    pinned = {x["id"].split("-", 1)[1]: x["msc_sha256"] for x in entries if x["id"].startswith("1232-")}
    rows, starts = {}, {}
    for site, path in paths.items():
        raw = path.read_bytes()
        if sha256(raw).hexdigest() != pinned[site]:
            raise ValueError(f"{site} native MSC SHA-256 differs from the 12:32 input")
        rows[site] = parse_msc(raw)
        starts[site] = sequences(rows[site])

    shared = sorted(starts["edogawa"].keys() & starts["yokohama"].keys())
    totals = {site: defaultdict(Counter) for site in paths}
    receipts = []
    compared = matched = 0
    distinct_coordinates = set()
    for counter in shared:
        native_indices = {site: starts[site][counter] for site in paths}
        for site, indices in native_indices.items():
            for index in indices:
                for kind, counts in transitions(rows[site], index).items():
                    totals[site][kind].update(counts)
        copies = []
        for e in native_indices["edogawa"]:
            for y in native_indices["yokohama"]:
                differences = []
                left = rows["edogawa"][e:e + 4]
                right = rows["yokohama"][y:y + 4]
                for offset, (a, b) in enumerate(zip(left, right, strict=True)):
                    for q, (wa, wb) in enumerate(zip(quarters(a), quarters(b), strict=True)):
                        compared += 1
                        distinct_coordinates.add(((counter + offset // 3) % (1 << 32), offset % 3, q))
                        if wa == wb:
                            matched += 1
                        else:
                            differences.append(dict(row_offset=offset, packet_ordinal=q,
                                edogawa_sha256=sha256(wa).hexdigest(), yokohama_sha256=sha256(wb).hexdigest(),
                                edogawa_header=fields(wa), yokohama_header=fields(wb)))
                copies.append(dict(edogawa_rows=list(range(e, e + 4)), yokohama_rows=list(range(y, y + 4)),
                                   edogawa_four_rows_sha256=sha256(b"".join(left)).hexdigest(),
                                   yokohama_four_rows_sha256=sha256(b"".join(right)).hexdigest(), differing_wires=differences))
        receipts.append(dict(counter=counter, next_counter=(counter + 1) % (1 << 32), copies=copies))
    return dict(msc_sha256=pinned, selection="Four consecutive native 728-byte rows, all sixteen packet CRCs "
                "and four 716-byte DU CRCs pass; phases 0/1/2/0 and next counter = first + 1 modulo 2^32. "
                "Packet header fields are first interpreted after selection. Row and packet indices are zero-based.",
                selected_counter_count={k: len(v) for k, v in starts.items()},
                selected_starts_by_counter={site: dict(sorted(s.items())) for site, s in starts.items()},
                shared_counters=len(shared), full_wires_compared=compared, full_wires_matching=matched,
                distinct_wire_coordinates=len(distinct_coordinates), transitions_by_site=totals,
                transition_key="source packet ID:CI -> destination packet ID:CI; each native occurrence counted once per site",
                shared=receipts)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--edogawa", type=Path, required=True)
    p.add_argument("--yokohama", type=Path, required=True)
    args = p.parse_args()
    try:
        print(json.dumps(run(vars(args)), indent=2))
    except (OSError, ValueError) as error:
        p.exit(2, str(error) + "\n")
