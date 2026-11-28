"""Fit, seal, and score one complete directly carried EVS byte in native CRC-valid groups."""
import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
DEV = HERE.parent / "same-6140-1232"
DEV_MSC = DEV / "yokohama-msc.bin"
DEV_SHA256 = "267261e04afc6f48ef05a547f7784feb4cc9cf39401bf518697992153bdb0c64"
MODE = 0x74
OFFSET = 4
BASELINE = 0xC0
sys.path.insert(0, str(DEV))
from native_groups import native_groups
from check_evs_origin import PROJECTED_OCTETS
from evs_gsc_fields import mode_predictions
from render_continuous import MODE_POSITIONS, PACKET_STARTS


def capture(path):
    data = path.read_bytes()
    counts, _, _, groups = native_groups(data)
    return sha256(data).hexdigest(), counts, groups


def mode_rows(groups):
    """Exclude payload bytes, including the target, from the predictor's input."""
    for counter, triple in groups.items():
        for phase, unit in enumerate(triple):
            for index, address in enumerate(MODE_POSITIONS):
                yield counter, phase * 20 + index, unit[address]


def observed(groups, counter, slot):
    phase, index = divmod(slot, 20)
    return groups[counter][phase][PACKET_STARTS[index] + OFFSET]


def train():
    digest, counts, groups = capture(DEV_MSC)
    if digest != DEV_SHA256:
        raise ValueError("development MSC hash mismatch")
    if OFFSET + 1 not in PROJECTED_OCTETS or ("inactive_nibble", 12) not in mode_predictions(MODE):
        raise ValueError("unexpected EVS direct octet or GSC field definition")
    hist = Counter(observed(groups, counter, slot) for counter, slot, mode in mode_rows(groups) if mode == MODE)
    winners = sorted(byte for byte, count in hist.items() if count == max(hist.values()))
    if not winners:
        raise ValueError("no eligible development slots")
    return dict(
        format="native-evs-p4-byte-development-v1", source="../same-6140-1232/yokohama-msc.bin",
        source_msc_sha256=digest, native_transport=counts,
        native_counters_in_file_order=list(groups), native_groups=len(groups), slots=60 * len(groups),
        exposure="Previously published 12:32 UTC 6140 kHz Yokohama development capture.",
        mode=MODE, mode_name="SWB GSC INACTIVE with frequency-domain bandwidth extension",
        payload_offset_excluding_mode=OFFSET, word_bits_half_open=[40, 48],
        eligible=sum(hist.values()), byte_hex_counts={f"{b:02X}": hist[b] for b in sorted(hist)},
        tied_most_frequent_bytes=winners, tie_break="lowest unsigned byte", predicted=winners[0],
        baseline=BASELINE, baseline_matches=hist[BASELINE], fitted_matches=hist[winners[0]],
    )


def settings():
    raw = (HERE / "development.json").read_bytes()
    model = json.loads(raw)
    if model["source_msc_sha256"] != DEV_SHA256 or model["mode"] != MODE or model["baseline"] != BASELINE:
        raise ValueError("wrong development fit")
    return model, sha256(raw).hexdigest()


def decisions(rows, value):
    """Pure mode-only predictor. Every other mode is an explicit abstention in the totals."""
    return [[counter, slot // 20, slot, slot % 4 + 1, value, BASELINE]
            for counter, slot, mode in rows if mode == MODE]


def forecast(digest, groups, model, model_sha):
    counters = list(groups)
    training = set(model["native_counters_in_file_order"])
    return dict(
        format="native-evs-p4-byte-forecast-v1", source_msc_sha256=digest, development_sha256=model_sha,
        mode=MODE, payload_offset_excluding_mode=OFFSET, native_counters_in_file_order=counters,
        primary=counters[0] if counters else None, development_counter_overlap=sorted(training.intersection(counters)),
        slots=60 * len(counters), fitted_byte=model["predicted"], baseline_byte=BASELINE,
        row_fields=["counter", "phase", "slot", "position", "fitted_byte", "baseline_byte"],
        predictions=decisions(mode_rows(groups), model["predicted"]),
    )


def summarize(rows, opportunities):
    result = dict(slots=opportunities, eligible=len(rows), abstentions=opportunities - len(rows))
    for name, idx in (("fitted", 4), ("baseline", 5)):
        matches = sum(row[idx] == row[6] for row in rows)
        result[name] = dict(
            exact_bytes=matches, wrong_bytes=len(rows) - matches,
            high_nibbles=sum(row[idx] >> 4 == row[6] >> 4 for row in rows),
            low_nibbles=sum(row[idx] % 16 == row[6] % 16 for row in rows),
            exact_bits=sum(8 - (row[idx] ^ row[6]).bit_count() for row in rows),
            bits_compared=8 * len(rows),
        )
    return result


def breakdown(rows, group_count):
    return dict(total=summarize(rows, group_count * 60),
                by_position={str(p): summarize([r for r in rows if r[3] == p], group_count * 15)
                             for p in range(1, 5)})


def score(path, prediction_file, seal):
    raw = prediction_file.read_bytes()
    if sha256(raw).hexdigest() != seal.lower():
        raise ValueError("forecast SHA-256 differs from supplied seal")
    saved = json.loads(raw)
    digest, counts, groups = capture(path)
    expected = forecast(digest, groups, *settings())
    if saved != expected:
        raise ValueError("sealed forecast differs from mode-only rule, original MSC or development receipt")
    rows = [row + [observed(groups, row[0], row[2])] for row in saved["predictions"]]
    primary = saved["primary"]
    return dict(
        format="native-evs-p4-byte-score-v1", source_msc_sha256=digest, prediction_sha256=seal.lower(),
        native_transport=counts, native_groups=len(groups), mode=MODE, fitted_byte=saved["fitted_byte"],
        baseline_byte=BASELINE, development_counter_overlap=saved["development_counter_overlap"],
        primary=primary, primary_scores=breakdown([r for r in rows if r[0] == primary], int(primary is not None)),
        all_groups=breakdown(rows, len(groups)), row_fields=saved["row_fields"] + ["received_byte"],
        comparisons=rows,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("train", help="reproduce development.json using only the pinned Yokohama MSC")
    predict = commands.add_parser("predict", help="emit a sealable mode-only forecast on original native groups")
    predict.add_argument("msc", type=Path)
    compare = commands.add_parser("score", help="compare an externally sealed forecast with native transport bytes")
    compare.add_argument("msc", type=Path)
    compare.add_argument("predictions", type=Path)
    compare.add_argument("--seal", required=True, help="SHA-256 of the saved forecast, established before scoring")
    args = parser.parse_args()
    if args.command == "train":
        report = train()
    elif args.command == "predict":
        digest, _, groups = capture(args.msc)
        report = forecast(digest, groups, *settings())
    else:
        report = score(args.msc, args.predictions, args.seal)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
