"""Recheck one November 25 reception claim and cross-site DU matches from November 28."""
from collections import defaultdict
from hashlib import sha256
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
PAIR = ROOT / "examples/nov28/same-6140-1232"
sys.path.insert(0, str(ROOT / "scripts"))
from received_evs_packets import read_packet_snapshot
from salvage_msc_packets import records


def november_25_gap():
    path = ROOT / "contrib/kcbsdrm/reference/sf_2026-11-25_0457KST_3205_hik.bin"
    for row in records(path):
        if row and row["complete"] and row["phase"] == 0 and 43680333 <= row["counter"] <= 43680338:
            yield dict(row=row["index"], counter=row["counter"], phase=row["phase"],
                       du_crc=row["du"][-2:].hex(), du_sha256=sha256(row["du"]).hexdigest())


def complete_units(site):
    ticks, units, flags = read_packet_snapshot(PAIR / f"{site}-packets.npz")
    return {int(tick): unit.tobytes() for tick, unit, present in zip(ticks, units, flags, strict=True)
            if present.all()}


def matches_outside_original_snapshot(site, peer):
    original = complete_units(site)
    peer_ticks = defaultdict(list)
    for tick, unit in complete_units(peer).items():
        peer_ticks[unit].append(tick)
    for row in records(PAIR / f"{site}-msc.bin"):
        if row is None or not row["complete"]:
            continue
        matches = peer_ticks.get(row["du"], [])
        if len(matches) == 1 and matches[0] not in original:
            counter, phase = divmod(matches[0], 3)
            yield dict(row=row["index"], counter=counter, phase=phase,
                       du_sha256=sha256(row["du"]).hexdigest())


if __name__ == "__main__":
    print(json.dumps(dict(
        complete_phase_zero_in_reported_gap=list(november_25_gap()),
        edogawa_matched_to_original_yokohama=list(matches_outside_original_snapshot("edogawa", "yokohama")),
        yokohama_matched_to_original_edogawa=list(matches_outside_original_snapshot("yokohama", "edogawa")),
    ), indent=2))
