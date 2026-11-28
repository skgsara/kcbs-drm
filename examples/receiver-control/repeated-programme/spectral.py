"""Compare 05:00–05:05 on two public audio archives using temporal changes in spectral energy."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import subprocess

import numpy as np
from scipy.signal import butter, sosfiltfilt

RATE = 8000
FPS = 20
SECONDS = 300
FIT = (60, 120)
MAX_LAG = 60
NEGATIVES = (-30, -10, -2, 2, 10, 30)


def decode(path, start):
    audio = subprocess.check_output(["ffmpeg", "-nostdin", "-v", "error", "-xerror", "-ss", str(start),
                                     "-i", str(path), "-t", str(SECONDS), "-vn", "-ac", "1", "-ar", str(RATE),
                                     "-f", "s16le", "-"])
    if len(audio) != 2 * RATE * SECONDS:
        raise ValueError("expected exactly five minutes of mono audio")
    return np.frombuffer(audio, "<i2").astype(float) / 32768, sha256(audio).hexdigest()


def features(audio):
    # Windows are centered on grid times. Reflect padding applies only at the two file ends.
    padded = np.pad(audio, (256, 256), mode="reflect")
    windows = np.lib.stride_tricks.sliding_window_view(padded, 512)[::RATE // FPS][:len(audio) * FPS // RATE]
    power = np.abs(np.fft.rfft(windows * np.hanning(512))) ** 2
    frequencies = np.fft.rfftfreq(512, 1 / RATE)
    edges = np.geomspace(180, 3400, 19)
    bands = np.stack([power[:, (frequencies >= low) & (frequencies < high)].sum(axis=1)
                      for low, high in zip(edges[:-1], edges[1:], strict=True)], axis=1)
    level = bands.sum(axis=1)
    # Gate inaudible spans relative to each recording's ordinary programme level.
    mask = level > max(1e-12, np.percentile(level, 90) * 1e-4)
    logs = np.log(np.maximum(bands, 1e-10))
    padded_logs = np.pad(logs, ((2, 2), (0, 0)), mode="edge")
    return padded_logs[4:] - padded_logs[:-4], mask


def score(source, peer, start, stop, lag):
    a, active_a = source
    b, active_b = peer
    i, j = start * FPS, stop * FPS
    # Boundary bins are missing instead of silently shortening their denominator.
    if i + lag < 0 or j + lag > len(b):
        return None
    active = active_a[i:j] & active_b[i + lag:j + lag]
    if active.sum() < max(3 * FPS, (j-i) // 4):
        return None
    left, right = a[i:j][active], b[i + lag:j + lag][active]
    left -= left.mean(axis=0)
    right -= right.mean(axis=0)
    left_rms = np.sqrt(np.mean(left * left, axis=0))
    right_rms = np.sqrt(np.mean(right * right, axis=0))
    varying = (left_rms >= 0.12) & (right_rms >= 0.12)
    if varying.sum() < 6:
        return None
    bands = np.mean(left * right, axis=0)[varying] / (left_rms[varying] * right_rms[varying])
    return float(np.mean(bands))


def rounded(value):
    return round(value, 4) if value is not None else None


def test(source, peer):
    # The fit uses one minute that both clips fully cover at every permitted lag.
    choices = []
    for lag in range(-MAX_LAG * FPS, MAX_LAG * FPS + 1):
        value = score(source, peer, *FIT, lag)
        if value is not None:
            choices.append((value, -abs(lag), -lag, lag))
    if not choices:
        return dict(lag_seconds=None, fit=None, outcome="insufficient activity in calibration")
    fit, _, _, lag = max(choices)
    # Also retain separated calibration peaks for diagnosing repeated motifs.
    peaks = []
    for candidate_score, _, _, candidate_lag in sorted(choices, reverse=True):
        if all(abs(candidate_lag - previous) >= 2 * FPS for previous, _ in peaks):
            peaks.append((candidate_lag, rounded(candidate_score)))
        if len(peaks) == 5:
            break
    rows = []
    for start in range(0, SECONDS, 10):
        value = score(source, peer, start, start + 10, lag)
        alternatives = [score(source, peer, start, start + 10, lag + n * FPS) for n in NEGATIVES]
        available = [v for v in alternatives if v is not None]
        qualified = value is not None and bool(available) and value >= 0.30 and value >= max(available) + 0.10
        rows.append(dict(start=start, fit_window=FIT[0] <= start < FIT[1], score=rounded(value),
                         wrong_time=[rounded(v) for v in alternatives], qualifies=qualified))
    return dict(lag_seconds=lag / FPS, fit=rounded(fit),
                separated_calibration_peaks=[[frame / FPS, r] for frame, r in peaks], wrong_time_lag_deltas_seconds=list(NEGATIVES),
                qualifying_held_out_bin_starts=[r["start"] for r in rows if not r["fit_window"] and r["qualifies"]],
                unavailable_held_out_bin_starts=[r["start"] for r in rows if not r["fit_window"] and r["score"] is None],
                bins=rows)


def controls(audio):
    delay = int(3.25 * RATE)
    copied = np.concatenate((np.zeros(delay), audio[:-delay]))
    copied = 0.18 * sosfiltfilt(butter(2, [260, 2500], fs=RATE, btype="bandpass", output="sos"), copied)
    # Shuffle whole 5-s fragments, preserving local tempo, spectral input and overall level.
    order = np.random.default_rng(1729).permutation(SECONDS // 5)
    shuffled = audio.reshape(-1, 5 * RATE)[order].reshape(-1)
    primary = features(audio)
    result = {}
    for name, signal in (("filtered_and_delayed_same_file", copied), ("reordered_five_second_fragments", shuffled)):
        checked = test(primary, features(signal))
        result[name] = {k: v for k, v in checked.items() if k not in ("bins", "wrong_time_lag_deltas_seconds")}
        result[name]["evaluable_held_out_bins"] = sum(not r["fit_window"] and r["score"] is not None for r in checked["bins"])
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("nov19", type=Path)
    parser.add_argument("nov20", type=Path)
    args = parser.parse_args()
    earlier, first = decode(args.nov19, 2559)
    later, second = decode(args.nov20, 2548)
    earlier_features, later_features = features(earlier), features(later)
    matched = test(earlier_features, later_features)
    # Diagnostic motivated by the independently fitted signed-waveform offset in archive_audio.py.
    waveform_lag = round(-9.317375 * FPS)
    repeat_lag = round(matched["lag_seconds"] * FPS) - waveform_lag
    diagnostics = dict(waveform_lag_on_feature_grid_seconds=waveform_lag / FPS,
                       feature_lag_difference_seconds=repeat_lag / FPS,
                       calibration_cross_at_waveform_lag=rounded(score(earlier_features, later_features, *FIT, waveform_lag)),
                       row_fields=["start", "cross_at_waveform_lag", "Nov19_vs_itself_at_lag_difference",
                                   "Nov20_vs_itself_at_lag_difference"],
                       rows=[[start, rounded(score(earlier_features, later_features, start, start + 10, waveform_lag)),
                              rounded(score(earlier_features, earlier_features, start, start + 10, repeat_lag)),
                              rounded(score(later_features, later_features, start, start + 10, repeat_lag))]
                             for start in range(0, SECONDS, 10)])
    result = dict(source_offsets_seconds=[2559, 2548], mono_8khz_pcm_sha256=[first, second], seconds=SECONDS,
                  spectral_bands=18, low_high_hz=[180, 3400], grid_seconds=1/FPS, calibration_seconds=list(FIT),
                  convention="Within the nominal 05:00 excerpts, Nov20 time equals Nov19 time plus the fitted lag.",
                  scope="Signed waveform observations on this archive pair preceded this independent feature check. "
                        "Thresholds are descriptive. Each score covers active frames of the indicated 10 s bin.",
                  feature="Bandwise Pearson correlations of 200 ms differences in log-Hann spectral power. "
                          "Average active bands. Fit one constant lag on 05:01:00–05:02:00; keep it fixed on all other bins.",
                  qualifies="At least 0.30 and 0.10 above every available forced wrong-time score.",
                  cross_day=matched, repeated_passage_diagnostic=diagnostics, controls=controls(earlier))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
