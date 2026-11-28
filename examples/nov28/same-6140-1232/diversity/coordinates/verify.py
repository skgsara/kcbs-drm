"""Locate the two retrospectively combined DUs using the released 12:32 native row order."""
from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import sys

import numpy as np

HERE = Path(__file__).resolve().parent
CASE = HERE.parents[1]
FUSION = HERE.parent / "fusion"
ALIGNMENT = HERE.parent / "alignment"
sys.path[:0] = [str(FUSION), str(ALIGNMENT), str(CASE.parents[2] / "scripts")]
from check import check as verify_alignment
from proof import CASES, ORDINAL_HEADERS, accepted, data_unit, valid, verify as verify_fusion, wire_rows
from salvage_msc_packets import salvage


def require(ok, message):
    if not ok:
        raise ValueError(message)


def default_reception(rows, indices):
    """Run the ordinary receiver with source row boundaries intact, including all failed records."""
    with TemporaryDirectory() as temp:
        source = Path(temp) / "input.msc"
        source.write_bytes(b"".join(len(wire).to_bytes(4, "little") + wire for wire in rows))
        out = Path(temp) / "transport"
        with redirect_stdout(StringIO()):
            salvage([source], out, transport_only=True, save_packets=True)
        provenance = json.loads((out / "provenance.json").read_bytes())
        with np.load(out / "data_units.npz", allow_pickle=False) as archive:
            units = {(int(c), int(p)): du.tobytes() for c, p, du in
                     zip(archive["counters"], archive["phases"], archive["du"], strict=True)}
        with np.load(out / "groups.npz", allow_pickle=False) as archive:
            groups = set(map(int, archive["counters"]))
    coords = []
    for i in indices:
        assigned = {tuple(map(int, key.split(",")[:2])) for key, sources in provenance.items()
                    if any(row == i for _, row in sources)}
        require(len(assigned) <= 1, f"ambiguous default provenance at row {i}")
        coords.append(next(iter(assigned), None))
    return coords, units, groups


def complete(wire):
    unit = data_unit(accepted(wire))
    require(unit is not None, "expected four valid packet headers and CRCs and a valid DU CRC")
    return unit


def anchor(left, right, pair):
    """Join only independently witnessed, nonconflicting intact packets at an endpoint."""
    a, b = map(accepted, (left, right))
    require(pair["witness_ordinals"], "no unique cross-station wire match at endpoint")
    require(all(x == y for x, y in zip(a, b) if x and y), "conflicting endpoint packet")
    unit = data_unit([x or y for x, y in zip(a, b)])
    require(unit is not None and unit[1] >> 4 == 0, "invalid phase-zero anchor")
    sources = [site for site, packets in (("edogawa", a), ("yokohama", b)) if packets[0] and packets[3]]
    require(sources, "no single original receiver supplied both phase and counter packets")
    return dict(counter=int.from_bytes(unit[664:668], "big"), du_crc=unit[-2:].hex().upper(),
                edogawa_row=pair["edogawa_row"], yokohama_row=pair["yokohama_row"],
                witness_ordinals=pair["witness_ordinals"], original_counter_sources=sources)


def verify():
    paths = [CASE / f"{site}-msc.bin" for site in ("edogawa", "yokohama")]
    fingerprints = verify_fusion(FUSION, paths)
    pair_file = ALIGNMENT / "row-pairs.json"
    verify_alignment(CASE, pair_file)
    pairs = {(p["edogawa_row"], p["yokohama_row"]): p for p in json.loads(pair_file.read_bytes())}
    require(all(pairs[case]["known_coordinate"] is None for case in CASES), "target had a prior coordinate")
    rows = [wire_rows(path.read_bytes()) for path in paths]
    recovered = wire_rows((FUSION / "recovered.msc.bin").read_bytes())
    phases = [complete(wire)[1] >> 4 for wire in recovered]
    require(phases == [2, 1], "combined rows have unexpected received phases")
    strict = {}
    for site, native, indices in zip(("edogawa", "yokohama"), rows, zip(*CASES), strict=True):
        before, _, old_groups = default_reception(native, indices)
        require(before == [None, None], f"{site} originally assigned a target row")
        augmented = native.copy()
        for i, wire in zip(indices, recovered, strict=True):
            augmented[i] = wire
        coords, units, groups = default_reception(augmented, indices)
        if site == "yokohama":
            context = [complete(augmented[i]) for i in range(119, 123)]
            require([u[1] >> 4 for u in context] == [0, 1, 2, 0], "Y119..122 phase sequence differs")
            c, next_c = (int.from_bytes(context[i][664:668], "big") for i in (0, 3))
            require(c == 43945691 and next_c == c + 1, "Yokohama bounding counters differ")
            require(coords == [None, (c, 1)] and groups - old_groups == {c}, "default group closure differs")
            require(all(units[c, p] == context[p] for p in range(3)), "archived group bodies differ from wires")
            context_crc = [unit[-2:].hex().upper() for unit in context]
        else:
            require(coords == [None, None] and groups == old_groups, "unexpected Edogawa default assignment")
        strict[site] = dict(target_coordinates_before=before, target_coordinates_after=coords,
                            complete_groups_before=len(old_groups), complete_groups_after=len(groups))

    endpoints = []
    for e, y in ((104, 107), (107, 110)):
        endpoints.append(anchor(rows[0][e], rows[1][y], pairs[e, y]))
    first, last = endpoints
    require(last["counter"] == first["counter"] + 1 == 43945688, "nonconsecutive phase-zero anchors")
    for i, (start, target, end) in enumerate(((104, 106, 107), (107, 109, 110))):
        require(end - start == 3 and target - start == phases[0] == 2, "target outside phase-two bracket")
        interior = rows[i][start + 1]
        require(accepted(interior)[0] is None, "expected an absent phase tag in the first interior row")
        for q, header in enumerate(ORDINAL_HEADERS):
            wire = interior[182*q:182*(q+1)]
            require(not valid(wire) or wire[0] == header, "unexpected CRC-valid interior header")
    return dict(targets=[dict(edogawa_row=e, yokohama_row=y, phase=p, du_crc=f["combined"]["du_crc"],
                              du_sha256=f["combined"]["du_sha256"])
                         for (e, y), p, f in zip(CASES, phases, fingerprints, strict=True)],
                default_reception=strict, yokohama_rows_119_through_122_du_crcs=context_crc,
                phase_two_bracket=dict(counter=first["counter"], phase=phases[0], endpoints=endpoints))


if __name__ == "__main__":
    print(json.dumps(verify(), indent=2))
