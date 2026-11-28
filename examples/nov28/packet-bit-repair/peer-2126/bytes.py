"""Score a sealed mode-only byte forecast on independently received complete peer groups at the same counter."""
import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import byte_rule
from native_groups import native_groups
from peer import PRIMARY_2126, PEER_2126
from render_continuous import MODE_POSITIONS, PACKET_STARTS


def tally(rows, slots):
    checked = [r for r in rows if r["peer_byte"] is not None]
    counts = Counter(r["peer_byte"] for r in checked)
    summary = dict(primary_slots=slots, eligible=len(rows), rule_abstentions=slots - len(rows),
                   peer_checked=len(checked), no_peer_native_group=len(rows) - len(checked),
                   peer_mode_disagrees=sum(r["peer_mode"] != byte_rule.MODE for r in checked),
                   peer_target_hex_counts={f"{k:02X}": v for k, v in sorted(counts.items())})
    for name in ("fitted", "baseline"):
        matches = sum(r[name] == r["peer_byte"] for r in checked)
        summary[name] = dict(exact=matches, wrong=len(checked) - matches)
    return summary


def compare(saved, peer_raw):
    _, receipts, _, groups = native_groups(peer_raw)
    starts = {}
    for receipt in receipts:
        starts.setdefault(receipt["counter"], receipt["phase0_row"])
    comparisons = []
    field_names = ["counter", "phase", "slot", "position", "fitted_byte", "baseline_byte"]
    if saved["row_fields"] != field_names or saved["payload_offset_excluding_mode"] != 4:
        raise ValueError("unexpected decision fields or payload octet")
    for counter, phase, slot, position, fitted, baseline in saved["predictions"]:
        if not 0 <= slot < 60 or (phase, position) != (slot // 20, slot % 4 + 1):
            raise ValueError("inconsistent forecast coordinate")
        index = slot % 20
        offset = PACKET_STARTS[index] + 4
        row = dict(counter=counter, phase=phase, slot=slot, position=position, fitted=fitted, baseline=baseline,
                   du_byte=offset, peer_ordinal=offset // 179, peer_native_row=None, peer_mode=None, peer_byte=None)
        if counter in groups:
            unit = groups[counter][phase]
            row.update(peer_native_row=starts[counter] + phase, peer_mode=unit[MODE_POSITIONS[index]],
                       peer_byte=unit[offset])
        comparisons.append(row)
    targets = saved["native_counters_in_file_order"]
    primary = saved["primary"]
    return dict(source_native_groups=len(targets), peer_native_groups=len(groups),
                shared_native_groups=len(set(targets) & groups.keys()), primary=primary,
                primary_checked=tally([r for r in comparisons if r["counter"] == primary], 60 if primary is not None else 0),
                total=tally(comparisons, len(targets) * 60),
                by_position={p: tally([r for r in comparisons if r["position"] == p], len(targets) * 15)
                             for p in range(1, 5)}, rows=comparisons)


def verify(primary, witness, forecast, seal):
    raw = forecast.read_bytes()
    if sha256(raw).hexdigest() != seal.lower():
        raise ValueError("forecast SHA differs from the external pre-score seal")
    source = primary.read_bytes()
    if sha256(source).hexdigest() != PRIMARY_2126:
        raise ValueError("unexpected primary MSC")
    _, _, _, groups = native_groups(source)
    expected = byte_rule.forecast(PRIMARY_2126, groups, *byte_rule.settings())
    frozen = json.loads(raw)
    if frozen != expected:
        raise ValueError("forecast differs from the original primary mode-only decisions")
    peer_raw = witness.read_bytes()
    if sha256(peer_raw).hexdigest() != PEER_2126:
        raise ValueError("unexpected peer MSC")
    return dict(format="peer-evs-p4-full-byte-v1", primary_msc_sha256=PRIMARY_2126, peer_msc_sha256=PEER_2126,
                forecast_sha256=seal.lower(), scope="Independently CRC-checked contiguous 0/1/2 native groups "
                     "at the same transmitted counter. Each target is word octet 5. Every peer byte at an eligible "
                     "coordinate counts, including a disagreement in the peer mode or payload.", **compare(frozen, peer_raw))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("primary", "witness", "forecast"):
        parser.add_argument(name, type=Path)
    parser.add_argument("--seal", required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(verify(args.primary, args.witness, args.forecast, args.seal), indent=2))
    except (OSError, ValueError) as error:
        parser.exit(2, f"{error}\n")
