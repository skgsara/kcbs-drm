"""Locate independently received trailer fragments by exact byte equality in a labelled archive."""
from collections import Counter, defaultdict
from hashlib import sha256
import json

from check import CASE, ROOT, PINS, Q3_START, SLICES, adjacent_observations, blocks, digest, packets
from project_evs_group import checked_units

MEMBER_HASH = "5be01db5e77f42b5b6ddd05fec8d0dee146f48356cdc7d89dd98edc8a04bae5f"
PEER_DU_HASH = "99461ed346d48900aed781d6af9eb6ebac891af1a0302a85aecdfcf9a81ff7ac"
OUTCOMES = ("unique_correct", "unique_wrong", "ambiguous", "absent")


def locate(index, fragments):
    """Only the exact fragment bytes are available to this lookup."""
    return sorted({coord for fragment in fragments for coord in index.get(fragment, ())})


def verdict(found, reference):
    if not found:
        return "absent"
    if len(found) > 1:
        return "ambiguous"
    return "unique_correct" if found[0] == reference else "unique_wrong"


def tally(rows):
    outcomes = Counter(row["outcome"] for row in rows)
    return {"queries": len(rows), **{name: outcomes[name] for name in OUTCOMES}}


def score(index, queries, member_pieces, member_blocks, peer_complete):
    # Resolve *both* possible physical windows before opening the counter/phase labels.
    results = [locate(index, windows) for _, windows in queries]
    scored = []
    selected_results = []
    for ((reference, windows), found) in zip(queries, results, strict=True):
        counter, phase = reference
        selected = locate(index, [windows[phase - 1]])
        selected_results.append(selected == found)
        scored.append(dict(reference=reference, candidates=found, outcome=verdict(found, reference),
                           reference_du_in_index=reference in member_pieces,
                           reference_counter_all_three_dus=counter in member_blocks,
                           peer_complete=3 * counter + phase in peer_complete,
                           phase_selected_outcome=verdict(selected, reference)))
    ledger = [[*r["reference"], r["candidates"], r["outcome"]] for r in scored]
    serialized = json.dumps(ledger, separators=(",", ":")).encode("ascii")
    return dict(
        total=tally(scored),
        by_true_phase={str(p): tally([r for r in scored if r["reference"][1] == p]) for p in (1, 2)},
        by_true_du_availability={name: tally([r for r in scored if r["reference_du_in_index"] == present])
                                 for name, present in (("in_member_index", True), ("absent_from_member_index", False))},
        by_true_counter_completeness={name: tally([r for r in scored if r["reference_counter_all_three_dus"] == full])
                                      for name, full in (("all_three_member_dus", True), ("otherwise", False))},
        by_peer_du={name: tally([r for r in scored if r["peer_complete"] == full])
                    for name, full in (("complete", True), ("partial", False))},
        candidate_count_histogram=dict(sorted(Counter(len(r["candidates"]) for r in scored).items())),
        phase_selected_single_window_outcomes={name: sum(r["phase_selected_outcome"] == name for r in scored)
                                                for name in OUTCOMES},
        same_candidate_lists_as_phase_selected_single_window=sum(selected_results),
        coordinate_ledger_sha256=sha256(serialized).hexdigest(),
    )


def run():
    member_dir = CASE.parent / "member-3205-20min"
    source = json.loads((member_dir / "cross-frequency.json").read_bytes())
    ids = set(source["historical_exposure"]["member_historical_counter_ids"])
    member_path = member_dir / "member-dus.npz"
    peer_path = CASE / "dual-6140.npz"
    peer_dus = ROOT / source["sources"]["edogawa_6140_du_archive"]
    if (digest(member_path), digest(peer_path), digest(peer_dus)) != (MEMBER_HASH, PINS["6140"], PEER_DU_HASH):
        raise ValueError("published input digest differs")

    pieces = {}
    index = defaultdict(list)
    for counter, phase, du in checked_units(member_path):
        a, b = SLICES[phase]
        piece = du[a:b]
        pieces[counter, phase] = piece
        if phase in (1, 2):
            index[piece].append((counter, phase))

    peer, peer_complete = packets(peer_path, peer_dus, ids, None, None)
    queries = []
    for (tick, ordinal), (body, _) in sorted(peer.items()):
        counter, phase = divmod(tick, 3)
        if ordinal == 3 and phase in (1, 2):
            # No phase is passed to the window selection: offer both candidate byte slices.
            windows = [body[a - Q3_START:b - Q3_START] for a, b in SLICES[1:]]
            queries.append(((counter, phase), windows))
    member_blocks = blocks(pieces)
    coords = [coord for matches in index.values() for coord in matches]
    member_ids = {c for c, _ in pieces}
    return dict(
        format="physical-trailer-fingerprint-v1",
        member_du_sha256=MEMBER_HASH, peer_packet_archive_sha256=PINS["6140"], peer_du_sha256=PEER_DU_HASH,
        member_index=dict(
            validated_dus_all_phases=len(pieces), all_counter_ids=len(member_ids),
            dus_by_phase=[sum(p == phase for c, p in pieces) for phase in range(3)],
            indexed_33_byte_coordinates=len(coords), indexed_distinct_fragments=len(index),
            keys_with_multiple_coordinates=sum(len(v) > 1 for v in index.values()),
            coordinates_in_previously_shared_119_counters=sum(c in ids for c, p in coords),
            coordinates_outside_previously_shared_119_counters=sum(c not in ids for c, p in coords),
            complete_96_byte_blocks=len(member_blocks), distinct_96_byte_blocks=len(set(member_blocks.values())),
            consecutive_member_blocks=adjacent_observations(member_blocks),
        ),
        peer_queries=dict(
            scope="All published q3 records with archived phase 1 or 2 in the independent 6140 wire archive. "
                  "The archive selection previously required a shared assigned counter. The lookup uses the entire "
                  "validated 3205 member archive and never receives the peer counter or phase.",
            previously_shared_counter_ids=len(ids), phase_1_or_2_q3_queries=len(queries),
            from_complete_peer_dus=sum(3*c + p in peer_complete for (c, p), _ in queries),
            from_partial_peer_dus=sum(3*c + p not in peer_complete for (c, p), _ in queries),
            physical_du_windows_half_open=SLICES[1:],
        ),
        score=score(index, queries, pieces, member_blocks, peer_complete),
        ledger_format="SHA-256 of compact ASCII JSON rows [true_counter,true_phase,sorted_candidate_coordinates,"
                      "outcome] in ascending true-coordinate order.",
        scope="Retrospective exact recording alignment within these archives. An absent true coordinate can "
              "still have a different matching coordinate if the bytes repeat elsewhere. "
              "Finding a unique match does not by itself establish independent origin.",
    )


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
