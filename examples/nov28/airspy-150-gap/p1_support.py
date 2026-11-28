"""Compare four fixed mode/tail pairs with earlier text-supported P1 labels."""
from hashlib import sha256
import json
from pathlib import Path
import sys


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path[:0] = [str(ROOT / "scripts"), str(ROOT / "examples/nov27/validation/hq-class"),
                str(HERE.parent / "swb-transition")]
from archived import transport
from p1_archive import predictions, scores


FROZEN = "dcbbed55b9c48c05fe8a9663ddcb198fa6e50ba0c69c492f7228a98da40cd017"
PROFILES = {"61/6C": 1, "60/B6": 0, "60/3A": 0, "61/4C": 1}


def main():
    units, origins, sources, _ = transport()
    projected = predictions(units, origins, sources)
    encoded = (json.dumps(projected, indent=2, sort_keys=True) + "\n").encode()
    if sha256(encoded).hexdigest() != FROZEN:
        raise ValueError("P1 inputs or predictions differ from the published archive")

    columns = {}
    for profile, expected in PROFILES.items():
        rows = [r for r in projected["cases"] if f"{r['mode']}/{r['p31']}" == profile]
        if any(r["allowed"] != [expected] for r in rows):
            raise ValueError(f"original predictions differ for {profile}")
        strict = scores({"cases": rows}, units, origins)["header_or_body_column"]
        n = strict["counts"]
        columns[profile] = {
            "received": len(rows),
            "labelled": n["labelled_transitions"],
            "matches": n["exact_pair_matches"],
            "example": next(iter(strict["examples"].values()), None),
            "disagreements": strict["disagreements"],
        }
    print(json.dumps(columns, indent=2))


if __name__ == "__main__":
    main()
