"""Seal the sign-IQ receiver output, then compare its direct octets with a separate receiver run."""
import argparse
from collections import defaultdict
from contextlib import redirect_stdout
import gzip
from hashlib import sha256
import io
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

HERE = Path(__file__).resolve().parent
AGREED = HERE.parent / "agreed-bytes"
sys.path.insert(0, str(AGREED))

from field_groups import history
from native_groups import native_groups
from project_evs_group import PROJECTED_OCTETS, project_group
from received_evs_packets import read_packet_snapshot
from salvage_msc_packets import salvage
from score_air import selected_projection


def registry():
    seen, _ = history()
    previous = json.loads((AGREED / "field/transport-comparison.json").read_bytes())
    seen.update(previous["all_arm_assigned_counters"])
    digest = sha256(",".join(map(str, sorted(seen))).encode("ascii")).hexdigest()
    if len(seen) != 15274 or digest != "2b7855f7b861f4d6f7ba6704225306bd165ca06c2749dccf3ee866299e5f8664":
        raise ValueError("assigned-counter history differs from the fixed inventory")
    return seen, digest


def accepted_packets(path):
    ticks, units, flags = read_packet_snapshot(path)
    return {(int(tick), ordinal): bytes(unit[ordinal * 179:(ordinal + 1) * 179])
            for tick, unit, present in zip(ticks, units, flags, strict=True)
            for ordinal, good in enumerate(present) if good}


def checked_arm(msc, snapshot):
    """Verify accepted coordinates/bytes and reconstruct their earliest source-row witnesses."""
    raw = msc.read_bytes()
    counts, receipts, wires, _ = native_groups(raw)
    packets = accepted_packets(snapshot)
    first = {}
    with TemporaryDirectory() as temp:
        stock = Path(temp) / "stock"
        with redirect_stdout(io.StringIO()):
            salvage([msc], stock, transport_only=True, save_packets=True)
        if packets != accepted_packets(stock / "packets.npz"):
            raise ValueError("packet snapshot differs from stock transport salvage of the supplied MSC")
        provenance = json.loads((stock / "provenance.json").read_bytes())
        for tick, ordinal in packets:
            counter, phase = divmod(tick, 3)
            witnesses = provenance[f"{counter},{phase},{ordinal}"]
            row = min(index for _, index in witnesses)
            if counter not in first or row < first[counter]:
                first[counter] = row
    ordinals = defaultdict(int)
    for tick, _ in packets:
        ordinals[tick // 3] += 1
    partial = min(((row, counter) for counter, row in first.items() if ordinals[counter] < 12), default=None)
    control = dict(counter=partial[1], first_source_row=partial[0],
                   accepted_packets=ordinals[partial[1]]) if partial else None
    native_ids = sorted(wires)
    seen, _ = registry()
    assigned = set(first)
    report = dict(msc_sha256=sha256(raw).hexdigest(), packets_sha256=sha256(snapshot.read_bytes()).hexdigest(),
                  **counts, native_complete_group_occurrences=len(receipts), native_complete_group_ids=native_ids,
                  packet_coordinates=len(packets), assigned_counters=sorted(assigned),
                  prior_assigned_intersection=sorted(seen & assigned))
    return report, receipts, wires, control


def seal(msc, packets):
    seen, digest = registry()
    arm, receipts, _, partial = checked_arm(msc, packets)
    candidates = dict(primary=next(iter(receipts), None), partial_control=partial,
                      first_unregistered=next((r for r in receipts if r["counter"] not in seen), None))
    selections = {}
    for name, selection in candidates.items():
        selections[name] = None if selection is None else dict(
            selection=selection, in_prior_registry=selection["counter"] in seen,
            fields=selected_projection(packets, selection["counter"], evidence_version=2))
    return dict(format="sign-iq-receiver-seal-v1", prior_inventory_size=len(seen), prior_inventory_sha256=digest,
                sign=arm, selections=selections)


def compare_slots(sign, reference):
    """Count individual equal/different bits at the 22 fixed directly carried word octets."""
    positions = {}
    for position in range(1, 5):
        counts = dict(slots=0, agreed_bits=0, disagreed_bits=0, sign_only_bits=0,
                      reference_only_bits=0, neither_received_bits=0,
                      sign_no_direct_bits_slots=0, sign_erased_evs_words=0)
        positions[str(position)] = counts
    for source_row, target_row in zip(sign["slots"], reference["slots"], strict=True):
        coordinates = ("counter", "phase", "cycle", "slot", "position")
        if any(source_row[k] != target_row[k] for k in coordinates):
            raise ValueError("slot coordinates differ between projections")
        counts = positions[str(source_row["position"])]
        counts["slots"] += 1
        source = source_row["octets"].split()
        target = target_row["octets"].split()
        counts["sign_no_direct_bits_slots"] += int(source_row["direct_bits"] == 0)
        counts["sign_erased_evs_words"] += int(any(value in ("--", "??") for value in source))
        for octet in PROJECTED_OCTETS:
            left, right = source[octet], target[octet]
            if "??" in (left, right):
                raise ValueError("unknown clear value at a directly carried coordinate")
            if left == "--" and right == "--":
                counts["neither_received_bits"] += 8
            elif left == "--":
                counts["reference_only_bits"] += 8
            elif right == "--":
                counts["sign_only_bits"] += 8
            else:
                diff = (int(left, 16) ^ int(right, 16)).bit_count()
                counts["agreed_bits"] += 8 - diff
                counts["disagreed_bits"] += diff
    for counts in positions.values():
        counts["comparable_bits"] = counts["agreed_bits"] + counts["disagreed_bits"]
        counts["sign_erased_direct_bits"] = counts["reference_only_bits"] + counts["neither_received_bits"]
        counts["unavailable_bits"] = counts["sign_erased_direct_bits"] + counts["sign_only_bits"]
        capacity = 15 * 8 * len(PROJECTED_OCTETS)
        if counts["slots"] != 15 or counts["comparable_bits"] + counts["unavailable_bits"] != capacity:
            raise ValueError("invalid number of slot or bit coordinates")
    return positions


def compare_wires(sign, reference):
    shared = sorted(sign.keys() & reference.keys())
    mismatches = []
    for counter in shared:
        for phase, (left, right) in enumerate(zip(sign[counter], reference[counter], strict=True)):
            for q in range(4):
                packet = slice(182 * q, 182 * (q + 1))
                if left[packet] != right[packet]:
                    mismatches.append([counter, phase, q])
    return dict(shared_complete_groups=len(shared), shared_group_ids=shared, compared_wire_packets=12 * len(shared),
                mismatching_wire_packets=mismatches, matching_wire_packets=12 * len(shared) - len(mismatches),
                sign_only_native_ids=sorted(sign.keys() - reference.keys()),
                reference_only_native_ids=sorted(reference.keys() - sign.keys()))


def compare(seal_path, expected, reference_msc, reference_packets, sign_msc):
    data = seal_path.read_bytes()
    if sha256(data).hexdigest() != expected:
        raise ValueError("seal SHA-256 mismatch")
    sealed = json.loads(gzip.decompress(data))
    sign_data = sign_msc.read_bytes()
    if sealed["format"] != "sign-iq-receiver-seal-v1" or sha256(sign_data).hexdigest() != sealed["sign"]["msc_sha256"]:
        raise ValueError("sign MSC or seal format differs")
    _, _, sign_wires, _ = native_groups(sign_data)
    ref, _, ref_wires, _ = checked_arm(reference_msc, reference_packets)
    scores = {}
    for name, entry in sealed["selections"].items():
        scores[name] = None
        if entry is None:
            continue
        counter = entry["selection"]["counter"]
        source = entry["fields"]["projection"]
        target = project_group(reference_packets, counter, packets=True)
        scores[name] = dict(counter=counter, in_prior_registry=entry["in_prior_registry"],
                            sign_pristine_native=counter in sign_wires, reference_pristine_native=counter in ref_wires,
                            sign_word_erasures=source["word_erasures"],
                            by_position=compare_slots(source, target))
    return dict(format="sign-iq-reference-comparison-v1", seal_sha256=expected,
                prior_inventory_sha256=sealed["prior_inventory_sha256"],
                prior_inventory_size=sealed["prior_inventory_size"],
                sign=sealed["sign"], reference=ref, native_wires=compare_wires(sign_wires, ref_wires),
                selections=scores, scope="Directly carried bits only. The reference uses the same RF recording.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    predict = commands.add_parser("seal")
    predict.add_argument("msc", type=Path)
    predict.add_argument("packets", type=Path)
    evaluate = commands.add_parser("compare")
    evaluate.add_argument("seal_gz", type=Path)
    evaluate.add_argument("seal_sha256")
    evaluate.add_argument("reference_msc", type=Path)
    evaluate.add_argument("reference_packets", type=Path)
    evaluate.add_argument("sign_msc", type=Path)
    args = parser.parse_args()
    if args.command == "seal":
        result = seal(args.msc, args.packets)
        data = json.dumps(result, sort_keys=True, separators=(",", ":"), allow_nan=False).encode() + b"\n"
        with gzip.GzipFile(filename="", mode="wb", fileobj=sys.stdout.buffer, mtime=0) as output:
            output.write(data)
    else:
        result = compare(args.seal_gz, args.seal_sha256, args.reference_msc, args.reference_packets, args.sign_msc)
        print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
