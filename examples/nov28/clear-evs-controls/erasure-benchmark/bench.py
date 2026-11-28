"""Project public EVS conformance words, seal erasure baselines, then compare with originals."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from score import observations, read_words

TARGET = (15, 18, 21, 24, 27, 30)
ERASED = ((), TARGET, tuple(range(0, 32, 3)), tuple(range(0, 32, 3)))
METHODS = ("fields", "previous", "previous_same_mode")


def digest(data):
    return sha256(data).hexdigest()


def save(path, data, compact=False):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(data, stream, indent=None if compact else 2, separators=(",", ":") if compact else None)
        stream.write("\n")
    return digest(path.read_bytes())


def project(word, position):
    return "".join("??" if byte_index - 1 in ERASED[position] else f"{value:02x}"
                   for byte_index, value in enumerate(word))


def prepare(paths, output):
    output.mkdir(exist_ok=False, parents=True)
    reports, groups, originals = [], [], []
    if len({p.name for p in paths}) != len(paths):
        raise ValueError("duplicate source names")
    for source, path in enumerate(paths):
        words = list(read_words(path))
        report = dict(file=path.name, sha256=digest(path.read_bytes()), slots=len(words),
                      trailing_slots=len(words) % 60, bad_word_groups=[], scored_groups=0)
        for start in range(0, len(words) - 59, 60):
            block = words[start:start + 60]
            if not all(block):
                report["bad_word_groups"].append(start)
                continue
            if any(len(word) != 33 for word in block):
                raise ValueError("unexpected word length")
            coordinate = [source, start]
            groups.append([coordinate, [project(word, i % 4) for i, word in enumerate(block)]])
            targets = [bytes(word[1 + p] for p in TARGET).hex() for word in block[1::4]]
            originals.append([coordinate, digest(b"".join(block)), targets])
            report["scored_groups"] += 1
        reports.append(report)
    view_hash = save(output / "visible.json", groups, compact=True)
    save(output / "answers.json", dict(visible_sha256=view_hash, sources=reports, groups=originals), compact=True)
    print("observable file SHA-256", view_hash)


def predict(view_path, ledger_path):
    raw = view_path.read_bytes()
    predictions = []
    for coordinate, words in json.loads(raw):
        if len(words) != 60:
            raise ValueError("incomplete projected group")
        for i, word in enumerate(words):
            erasures = [p - 1 for p in range(33) if word[2*p:2*p+2] == "??"]
            if len(word) != 66 or erasures != list(ERASED[i % 4]):
                raise ValueError("unexpected observable projection")
        group_rows = []
        for slot in range(1, 60, 4):
            target_view = words[slot]
            # These named checks read outside the erased bytes. Exercise them on
            # both fill values and require the entire field reports to agree.
            zero = bytes.fromhex(target_view.replace("??", "00"))
            ones = bytes.fromhex(target_view.replace("??", "ff"))
            events = list(observations(slot, zero))
            if events != list(observations(slot, ones)):
                raise ValueError("field checker depends on the erasure fill")
            conflict = any(value not in allowed for _, value, allowed, _ in events)
            previous = bytes.fromhex(words[slot - 1])
            copied = bytes(previous[1 + p] for p in TARGET).hex()
            group_rows.append(dict(visible_conflict=conflict, previous=copied,
                                   same_mode=previous[0] == zero[0]))
        predictions.append([coordinate, group_rows])
    ledger = dict(visible_sha256=digest(raw), groups=predictions)
    print("prediction file SHA-256", save(ledger_path, ledger, compact=True))


def counts():
    return dict(groups=0, exact_groups=0, wrong_fully_called_groups=0, groups_with_abstention=0,
                words=0, exact_words=0, wrong_words=0, no_call_words=0, tied_words=0,
                visible_conflicts=0, called_bytes=0, correct_bytes=0, called_bits=0, correct_bits=0)


def score_group(rows, targets, method, result):
    correct = calls = 0
    result["groups"] += 1
    for row, original in zip(rows, targets, strict=True):
        result["words"] += 1
        if method == "fields":
            result["no_call_words"] += 1
            result["visible_conflicts" if row["visible_conflict"] else "tied_words"] += 1
            continue
        if method == "previous_same_mode" and not row["same_mode"]:
            result["no_call_words"] += 1
            continue
        predicted, expected = bytes.fromhex(row["previous"]), bytes.fromhex(original)
        if len(predicted) != 6 or len(expected) != 6:
            raise ValueError("expected six target bytes")
        calls += 1
        correct += predicted == expected
        result["exact_words" if predicted == expected else "wrong_words"] += 1
        result["called_bytes"] += 6
        result["called_bits"] += 48
        result["correct_bytes"] += sum(a == b for a, b in zip(predicted, expected))
        result["correct_bits"] += sum(8 - (a ^ b).bit_count() for a, b in zip(predicted, expected))
    kind = "groups_with_abstention" if calls < 15 else "exact_groups" if correct == 15 else "wrong_fully_called_groups"
    result[kind] += 1


def score(ledger_path, known_hash, answer_path, output):
    raw = ledger_path.read_bytes()
    if digest(raw) != known_hash:
        raise ValueError("prediction file differs from its supplied seal")
    ledger = json.loads(raw)
    answers = json.loads(answer_path.read_bytes())
    if ledger["visible_sha256"] != answers["visible_sha256"]:
        raise ValueError("predictions and originals have different projected inputs")
    sources = answers["sources"]
    for source in sources:
        source["baselines"] = {name: counts() for name in METHODS}
    seen = set()
    for (point, rows), (label_point, block_digest, targets) in zip(ledger["groups"], answers["groups"], strict=True):
        if point != label_point or len(rows) != 15 or len(targets) != 15:
            raise ValueError("prediction and answer coordinates disagree")
        seen.add(block_digest)
        for name in METHODS:
            score_group(rows, targets, name, sources[point[0]]["baselines"][name])
    totals = {name: {key: sum(source["baselines"][name][key] for source in sources)
                     for key in counts()} for name in METHODS}
    save(output, dict(visible_sha256=ledger["visible_sha256"], prediction_sha256=known_hash,
                      answers_sha256=digest(answer_path.read_bytes()), sources=sources,
                      distinct_original_groups=len(seen), totals=totals))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_subparsers(dest="action", required=True)
    p = modes.add_parser("prepare")
    p.add_argument("output", type=Path)
    p.add_argument("inputs", nargs="+", type=Path)
    p = modes.add_parser("predict")
    p.add_argument("visible", type=Path)
    p.add_argument("ledger", type=Path)
    p = modes.add_parser("score")
    p.add_argument("ledger", type=Path)
    p.add_argument("seal")
    p.add_argument("answers", type=Path)
    p.add_argument("output", type=Path)
    args = parser.parse_args()
    if args.action == "prepare":
        prepare(args.inputs, args.output)
    elif args.action == "predict":
        predict(args.visible, args.ledger)
    else:
        score(args.ledger, args.seal, args.answers, args.output)
