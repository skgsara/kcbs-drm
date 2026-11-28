"""Compare fixed bits in a sealed group with an independently demodulated native MSC dump."""
import argparse
from collections import Counter
import gzip
from hashlib import sha256
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "nov28/same-6140-1232"))
from native_groups import checked_bytes, native_groups

EVEN_SHA = "b079ce56f627aead14cd511bbcc624349fe5cb0a36ee330392bd2715149e7c6f"
ODD_SHA = "623bde0dcfaac7e1e409894e6d60f9947046fcfc22f7d2ddcd33526a7a1977db"


def direct_location(slot, word_bit):
    """DU offset plus MSB-first index, only where the wire carries the clear bit."""
    if not 0 <= slot < 60 or not 0 <= word_bit < 264:
        raise ValueError("invalid slot or bit coordinate")
    phase, local = divmod(slot, 20)
    cycle, role = divmod(local, 4)
    word_byte, bit = divmod(word_bit, 8)
    if word_byte == 0:
        offset = 2 + cycle if role == 0 else 39 + 33 * (role - 1) + 131 * cycle
    else:
        payload = word_byte - 1
        if payload % 3 == 0:
            return None
        offset = 7 + 33 * role + 131 * cycle + payload
    return phase, offset, bit


def audit(seal, seal_sha, msc, msc_sha, selection):
    entry = json.loads(gzip.decompress(checked_bytes(seal, seal_sha)))["selections"][selection]
    if entry is None:
        raise ValueError("the sealed selection is absent")
    counter = entry["selection"]["counter"]
    evidence = entry["fields"]["bit_evidence"]
    if evidence["counter"] != counter:
        raise ValueError("counter differs between the seal and its field decisions")
    _, receipts, _, all_units = native_groups(checked_bytes(msc, msc_sha))
    units = all_units.get(counter)
    if units is None:
        raise ValueError("target has no complete 0/1/2 triple with valid packet and DU CRCs")
    result = []
    conditional = Counter()
    fixed = {}
    for s in evidence["slots"]:
        slot = s["slot"]
        phase, local = divmod(slot, 20)
        cycle, zero_position = divmod(local, 4)
        position = zero_position + 1
        if (s["counter"], s["phase"], s["cycle"], s["position"]) != (counter, phase, cycle, position):
            raise ValueError("inconsistent sealed slot coordinates")
        for e in s["events"]:
            if e["kind"] == "conditional":
                # Count the sealed field domain once; overlapping fields can refer to the same bit.
                k = (e["check"], tuple(e["word_bits"]), tuple(e["allowed_values"]),
                     e["observation"], len(e["fixed_bits"]))
                conditional[k] += 1
                continue
            if e["kind"] != "direct_check":
                raise ValueError("unknown kind of sealed event")
            for bit_s, predicted in e["fixed_bits"].items():
                bit = int(bit_s)
                if predicted not in (0, 1):
                    raise ValueError("invalid fixed bit")
                loc = direct_location(slot, bit)
                if loc is None:
                    raise ValueError("sealed direct prediction addresses opaque data")
                coord = slot, bit
                if coord in fixed:
                    if fixed[coord]["predicted"] != predicted:
                        raise ValueError("conflicting direct predictions at the same bit")
                    fixed[coord]["checks"].append(e["check"])
                    continue
                _, offset, index = loc
                observed = (units[phase][offset] >> (7 - index)) & 1
                row = dict(slot=slot, phase=phase, cycle=cycle, position=position, word_bit=bit,
                           du_offset=offset, packet_ordinal=offset // 179, checks=[e["check"]],
                           predicted=predicted, observed=observed, excluded=1-predicted,
                           outcome="match" if predicted == observed else "mismatch")
                fixed[coord] = row
                result.append(row)
    direct = evidence["total"]
    if len(result) != direct["unique_direct_fixed_bits"]:
        raise ValueError("unique fixed direct bit count differs from seal")
    hashes = [sha256(du).hexdigest() for du in units]
    return dict(counter=counter, selection=selection, seal_sha256=seal_sha, witness_msc_sha256=msc_sha,
                witness_phase0_rows=[r["phase0_row"] for r in receipts if r["counter"] == counter],
                witness_du_sha256=hashes, whole_units_equal_to_seal=(hashes == entry["selection"].get("du_sha256")),
                direct_matches=sum(r["outcome"] == "match" for r in result),
                direct_mismatches=sum(r["outcome"] == "mismatch" for r in result), direct=result,
                conditional=[dict(check=k[0], word_bits=k[1], allowed_values=k[2], observation=k[3],
                                  fixed_bits_per_event=k[4], events=n) for k,n in sorted(conditional.items())],
                unique_conditional_fixed_bits=direct["unique_conditional_fixed_bits"],
                conditional_bits_scored_against_clear_labels=0, carried_unknown_bits=direct["carried_unknown_bits"],
                word_erasures=direct["word_erasures"],
                scope="The held-back MSC tests the directly carried bit at the same coordinate. "
                      "The two inputs use disjoint samples of one RF recording. Conditional fields lack "
                      "independent plaintext labels. Repeated predictions may share a mode or history.")


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("witness_msc", type=Path)
    cli.add_argument("--seal", type=Path, default=HERE / "field/even-fields.json.gz")
    cli.add_argument("--seal-sha256", default=EVEN_SHA)
    cli.add_argument("--witness-sha256", default=ODD_SHA)
    cli.add_argument("--selection", choices=("primary","first_unregistered"), default="first_unregistered")
    args = cli.parse_args()
    try:
        report = audit(args.seal, args.seal_sha256, args.witness_msc, args.witness_sha256, args.selection)
    except (ValueError, OSError, KeyError) as exc:
        cli.exit(1, f"{exc}\n")
    print(json.dumps(report, indent=2))
