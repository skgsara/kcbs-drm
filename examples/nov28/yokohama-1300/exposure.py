"""Compare assigned counters from the frozen 13:00 score with previously published coordinates."""
import argparse
import gzip
from hashlib import sha256
import json
from pathlib import Path
import re


HERE = Path(__file__).resolve().parent
ORIGINAL_SHA = "0b116969b6f496804d22ca48103046f0436da9a40470ab320398af83debbcbc7"
EXTENDED_SHA = "b8809bc9412da1b18b78a8b4f302efd873a00cd71baa3ec04b9c27e457ec480b"
SOURCES = {
    "history.json.gz": "b6332065393163515d80a606959f85df101102daeaf182917dc94fda4f4ea06f",
    "edogawa-native.json": "84b6c70b2a1ca2635263e4ef9d174ec85ca3f37bcbd8167279b214cfac948eed",
    "yokohama-native.json": "abf60a7169082b9be8fd0fc1c37a115a03e903c2c4ebd5a8827c401eb5ae4e38",
}


def counter_ids(values):
    if (not isinstance(values, list) or any(type(n) is not int or not 0 <= n <= 0xffffffff for n in values)
            or sorted(set(values)) != values):
        raise ValueError("expected an ascending list of distinct uint32 counters")
    return set(values)


def registries():
    plain = gzip.decompress((HERE / "history.json.gz").read_bytes())
    if sha256(plain).hexdigest() != ORIGINAL_SHA:
        raise ValueError("original frozen inventory digest mismatch")
    original = counter_ids(json.loads(plain)["counter_ids"])
    extended = set()
    sources = []
    for name, expected in SOURCES.items():
        raw = (HERE.parent / "same-6140-1232" / name).read_bytes()
        if sha256(raw).hexdigest() != expected:
            raise ValueError(f"historical input digest mismatch for {name}")
        if name.endswith(".gz"):
            ids = counter_ids(json.loads(gzip.decompress(raw))["counter_ids"])
        else:
            ids = counter_ids(json.loads(raw)["assigned_counters"])
        sources.append(dict(path="same-6140-1232/" + name, sha256=expected, count=len(ids),
                            new_to_union=len(ids - extended)))
        extended.update(ids)
    serialized = (json.dumps({"counter_ids": sorted(extended)}, separators=(",", ":")) + "\n").encode()
    if not original <= extended or sha256(serialized).hexdigest() != EXTENDED_SHA:
        raise ValueError("extended inventory membership mismatch")
    receipt = dict(revision="b2fc5e307bf2c9a4dc4312101985e41f238490bc", sources=sources,
                   counter_count=len(extended), sha256=EXTENDED_SHA,
                   serialization="compact JSON with a sorted counter_ids array and a trailing LF")
    return original, extended, receipt


def selection(row, label, count, assigned, prior, extended):
    if row is None:
        if count and not prior:
            raise ValueError(f"missing {label} projection")
        return dict(counter=None, previously_observed=None,
                    status="suppressed_by_frozen_overlap" if count else "no_eligible_group")
    if prior or not count or not isinstance(row, dict):
        raise ValueError(f"unexpected {label} projection")
    counter = row["counter"]
    if type(counter) is not int or counter not in assigned or row["format"] != "kcbs-evs-packet-projection-v1":
        raise ValueError(f"invalid {label} packet projection or counter")
    if not all(isinstance(row.get(key), dict)
               for key in ("transition_tags", "core_history", "intra_word", "gsc_fields", "hq_neighbors")):
        raise ValueError(f"missing frozen field-check section in {label}")
    if row["total_slots"] != 60 or len(row["slots"]) != 60:
        raise ValueError(f"expected 60 slots in {label}")
    for i, slot in enumerate(row["slots"]):
        if (slot["counter"], slot["slot"], slot["phase"], slot["cycle"], slot["position"]) != (
                counter, i, i // 20, (i % 20) // 4, i % 4 + 1):
            raise ValueError(f"unexpected slot order in {label}")
    packets = row["received_packet_ordinals"]
    if not isinstance(packets, dict) or any(
            phase not in ("0", "1", "2") or not isinstance(qs, list) or not qs
            or any(type(q) is not int or not 0 <= q < 4 for q in qs)
            or qs != sorted(set(qs)) for phase, qs in packets.items()):
        raise ValueError(f"invalid packet ordinals in {label}")
    if label == "primary" and not all(packets.get(str(p)) == [0, 1, 2, 3] for p in range(3)):
        raise ValueError("primary lacks three complete phases")
    if label == "first_partial" and not any(0 < len(qs) < 4 for qs in packets.values()):
        raise ValueError("partial control lacks a partially received phase")
    return dict(counter=counter, previously_observed=counter in extended, status="reported")


def compare(document, original, extended):
    if document["prior_inventory_sha256"] != ORIGINAL_SHA:
        raise ValueError("score names a different frozen inventory")
    if not re.fullmatch(r"[0-9a-f]{64}", document["packet_snapshot_sha256"]):
        raise ValueError("invalid packet snapshot digest")
    assigned = counter_ids(document["assigned_counters"])
    prior = counter_ids(document["prior_overlap"])
    if prior != original & assigned:
        raise ValueError("score disagrees with frozen counter intersection")
    complete, partial = document["complete_groups"], document["groups_with_partial_packet_rows"]
    if any(type(n) is not int or n < 0 for n in (complete, partial)) or complete + partial > len(assigned):
        raise ValueError("group counts inconsistent with assigned counters")
    return dict(packet_snapshot_sha256=document["packet_snapshot_sha256"],
                assigned_count=len(assigned), frozen_overlap=sorted(prior),
                extended_overlap_count=len(assigned & extended), extended_overlap=sorted(assigned & extended),
                additional_prior_exposure=sorted((assigned & extended) - prior),
                absent_from_extended_count=len(assigned - extended),
                primary=selection(document["primary"], "primary", complete, assigned, prior, extended),
                first_partial=selection(document["first_partial"], "first_partial", partial, assigned, prior, extended))


def check(path):
    raw = path.read_bytes()
    original, extended, receipt = registries()
    return dict(score_sha256=sha256(raw).hexdigest(), frozen_inventory_sha256=ORIGINAL_SHA,
                exposure_inventory=receipt, result=compare(json.loads(raw), original, extended),
                scope="All assigned counters reported by the frozen scorer, including any subsequently "
                      "quarantined coordinates. A score JSON alone cannot authenticate the RF input, "
                      "timing, receiver settings, or physical row order.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("score", type=Path, help="JSON report produced by the frozen score.py")
    args = parser.parse_args()
    try:
        print(json.dumps(check(args.score), indent=2))
    except (OSError, KeyError, TypeError, ValueError) as error:
        parser.exit(2, f"{error}\n")
