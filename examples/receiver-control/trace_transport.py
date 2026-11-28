"""After the sender reveal, locate scored packets in the sealed native MSC of the synthetic control."""
import argparse
from collections import Counter
import gzip
from hashlib import sha256
import json
from pathlib import Path
import sys

from generate import FIRST_COUNTER, damaged_rows, valid_crc

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "scripts"))
from drm_row_alignment import ROW_BYTES, PACKET_BYTES, read_msc, valid_packets, witnessed_pairs
from received_evs_packets import read_packet_snapshot


def split_rows(raw):
    return [raw[i:i + ROW_BYTES] for i in range(0, len(raw), ROW_BYTES)]


def gate_context(row_map, native, sender_start):
    # Inspect only witnessed contiguous rows. Do not use nominal spacing to pair the dumps.
    window = [row_map.get(sender_start + p) for p in range(4)]
    if None in window or window != list(range(window[0], window[0] + 4)):
        return {"contiguous_witnessed_window": False}
    packets = [valid_packets(native[r]) for r in window]
    incomplete = []
    for p in range(3):
        if len(packets[p]) != 4 or not valid_crc(b"".join(packets[p][q][1:-2] for q in range(4))):
            incomplete.append(window[p])
    return dict(contiguous_witnessed_window=True, incomplete_rows_in_three_phase_group=incomplete,
                four_row_bracket_missing_phase_packet_0=[r for r, pk in zip(window, packets) if 0 not in pk],
                boundary_rows_missing_counter_packet_3=[window[p] for p in (0, 3) if 3 not in packets[p]])


def trace(received):
    receipt = json.loads((HERE / "result/receiver.json").read_bytes())
    msc = received / "demod/msc.bin"
    packet_file = received / "receiver/packets.npz"
    for name, path in (("msc", msc), ("packets", packet_file)):
        if sha256(path.read_bytes()).hexdigest() != receipt["source_and_receiver_sha256"][name]:
            raise ValueError(f"{name} differs from the sealed receiver output")
    provenance = json.loads((received / "receiver/provenance.json").read_bytes())
    ticks, bodies, flags = read_packet_snapshot(packet_file)
    snapshot = {int(t): (unit, ok) for t, unit, ok in zip(ticks, bodies, flags, strict=True)}
    original = gzip.decompress((HERE / "fixture/sender-msc.bin.gz").read_bytes())
    sent, _ = damaged_rows(original)
    pristine, actual = split_rows(original), split_rows(sent)
    native = read_msc(msc)
    pairs, witnesses = witnessed_pairs(pristine, native)
    matched = dict(pairs)
    counts = Counter(dict.fromkeys(("planned_good", "planned_bad", "good_in_unresolved_row",
                                     "good_native_bad_or_missing", "good_native_crc_valid_different",
                                     "good_exact_assigned", "good_exact_unassigned", "good_exact_quarantined",
                                     "bad_delivered_as_sent",
                                     "bad_native_different", "bad_in_unresolved_row", "bad_assigned"), 0))
    whole_equal = 0
    unassigned, quarantined, contexts = [], [], {}
    for i, sent_row in enumerate(actual):
        group, p = divmod(i, 3)
        c = FIRST_COUNTER + group
        nr = matched.get(i)
        valid_sent = valid_packets(sent_row)
        src, ok = snapshot.get(c * 3 + p, (None, (False,) * 4))
        missing = []
        if nr is not None:
            row = native[nr]
            valid_native = valid_packets(row)
            whole_equal += row == sent_row
        for q in range(4):
            scheduled = q in valid_sent
            counts["planned_good" if scheduled else "planned_bad"] += 1
            if nr is None:
                counts["good_in_unresolved_row" if scheduled else "bad_in_unresolved_row"] += 1
                continue
            start = q * PACKET_BYTES
            wire = sent_row[start:start + PACKET_BYTES]
            observed = row[start:start + PACKET_BYTES]
            if ok[q]:
                origins = provenance.get(f"{c},{p},{q}", ())
                if not any(idx == nr for _, idx in origins) or src[q*179:(q+1)*179].tobytes() != observed[1:-2]:
                    raise ValueError(f"accepted packet lacks the matched native wire at {c}/{p}/{q}")
            if not scheduled:
                counts["bad_delivered_as_sent" if wire == observed else "bad_native_different"] += 1
                counts["bad_assigned"] += int(ok[q])
            elif q not in valid_native:
                counts["good_native_bad_or_missing"] += 1
            elif wire != observed:
                counts["good_native_crc_valid_different"] += 1
            elif ok[q]:
                counts["good_exact_assigned"] += 1
            elif provenance.get(f"{c},{p},{q}"):
                counts["good_exact_quarantined"] += 1
                quarantined.append(dict(counter=c, phase=p, native_row=nr, ordinal=q))
            else:
                counts["good_exact_unassigned"] += 1
                missing.append(q)
        if missing:
            unassigned.append(dict(counter=c, phase=p, native_row=nr, crc_good_unassigned_ordinals=missing))
            contexts[str(c)] = gate_context(matched, native, 3 * group)
    return dict(scope="Retrospective comparison to this synthetic sender. One-to-one, order-consistent native "
                      "row pairs require a unique unchanged same-ordinal CRC-good full wire in both dumps.",
                source_template_sha256=sha256(original).hexdigest(), transmitted_rows_sha256=sha256(sent).hexdigest(),
                native_msc_sha256=receipt["source_and_receiver_sha256"]["msc"], alignment=witnesses,
                matched_sender_rows=len(matched), matched_rows_identical_to_transmitted_bytes=whole_equal,
                first_last_native_rows=[pairs[0][1], pairs[-1][1]] if pairs else [],
                unmatched_sender_rows=[i for i in range(len(pristine)) if i not in matched],
                packets=counts, good_packets_unassigned_by_row=unassigned, assignment_gate_context=contexts,
                good_packets_quarantined=quarantined,
                gate_basis="A phase-zero singleton needs good q0 and q3. Phases 1/2 need a complete "
                           "0/1/2 triple or a 0/1/2/0 bracket with good q0 on all four rows and good q3 "
                           "at both counter anchors. The context lists failed physical requirements.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("received", type=Path, help="existing output directory from receive.py")
    args = parser.parse_args()
    try:
        print(json.dumps(trace(args.received), indent=2))
    except (ValueError, OSError, KeyError) as exc:
        parser.exit(1, f"{exc}\n")
