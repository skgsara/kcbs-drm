"""Select the primary and partial-packet control from one scheduled IQ reception."""
import argparse
import gzip
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
HISTORY_SHA256 = "0b116969b6f496804d22ca48103046f0436da9a40470ab320398af83debbcbc7"
SCRIPTS = HERE.parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS))
from project_evs_group import checked_units
from received_evs_packets import read_packet_snapshot


def score(directory):
    history = gzip.decompress((HERE / "history.json.gz").read_bytes())
    digest = sha256(history).hexdigest()
    if digest != HISTORY_SHA256:
        raise ValueError("counter inventory differs from the frozen registry")
    known = set(json.loads(history)["counter_ids"])
    report = json.loads((directory / "report.json").read_bytes())
    if report["files"] != 1:
        raise ValueError("expected just one demodulated MSC input")
    packet_path = directory / "packets.npz"
    ticks, units, flags = read_packet_snapshot(packet_path)
    complete_dus = {(c, p): u for c, p, u in checked_units(directory / "data_units.npz")}
    received = {}
    accepted_packets = set()
    partial = set()
    for tick, unit, present in zip(ticks, units, flags, strict=True):
        c, p = divmod(int(tick), 3)
        accepted_packets.update(f"{c},{p},{q}" for q, ok in enumerate(present) if ok)
        if present.all():
            received[c, p] = unit.tobytes()
        elif present.any():
            partial.add(c)
    if received != complete_dus:
        raise ValueError("packet snapshot and complete data units disagree")
    whole_groups = {c for c, _ in received if all((c, p) in received for p in range(3))}

    provenance = json.loads((directory / "provenance.json").read_bytes())
    if not accepted_packets.issubset(provenance):
        raise ValueError("packet receipt without a physical source")
    rows = {}
    phase_zero = {}
    sources = set()
    for key, origins in provenance.items():
        c, p, q = map(int, key.split(","))
        sources.update(source for source, row in origins)
        first = min(row for source, row in origins)
        rows[c] = min(first, rows.get(c, first))
        if (p, q) == (0, 0):
            phase_zero[c] = first
    if len(sources) > 1 or not (whole_groups <= phase_zero.keys() and partial <= rows.keys()):
        raise ValueError("expected physical row coordinates from a single receiver run")
    overlap = sorted(known.intersection(rows))
    primary = min(whole_groups, key=lambda c: (phase_zero[c], c), default=None)
    control = min(partial, key=lambda c: (rows[c], c), default=None)

    def projection(counter):
        if counter is None or overlap:
            return None
        command = [sys.executable, "-B", SCRIPTS / "project_evs_group.py", "--packets", packet_path,
                   "--counter", str(counter), "--field-checks"]
        return json.loads(subprocess.check_output(command))

    return dict(prior_inventory_sha256=digest,
                packet_snapshot_sha256=sha256(packet_path.read_bytes()).hexdigest(),
                assigned_counters=sorted(rows), prior_overlap=overlap,
                complete_groups=len(whole_groups), groups_with_partial_packet_rows=len(partial),
                primary=projection(primary), first_partial=projection(control))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("transport_directory", type=Path)
    print(json.dumps(score(parser.parse_args().transport_directory), indent=2))
