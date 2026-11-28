"""Document the exploratory byte selection on previously received, complete broadcast groups."""
import json
from hashlib import sha256

from rule import (CENTERS, HERE, MEMBER, MODE_POSITIONS, NOV, PACKET_STARTS, breakdown,
                  complete_dus, decisions, features, labelled, octet, train)


def scan(groups):
    rows = []
    for j in range(32):
        if j % 3 == 0:
            continue
        predicted = exact = 0
        for triple in groups.values():
            modes = [octet(triple, s, MODE_POSITIONS) for s in range(60)]
            values = [octet(triple, s, PACKET_STARTS, j) for s in range(60)]
            for s in CENTERS:
                if modes[s - 1] == modes[s] == modes[s + 1] and values[s - 1] == values[s + 1]:
                    predicted += 1
                    exact += values[s] == values[s - 1]
        rows.append(dict(offset=j, predictions=predicted, exact=exact))
    return rows


if __name__ == "__main__":
    model = train()
    if json.loads((HERE / "model.json").read_bytes()) != model:
        raise ValueError("mode baseline differs from training")
    result = {}
    for label, path in (("member_3205", MEMBER), ("edogawa_6140", NOV.parent / "nov27/validation/late-payload/edogawa-data-units.npz")):
        groups = complete_dus(path)
        rows = labelled(decisions(features(groups), model), groups)
        result[label] = dict(source_sha256=sha256(path.read_bytes()).hexdigest(), groups=len(groups),
                             overlap_with_model_fit=len(set(groups) & set(model["training_counter_ids"])),
                             all_readable_offsets=scan(groups), p5=breakdown(rows, set(groups)))
    print(json.dumps(result, indent=2))
