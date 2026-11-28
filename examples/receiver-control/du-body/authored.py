"""Compare unchanged native DU bodies from the authored clear-IQ fixture with its encoder words."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys

from check import assess, body, passes
from drm_row_alignment import parse_msc, valid_packets
from render_continuous import MODE_POSITIONS, PACKET_STARTS
from salvage_msc_packets import crc

HERE = Path(__file__).resolve().parent
CASE = HERE.parent
sys.path.insert(0, str(CASE))
from verify import FIRST, GROUPS, read_bytes, read_g192


def verified_bytes(path, expected):
    raw = read_bytes(path)
    if sha256(raw).hexdigest() != expected:
        raise ValueError(f"uncompressed SHA-256 mismatch for {path.name}")
    return raw


def classify(row):
    if len(valid_packets(row)) == 4:
        unit = body(row)
        return (unit, None) if passes(unit) else None
    kind, evidence = assess(row)
    if kind != "fcs_only_compatible" or evidence["fcs_differing_bits_with_canonical_header"] != 1:
        return None
    q = evidence["ordinal"]
    wire = row[182*q:182*(q+1)]
    unit = body(row)
    return unit, dict(failed_ordinal=q, received_fcs=wire[-2:].hex(), packet_crc_passed=False,
                      recomputed_fcs=crc(wire[:-2]).to_bytes(2, "big").hex(),
                      unchanged_du_sha256=sha256(unit).hexdigest())


def select(raw):
    rows = [classify(row) for row in parse_msc(raw)]
    strict, compatible, failures = {}, {}, []
    for start in range(len(rows) - 2):
        triple = rows[start:start + 3]
        if any(item is None for item in triple):
            continue
        units, annotations = zip(*triple, strict=True)
        if [unit[1] >> 4 for unit in units] != [0, 1, 2]:
            continue
        counter = int.from_bytes(units[0][664:668], "big")
        if not FIRST <= counter < FIRST + GROUPS:
            continue
        if counter in compatible:
            raise ValueError(f"duplicate native triple for fixture counter {counter}")
        words = [unit[mode:mode+1] + unit[payload:payload+32] for unit in units
                 for mode, payload in zip(MODE_POSITIONS, PACKET_STARTS, strict=True)]
        compatible[counter] = words
        if all(note is None for note in annotations):
            strict[counter] = words
        for phase, note in enumerate(annotations):
            if note is not None:
                failures.append(dict(counter=counter, phase=phase, native_row=start + phase, **note))
    return strict, compatible, failures


def compare(words, sender):
    good = [actual == target for actual, target in zip(words, sender, strict=True)]
    return dict(slots=len(words), supplied=sum(w is not None for w in words),
                erased=words.count(None), exact_words=sum(good),
                wrong_words=sum(w is not None and not ok for w, ok in zip(words, good, strict=True)),
                complete_groups=sum(None not in words[i:i+60] for i in range(0, len(words), 60)),
                exact_complete_groups=sum(all(good[i:i+60]) for i in range(0, len(words), 60)))


def timeline(groups):
    return [word for c in range(FIRST, FIRST + GROUPS) for word in groups.get(c, [None] * 60)]


def replay(native_path):
    receiver = json.loads((CASE / "result/receiver.json").read_bytes())["source_and_receiver_sha256"]
    strict, compatible, failures = select(verified_bytes(native_path, receiver["msc"]))
    stock = read_g192(verified_bytes(CASE / "result/received.192.gz", receiver["receiver_g192"]))
    sender_info = json.loads((CASE / "fixture/sender.json").read_bytes())["files"]["sender.192.gz"]
    sender_digest = sender_info["uncompressed_sha256"]
    sender = read_g192(verified_bytes(CASE / "fixture/sender.192.gz", sender_digest))
    if None in sender:
        raise ValueError("every slot requires a supplied independent encoder word")
    return dict(native_msc_sha256=receiver["msc"], iq_sha256=receiver["source_iq"],
                receiver_g192_sha256=receiver["receiver_g192"], sender_g192_sha256=sender_digest,
                first_counter=FIRST, last_counter=FIRST + GROUPS - 1,
                stock_receiver=compare(stock, sender), strict_native_triples=compare(timeline(strict), sender),
                including_fcs_compatible_triples=compare(timeline(compatible), sender),
                additional_complete_counters=sorted(compatible.keys() - strict.keys()),
                original_failed_packets_in_selected_triples=failures)


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--native", type=Path, default=CASE / "phase-anchors/synthetic-native.msc.bin.gz",
                     help="original pinned receiver MSC, raw or gzipped")
    args = cli.parse_args()
    print(json.dumps(replay(args.native), indent=2))
