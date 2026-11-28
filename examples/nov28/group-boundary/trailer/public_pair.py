"""Replay the unassigned-packet location test on both public 12:32 UTC MSC recordings."""
import gzip
from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np

from unassigned import coverage, digest, incorporate, inventory, locate, read_packet_snapshot, sites_union, station
from drm_row_alignment import parse_msc, valid_packets

HERE = Path(__file__).resolve().parent
PAIR = HERE.parents[1] / "same-6140-1232"
SITES = ("edogawa", "yokohama")


def baseline(name, manifest, scratch):
    msc = PAIR / f"{name}-msc.bin"
    archived = PAIR / f"{name}-packets.npz"
    record = PAIR / f"{name}-native.json"
    if digest(record) != manifest["stations"][name]:
        raise ValueError(f"{name}: published station receipt hash differs")
    expected = json.loads(record.read_bytes())
    hashes = dict(msc_sha256=digest(msc), packet_archive_sha256=digest(archived))
    if (hashes["msc_sha256"], hashes["packet_archive_sha256"]) != (
            expected["msc_sha256"], expected["archive_sha256"]["packets.npz"]):
        raise ValueError(f"{name}: input hash differs from the published receipt")

    ticks, du, flags = read_packet_snapshot(archived)
    full = flags.all(axis=1)
    reference = scratch / f"{name}-dus.npz"
    np.savez_compressed(reference, counters=(ticks[full] // 3).astype(np.uint32),
                        phases=(ticks[full] % 3).astype(np.uint8), du=du[full])
    stock = scratch / name
    table, assigned = station([msc], stock, reference)
    replay = read_packet_snapshot(stock / "packets.npz")
    if not all(np.array_equal(a, b) for a, b in zip((ticks, du, flags), replay, strict=True)):
        raise ValueError(f"{name}: original salvage packet arrays differ from the published baseline")
    return msc, table, assigned, hashes


def inspect_union_gain(before, after, site_reports):
    first = inventory(before)
    last = inventory(after)
    gained = sorted(last["packet_coordinates"] - first["packet_coordinates"])
    if len(gained) != 1:
        raise ValueError("expected one gained union packet for this frozen pair")
    tick, q = gained[0]
    counter, phase = divmod(tick, 3)
    new_slots = sorted([t // 3, 20 * (t % 3) + i] for t, i in
                       last["complete_33_wire_octet_slots"] - first["complete_33_wire_octet_slots"])
    du = b"".join(after[tick, ordinal] for ordinal in range(4))

    origins = [(site, row["native_row"]) for site, report in site_reports.items() for row in report["location"]["rows"]
               if (row["counter"], row["phase"]) == (counter, phase) and q in row["received_ordinals"]]
    if len(origins) != 1:
        raise ValueError("expected one original source for the gained packet")
    site, native_row = origins[0]
    raw = parse_msc((PAIR / f"{site}-msc.bin").read_bytes())[native_row]
    wire = valid_packets(raw)[q]
    if wire[1:-2] != after[tick, q]:
        raise ValueError("original wire differs from gained packet")

    align_file = PAIR / "diversity/alignment/row-pairs.json"
    aligned = [row for row in json.loads(align_file.read_bytes())
               if row["known_coordinate"] == [counter, phase] and row[site + "_row"] == native_row]
    if len(aligned) != 1:
        raise ValueError("expected one published alignment for the original row")
    anchor = aligned[0]
    mlc_dir = PAIR.parent / "clear-evs-controls/transport-mlc4"
    decisions = json.loads(gzip.decompress((mlc_dir / "decisions.json.gz").read_bytes()))
    mlc4 = mlc_dir / "edogawa-mlc4-msc.bin"
    if digest(mlc4) != decisions["mlc4_sha256"]:
        raise ValueError("published Edogawa four-iteration MSC hash differs")
    four_iter = parse_msc(mlc4.read_bytes())[anchor["edogawa_row"]]
    fusion = json.loads((PAIR / "diversity/fusion/proof.json").read_bytes())
    return dict(
        packet_coordinate=[counter, phase, q], original_site=site, original_row=native_row,
        wire_sha256=sha256(wire).hexdigest(), transmitted_packet_crc=wire[-2:].hex(),
        completed_du_sha256=sha256(du).hexdigest(), transmitted_du_crc=du[-2:].hex(),
        complete_counters_added=sorted(last["complete_three_du_groups"] - first["complete_three_du_groups"]),
        gained_full_wire_slots_counter_and_zero_based_slot=new_slots,
        prior_diversity_alignment=dict(receipt_sha256=digest(align_file), published_row=anchor),
        among_prior_two_fusion_recovery_rows=any((r["edogawa_row"], r["yokohama_row"]) ==
                                                 (anchor["edogawa_row"], anchor["yokohama_row"]) for r in fusion),
        prior_edogawa_mlc4=dict(
            msc_sha256=decisions["mlc4_sha256"], coordinate_in_assigned_packet_union_of_mlc1_mlc4=any(
                r["coordinate"] == [counter, phase, q] for r in decisions["packets"]["rows"]),
            accepted_at_aligned_native_row=q in valid_packets(four_iter)),
        interpretation="The original stock-assigned union lacked this packet coordinate. The earlier cross-site "
                       "alignment ledger already placed this same originally CRC-valid wire at the coordinate.",
    )


def run():
    prior = json.loads((PAIR / "comparison.json").read_bytes())
    with TemporaryDirectory() as directory:
        sites = {name: baseline(name, prior, Path(directory)) for name in SITES}

    before, after, reports = {}, {}, {}
    for name, other in (SITES, tuple(reversed(SITES))):
        msc, own, assigned, hashes = sites[name]
        additions, locations = locate(msc, own, assigned, sites[other][1])
        updated, quarantined = incorporate(own, additions)
        reports[name] = dict(hashes=hashes, location=locations, quarantined_proposals=quarantined,
                             coverage=coverage(own, updated))
        before[name], after[name] = own, updated
    original, prior_conflicts = sites_union(before.values())
    result, final_conflicts = sites_union(after.values())
    return dict(
        format="public-pair-unassigned-trailer-v1", location_rules_sha256=digest(HERE / "unassigned.md"),
        source_pair="../../same-6140-1232 (Edogawa and Yokohama, 6140 kHz, November 28 12:32 UTC)",
        sites=reports, union=dict(quarantined_before=prior_conflicts, quarantined_after=final_conflicts,
                                 coverage=coverage(original, result),
                                 gained_packet=inspect_union_gain(original, result, reports)),
        scope="Both complete, previously published recordings and their original single-site salvage baselines. "
              "The trailer proposes a coordinate. A separate unique packet must agree. "
              "Complete wire slots count transport coverage.",
    )


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
