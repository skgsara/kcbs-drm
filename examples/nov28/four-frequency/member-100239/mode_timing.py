"""Reproduce the frozen EVS mode-octet / AM programme-timing measurement."""
import argparse
from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import sys
import wave

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[3] / "scripts"))
from received_evs_packets import read_packet_snapshot
from render_continuous import MODE_POSITIONS


SLOTS_PER_SECOND = 50
SLOTS_PER_BIN = 10
BAND_EDGES = (200, 350, 500, 700, 950, 1250, 1650, 2150, 2800, 3400)
KNOWN_LAG = -156  # −3.12 s on the 20 ms grid of the November 27 recording.
PROTOCOL_HASH = "00c48ca7c68b66250ab3afc8edbfc56347bd6d8e9009b0c15b6c5853ec8c1d6a"
TEMPLATE_HASH = "d5a2d263902dd9aeb98ddabcc517a97b8338faba55c8e32e6b5f16a234c6010e"


def verify_hash(path, expected):
    actual = sha256(path.read_bytes()).hexdigest()
    if actual != expected:
        raise ValueError(f"{path}: expected SHA-256 {expected}, found {actual}")
    return actual


def read_modes(path, first_tick=None):
    ticks, units, present = read_packet_snapshot(path)
    if first_tick is None:
        observed = ticks[present.any(axis=1)]
        if not len(observed):
            raise ValueError("packet snapshot has no observed tick")
        first_tick = int(observed[0])
    if not len(ticks) or ticks[-1] < first_tick:
        raise ValueError("packet snapshot ends before the clock origin")
    modes = np.full(20 * (int(ticks[-1]) - first_tick + 1), -1)
    for tick, unit, flags in zip(ticks, units, present, strict=True):
        if tick >= first_tick:
            start = 20 * (int(tick) - first_tick)
            for slot, offset in enumerate(MODE_POSITIONS):
                if flags[offset // 179]:
                    modes[start + slot] = unit[offset]
    return modes, first_tick


def am_features(path):
    with wave.open(str(path), "rb") as source:
        if (source.getframerate(), source.getsampwidth(), source.getnchannels()) != (12000, 2, 1):
            raise ValueError("expected 12 kHz mono PCM16 AM audio")
        samples = np.frombuffer(source.readframes(source.getnframes()), dtype="<i2") / 32768.0
    # 40 ms windows centered at 10, 30, 50, ... ms. Discard incomplete windows.
    rate = 12000
    hop = rate // SLOTS_PER_SECOND
    width = 2 * hop
    features = np.full((len(samples) // hop, len(BAND_EDGES) - 1), np.nan)
    starts = hop * np.arange(len(features)) - hop // 2
    valid = (starts >= 0) & (starts + width <= len(samples))
    windows = np.lib.stride_tricks.sliding_window_view(samples, width)[starts[valid]]
    power = np.abs(np.fft.rfft(windows * np.hanning(width), axis=1)) ** 2
    hz = np.fft.rfftfreq(width, 1 / rate)
    bands = []
    for low, high in zip(BAND_EDGES[:-1], BAND_EDGES[1:]):
        mean_power = power[:, (hz >= low) & (hz < high)].mean(axis=1)
        bands.append(np.log(np.maximum(1e-12, mean_power)))
    log_bands = np.stack(bands, axis=1)
    features[valid] = log_bands - log_bands.mean(axis=1, keepdims=True)
    return features


def fit_templates(modes, features):
    steps = np.arange(8 * SLOTS_PER_SECOND, 98 * SLOTS_PER_SECOND)
    codes, observations = modes[steps], features[steps + KNOWN_LAG]
    keep = (codes >= 0) & np.isfinite(observations).all(axis=1)
    codes, observations = codes[keep], observations[keep]
    templates = np.full((256, observations.shape[1]), np.nan)
    counts = np.bincount(codes, minlength=256)
    for group in range(32):
        in_group = (codes >> 3) == group
        if in_group.sum() < 20:
            continue
        group_mean = observations[in_group].mean(axis=0)
        for code in range(8 * group, 8 * group + 8):
            exact = codes == code
            templates[code] = (observations[exact].sum(axis=0) + 20 * group_mean) / (counts[code] + 20)
    return templates, counts


def mean_correlation(predicted, observed):
    if not len(predicted):
        return None
    x = predicted - predicted.mean(axis=0)
    y = observed - observed.mean(axis=0)
    denominator = np.sqrt((x * x).sum(axis=0) * (y * y).sum(axis=0))
    correlations = np.divide((x * y).sum(axis=0), denominator, out=np.zeros(x.shape[1]),
                             where=denominator > 1e-16)
    return float(correlations.mean())


@dataclass
class Measurement:
    modes: np.ndarray
    templates: np.ndarray
    features: np.ndarray

    def score(self, start, end, offset, *, displacements=False):
        """Compare 200 ms bins at one offset. Both means use the same observed slots."""
        steps = np.arange(start * SLOTS_PER_SECOND, end * SLOTS_PER_SECOND)
        codes = np.full(len(steps), -1)
        in_stream = steps < len(self.modes)
        codes[in_stream] = self.modes[steps[in_stream]]
        indices = steps + offset
        valid = (codes >= 0) & (indices >= 0) & (indices < len(self.features))
        predicted = self.templates[np.maximum(codes, 0)]
        observed = self.features[np.clip(indices, 0, len(self.features) - 1)]
        valid &= np.isfinite(predicted).all(axis=1) & np.isfinite(observed).all(axis=1)

        counts = valid.reshape(-1, SLOTS_PER_BIN).sum(axis=1)
        keep = counts >= 5
        def bin_means(values):
            totals = np.where(valid[:, None], values, 0).reshape(-1, SLOTS_PER_BIN, values.shape[1]).sum(axis=1)
            return totals[keep] / counts[keep, None]

        x, y = bin_means(predicted), bin_means(observed)
        possible, used = len(keep), len(x)
        first_half = np.flatnonzero(keep) < possible / 2
        bins_per_half = [int(first_half.sum()), int((~first_half).sum())]
        halves = [mean_correlation(x[half], y[half]) for half in (first_half, ~first_half)]
        coverage = used >= max(60, np.ceil(0.65 * possible)) and min(bins_per_half) >= 25
        score = mean_correlation(x, y)
        result = dict(possible_bins=possible, used_bins=used, used_slots=int(counts[keep].sum()),
                      coverage_pass=bool(coverage), score=score, halves=halves, bins_per_half=bins_per_half)
        if displacements:
            result["pass_all"] = False
            if used >= 10:
                shifts = range(int(np.ceil(0.1 * used)), int(np.floor(0.9 * used)) + 1)
                controls = [mean_correlation(x, np.roll(y, shift, axis=0)) for shift in shifts]
                q99 = float(np.quantile(controls, 0.99))
                result.update(displacement_count=len(controls), displacement_q99=q99,
                              displacement_max=max(controls),
                              pass_all=bool(coverage and score >= 0.16 and min(halves) >= 0.08 and score >= q99 + 0.04))
        return result


def calibrate(args):
    original = json.loads((HERE / "mode-calibration.json").read_text())
    if args.first_counter * 3 != original["origin_tick"]:
        raise ValueError("clock origin differs from the November 27 reference")
    packet_hash = verify_hash(args.packets, original["old_mode_packet_archive_sha256"])
    audio_hash = verify_hash(args.am, original["am_sha256"])
    wrong_date_hash = verify_hash(args.wrong_date_am, original["wrong_date_am_sha256"])
    modes, first_tick = read_modes(args.packets, args.first_counter * 3)
    features = am_features(args.am)
    templates, counts = fit_templates(modes, features)
    with args.templates_out.open("xb") as output:
        np.save(output, templates, allow_pickle=False)
    model_hash = verify_hash(args.templates_out, TEMPLATE_HASH)
    reference = Measurement(modes, templates, features)
    wrong_date = Measurement(modes, templates, am_features(args.wrong_date_am))
    held_out = reference.score(120, 210, KNOWN_LAG, displacements=True)
    comparisons = []
    for start, end, other_start in ((120, 145, 1), (175, 200, 30)):
        other_offset = (other_start - start) * SLOTS_PER_SECOND
        comparisons.append(dict(nominal_seconds=[start, end], different_date_AM_at_second=other_start,
                                true=reference.score(start, end, KNOWN_LAG),
                                wrong_date=wrong_date.score(start, end, other_offset)))
    covered = all(item[key]["coverage_pass"] for item in comparisons for key in ("true", "wrong_date"))
    differences = [item["true"]["score"] - item["wrong_date"]["score"] for item in comparisons]
    margin = float(np.mean(differences))
    return dict(protocol_sha256=PROTOCOL_HASH, old_mode_packet_archive_sha256=packet_hash,
                am_sha256=audio_hash, wrong_date_am_sha256=wrong_date_hash, origin_tick=first_tick,
                slot_count=len(modes), received_modes=int((modes >= 0).sum()), train_mode_slots=int(counts.sum()),
                train_exact_codes=int((counts > 0).sum()),
                trained_top_five_groups=int(np.isfinite(templates).all(axis=1).sum()) // 8,
                train_code_counts={f"{i:02x}": int(n) for i, n in enumerate(counts) if n},
                frozen_templates_sha256=model_hash, known_lag_seconds=KNOWN_LAG / SLOTS_PER_SECOND,
                training=reference.score(8, 98, KNOWN_LAG), held_out=held_out, wrong_date_controls=comparisons,
                mean_true_minus_wrong_date=margin, passed=bool(held_out["pass_all"] and covered and margin >= 0.05))


def score(args):
    calibration = json.loads((HERE / "mode-calibration.json").read_text())
    if not calibration["passed"]:
        return dict(status="abstained_before_loading_new_inputs", reason="archival_positive_control_failed")
    receipt = json.loads((HERE / "mode-holdout.json").read_text())
    packet_hash = verify_hash(args.packets, receipt["source_packets_sha256"])
    audio_hash = verify_hash(args.am, receipt["source_am_sha256"])
    template_path = HERE / "mode-templates.npy"
    model_hash = verify_hash(template_path, TEMPLATE_HASH)
    modes, first_tick = read_modes(args.packets)
    study = Measurement(modes, np.load(template_path, allow_pickle=False), am_features(args.am))

    # Only the early training interval selects the lag. Prefer the smallest absolute
    # offset in an exact tie, then the more negative offset.
    trials = []
    for offset in range(-600, 601):
        training = study.score(12, 51, offset)
        if training["coverage_pass"]:
            trials.append((training["score"], -abs(offset), -offset, offset, training))
    if not trials:
        return dict(status="abstain", reason="insufficient_training_bin_coverage")
    _, _, _, offset, training = max(trials)
    training_passed = training["score"] >= 0.16 and abs(offset) <= 590
    lag = offset / SLOTS_PER_SECOND
    results = []
    for start, end in ((76, 114), (138, 201), (225, 287)):
        measured = study.score(start, end, offset, displacements=True)
        results.append(dict(nominal_time=[start, end], AM_sample_time=[start + lag, end + lag],
                            measured=measured, supports_alignment=training_passed and measured["pass_all"]))
    return dict(status="tested", origin_tick=first_tick, template_sha256=model_hash,
                source_packets_sha256=packet_hash, source_am_sha256=audio_hash,
                nominal_slot_span_s=len(modes) / SLOTS_PER_SECOND, received_modes=int((modes >= 0).sum()),
                lag_s=lag, candidate_lags=1201, training=training, training_passed=training_passed, results=results)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    old = commands.add_parser("calibrate", help="regenerate the sealed November 27 calibration")
    old.add_argument("packets", type=Path, help="11:05 receiver/packets.npz")
    old.add_argument("am", type=Path, help="11:05 audio/3250-AM-12k-mono.wav")
    old.add_argument("wrong_date_am", type=Path, help="November 19 6100 kHz control WAV")
    old.add_argument("--first-counter", type=int, required=True, help="11:05 first complete DRM counter")
    old.add_argument("--templates-out", type=Path, required=True, help="new file for regenerated NumPy templates")
    new = commands.add_parser("score", help="run the frozen test on the five-minute November 28 pair")
    new.add_argument("packets", type=Path, help="pooled 6140 kHz receiver packets.npz")
    new.add_argument("am", type=Path, help="mono 6100 kHz AM WAV from receive_am.py")
    args = parser.parse_args()
    try:
        verify_hash(HERE / "mode-protocol.md", PROTOCOL_HASH)
        result = calibrate(args) if args.action == "calibrate" else score(args)
    except (OSError, ValueError, wave.Error) as error:
        parser.exit(2, f"{parser.prog}: {error}\n")
    print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
