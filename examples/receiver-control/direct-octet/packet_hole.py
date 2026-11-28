"""Test same-position interpolation of directly carried p5 after deleting its physical packet."""
import argparse
from hashlib import sha256
import json
from pathlib import Path

from rule import MEMBER, MEMBER_SHA, MODE_POSITIONS, PACKET_STARTS, complete_dus, native_groups


def address(slot, field):
    phase, local = divmod(slot, 20)
    offset = MODE_POSITIONS[local] if field == "mode" else PACKET_STARTS[local] + 5
    return phase, int(offset)


def packet(cell):
    phase, offset = cell
    return phase, offset // 179


def trial(slot):
    inputs = [address(i, "mode") for i in (slot - 4, slot, slot + 4)]
    inputs += [address(i, "p5") for i in (slot - 4, slot + 4)]
    lost = packet(address(slot, "p5"))
    return slot, lost, inputs


# Each center is a separate deletion from the same intact, independently placed group.
TRIALS = [trial(slot) for slot in range(1, 59, 3) if 0 <= slot - 4 and slot + 4 < 60]
POSSIBLE = [slot for slot, lost, inputs in TRIALS if all(packet(cell) != lost for cell in inputs)]


def proposal(values):
    left_mode, center_mode, right_mode, left, right = values
    return left if left_mode == center_mode == right_mode and left == right else None


def forecasts(groups):
    issued = []
    for counter, triple in groups.items():
        for slot, lost, cells in TRIALS:
            if any(packet(cell) == lost for cell in cells):
                continue
            # Extract only five octets from surviving packets. Neither wire nor DU checksum
            # is passed to the rule. No byte from the missing 179-byte body is ever read.
            values = [triple[phase][offset] for phase, offset in cells]
            value = proposal(values)
            if value is not None:
                issued.append([counter, slot, value])
    return issued


def summary(groups, issued, *, score):
    ids = set(groups)
    counts = {str(p): dict(opportunities=sum(s % 4 + 1 == p for s, _, _ in TRIALS) * len(ids),
                           physically_possible=sum(s % 4 + 1 == p for s in POSSIBLE) * len(ids),
                           issued=0) for p in range(1, 5)}
    if score:
        for row in counts.values():
            row.update(exact=0, miss=0)
    for c, slot, prediction in issued:
        if c not in ids:
            continue
        row = counts[str(slot % 4 + 1)]
        row["issued"] += 1
        if score:
            phase, offset = address(slot, "p5")
            correct = prediction == groups[c][phase][offset]
            row["exact" if correct else "miss"] += 1
    return dict(total={k: sum(r[k] for r in counts.values()) for k in counts["1"]}, by_position=counts)


def decision_file(raw):
    transport, receipts, _, groups = native_groups(raw)
    issued = forecasts(groups)
    primary = receipts[0]["counter"] if receipts else None
    return groups, dict(protocol="direct-p5-single-whole-packet-hole-v1",
                        original_msc_sha256=sha256(raw).hexdigest(), native_transport=transport,
                        complete_counters=list(groups), primary=primary, centers=[s for s, _, _ in TRIALS],
                        physically_possible_centers=POSSIBLE, columns=["counter", "slot", "predicted_p5"],
                        predictions=issued, counts=summary(groups, issued, score=False))


def summary_with_primary(groups, issued, primary):
    return dict(all_groups=summary(groups, issued, score=True),
                primary_counter=primary,
                primary=None if primary is None else summary({primary: groups[primary]}, issued, score=True))


def controls():
    # Give the input reader only its five allowable physical addresses. Additional
    # codeword bits, checksums, the missing packet and other quarters are inaccessible.
    class GuardedUnit(dict):
        def __getitem__(self, key):
            if key not in self:
                raise ValueError(f"read outside the five surviving inputs: {key}")
            return super().__getitem__(key)

    if POSSIBLE != [28]:
        raise ValueError("physical layout differs from the declared geometry")
    counter, slot = 17, 28
    _, _, cells = next(t for t in TRIALS if t[0] == slot)
    units = [GuardedUnit() for _ in range(3)]
    for (phase, offset), value in zip(cells, (0x74, 0x74, 0x74, 0xa5, 0xa5), strict=True):
        units[phase][offset] = value
    expected = [[counter, slot, 0xa5]]
    if forecasts({counter: units}) != expected:
        raise ValueError("surviving input control")
    for index in (1, 4):
        phase, off = cells[index]
        units[phase][off] ^= 1
        if forecasts({counter: units}):
            raise ValueError("different modes or donors should abstain")
        units[phase][off] ^= 1
    # Score two different original target labels against the identical issued forecast.
    phase, off = address(slot, "p5")
    for target in (0, 0xa5):
        full = [dict(x) for x in units]
        full[phase][off] = target
        if forecasts({counter: full}) != expected:
            raise ValueError("forecast depends on the withheld packet")
        if summary({counter: full}, expected, score=True)["total"]["exact"] != int(target == 0xa5):
            raise ValueError("wrong synthetic score")
    return dict(guarded_five_octets=True, different_modes_abstain=True, different_donors_abstain=True,
                two_original_labels_same_forecast=True, exact_scores=[0, 1])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("development")
    commands.add_parser("controls")
    for name in ("predict", "score"):
        sub = commands.add_parser(name)
        sub.add_argument("--msc", type=Path, required=True)
        if name == "score":
            sub.add_argument("--predictions", type=Path, required=True)
            sub.add_argument("--sha256", required=True, help="previously sealed predictions file SHA-256")
    args = parser.parse_args()
    if args.command == "controls":
        result = controls()
    elif args.command == "development":
        if sha256(MEMBER.read_bytes()).hexdigest() != MEMBER_SHA:
            parser.error("development archive differs from published source")
        groups = complete_dus(MEMBER)
        issued = forecasts(groups)
        result = dict(source=MEMBER.name, source_sha256=MEMBER_SHA, complete_groups=len(groups),
                      centers=[s for s, _, _ in TRIALS], physically_possible_centers=POSSIBLE,
                      scores=summary(groups, issued, score=True), synthetic_controls=controls())
    else:
        if args.command == "score":
            sealed = args.predictions.read_bytes()
            if sha256(sealed).hexdigest() != args.sha256:
                parser.error("forecasts fail the supplied SHA-256")
        groups, result = decision_file(args.msc.read_bytes())
        if args.command == "score":
            if json.loads(sealed) != result:
                parser.error("sealed forecasts, source, or coordinates differ from reproducible predictions")
            result = dict(original_msc_sha256=result["original_msc_sha256"], predictions_sha256=args.sha256,
                          complete_groups=len(groups), **summary_with_primary(groups, result["predictions"], result["primary"]))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
