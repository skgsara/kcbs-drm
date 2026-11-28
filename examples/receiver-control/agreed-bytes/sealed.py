"""Seal partial direct-octet estimates from two branches, then optionally score against a third."""
import argparse
import gzip
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path

from peer import PACKET_STARTS, MODE_POSITIONS, evaluate, forecasts, read, valid_packets, witnessed_pairs


def addresses():
    result = {}
    for slot, (mode, payload) in enumerate(zip(MODE_POSITIONS, PACKET_STARTS, strict=True)):
        result[int(mode)] = (slot, "mode")
        for p in range(32):
            if p % 3:
                result[int(payload) + p] = (slot, f"p{p}")
    return result


LAYOUT = addresses()
SOURCE_COLUMNS = ["du_offset", "slot_within_du", "position", "field", "one_value", "four_value",
                  "number_of_equal_direct_octets_in_run", "predicted_octet"]


def source_ledger(one, four):
    a, ha = read(one)
    b, hb = read(four)
    pairs, issued = forecasts(a, b)
    rows = []
    for i, j, q, headers_ok, decisions in issued:
        octets = []
        for idx, _, v1, v4, length in decisions:
            offset = q * 179 + idx - 1
            slot, field = LAYOUT[offset]
            octets.append([offset, slot, slot % 4 + 1, field, v1, v4, length, v1 if length >= 8 else None])
        rows.append(dict(one_row=i, four_row=j, ordinal=q, both_headers_canonical=headers_ok, octets=octets))
    return a, issued, dict(schema="two-branch-direct-octet-seal-v1",
                           rule="Emit a branch-common byte in a run of >=8 equal directly carried EVS octets "
                                "in wire order within a single ordinal. Both source packet CRCs failed.",
                           one_sha256=ha, four_sha256=hb, one_rows=len(a), four_rows=len(b),
                           witnessed_branch_row_pairs=len(pairs), candidate_packets=len(issued),
                           candidate_direct_octets=sum(len(p["octets"]) for p in rows),
                           predicted_octets=sum(cell[-1] is not None for p in rows for cell in p["octets"]),
                           octet_columns=SOURCE_COLUMNS, packets=rows)


def encoded(obj, compressed):
    data = (json.dumps(obj, separators=(",", ":")) + "\n").encode("ascii")
    if not compressed:
        return data
    buf = BytesIO()
    with gzip.GzipFile(fileobj=buf, filename="", mode="wb", mtime=0) as out:
        out.write(data)
    return buf.getvalue()


def emit(path, obj):
    raw = encoded(obj, path.suffix == ".gz")
    path.write_bytes(raw)
    return sha256(raw).hexdigest()


def check_seal(path, expected):
    raw = path.read_bytes()
    if sha256(raw).hexdigest() != expected:
        raise ValueError("forecast file differs from the supplied SHA-256 seal")
    if raw.startswith(b"\x1f\x8b"):
        raw = gzip.decompress(raw)
    return json.loads(raw)


def with_labels(a, issued, locked, peer_path, label_source):
    if peer_path is None:
        if label_source is not None:
            raise ValueError("--label-source requires --peer")
        peer_rows, hp = [], None
    else:
        if label_source is None:
            raise ValueError("use --label-source same-iq or independent-rf with --peer")
        peer_rows, hp = read(peer_path)
    matched, _ = witnessed_pairs(a, peer_rows)
    mapping = dict(matched)
    a_good = [valid_packets(row) for row in a]
    peer_good = [valid_packets(row) for row in peer_rows]
    groups = evaluate(issued, mapping, peer_good)
    details = []
    for packet in locked["packets"]:
        i, q = packet["one_row"], packet["ordinal"]
        k = mapping.get(i)
        matching = []
        if k is not None:
            matching = [r for r, wire in a_good[i].items() if r != q and peer_good[k].get(r) == wire]
            if not matching or q in a_good[i]:
                raise ValueError("scoring row requires a separate matching canonical ordinal")
        target = None if k is None else peer_good[k].get(q)
        if peer_path is None:
            status = "no_scoring_branch"
        elif k is None:
            status = "row_not_witnessed"
        elif target is None:
            status = "target_failed_crc_or_header"
        else:
            status = "target_crc_and_header_passed"
        octets = []
        for offset, slot, position, field, _, _, _, forecast in packet["octets"]:
            if forecast is None:
                continue
            observed = None if target is None else target[1 + offset % 179]
            octets.append([offset, slot, position, field, forecast, observed,
                           None if observed is None else forecast == observed])
        details.append(dict(one_row=i, four_row=packet["four_row"], peer_row=k, ordinal=q,
                            matching_other_ordinals=matching, target_status=status, predictions=octets))
    comparable = groups["availability"]["peer_target_crc_good"]
    availability = groups["availability"]
    result = dict(schema="two-branch-direct-octet-score-v1", label_source=label_source,
                  peer_sha256=hp, peer_rows=len(peer_rows) if hp else None,
                  witnessed_one_to_peer_pairs=len(matched) if hp else None, availability=availability,
                  estimates=groups["estimates"] if comparable else None,
                  equal_bits=groups["equal_bits"] if comparable else None,
                  detail_columns=["du_offset", "slot_within_du", "position", "field", "prediction",
                                  "observed_or_null", "exact_or_null"],
                  packets=details)
    return result


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    subs = cli.add_subparsers(dest="command", required=True)
    lock = subs.add_parser("seal", help="use only the two original source branches")
    score = subs.add_parser("score", help="verify the recorded source seal before opening optional labels")
    for sub in (lock, score):
        sub.add_argument("--one", type=Path, required=True)
        sub.add_argument("--four", type=Path, required=True)
        sub.add_argument("--out", type=Path, required=True, help="JSON or deterministic .json.gz")
    score.add_argument("--sealed", type=Path, required=True)
    score.add_argument("--sha256", required=True, help="previously recorded seal file SHA-256")
    score.add_argument("--peer", type=Path, help="third branch or independent receiver; omit if unavailable")
    score.add_argument("--label-source", choices=["same-iq", "independent-rf"])
    score.add_argument("--summary", type=Path, help="write compact output without the per-octet table")
    args = cli.parse_args()
    previous = check_seal(args.sealed, args.sha256) if args.command == "score" else None
    rows, issued, ledger = source_ledger(args.one, args.four)
    if args.command == "seal":
        print(emit(args.out, ledger))
        return
    if previous != ledger:
        raise ValueError("both input decisions must reproduce the sealed ledger exactly")
    outcome = with_labels(rows, issued, ledger, args.peer, args.label_source)
    outcome["source_seal_sha256"] = args.sha256
    report_digest = emit(args.out, outcome)
    if args.summary:
        summary = {k: v for k, v in outcome.items() if k not in ("detail_columns", "packets")}
        summary["detail_sha256"] = report_digest
        emit(args.summary, summary)
    print(report_digest)


if __name__ == "__main__":
    main()
