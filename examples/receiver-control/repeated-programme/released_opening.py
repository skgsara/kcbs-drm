"""Search a released listening WAV for a ten-second passage verified on two earlier dates."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import wave

import numpy as np
from scipy import signal

from archive_audio import RATE, band, correlation, decode, get_source, window
import spectral


RELEASE = "KCBS2_NOV25_UNVERIFIED_QUIET_17m40_32k.wav"
RELEASE_SHA = "641bc91cc896440fca731883361d41b6419c962077abde22adb99f86e4f4f97d"
QUERY_TIME = 100  # seconds after 05:00 on the November 19 filename clock
DURATION = 10
PREVIOUS_WINDOWS = (60, 90)
MIN_POWER = 10 ** (-55 / 10)


def read_release(path):
    with path.open("rb") as stream:
        digest = sha256()
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    if path.stat().st_size != 67_891_244 or digest.hexdigest() != RELEASE_SHA:
        raise ValueError("unexpected November 25 release asset")
    with wave.open(str(path), "rb") as wav:
        geometry = wav.getnchannels(), wav.getframerate(), wav.getsampwidth(), wav.getnframes()
        if geometry != (1, 32000, 2, 33_945_600) or wav.getcomptype() != "NONE":
            raise ValueError("unexpected WAV geometry")
    pcm = subprocess.check_output(["ffmpeg", "-nostdin", "-v", "error", "-xerror", "-i", str(path),
                                   "-ac", "1", "-ar", str(RATE), "-f", "s16le", "-"])
    if len(pcm) != geometry[3] // 4 * 2:
        raise ValueError("incomplete resampled release")
    samples = np.frombuffer(pcm, "<i2").astype(float) / 32768
    return samples, dict(name=RELEASE, sha256=RELEASE_SHA, bytes=path.stat().st_size, rate=32000,
                         channels=1, sample_bits=16, samples=geometry[3], mono_8k_pcm_sha256=sha256(pcm).hexdigest(),
                         url=f"https://github.com/KoryoFront/kcbs2-drm-decode/releases/download/november-quiet-review/{RELEASE}")


def search(query, audio):
    """Signed, zero-mean local normalization at every possible target sample; select by magnitude."""
    query = query - query.mean()
    n = len(query)
    sums = np.r_[0., np.cumsum(audio)]
    squares = np.r_[0., np.cumsum(audio * audio)]
    energy = squares[n:] - squares[:-n] - (sums[n:] - sums[:-n]) ** 2 / n
    good = energy >= n * MIN_POWER
    if not np.any(good):
        raise ValueError("no target windows above the RMS floor")
    products = signal.oaconvolve(audio, query[::-1], mode="valid")
    scores = np.full_like(products, np.nan)
    scores[good] = products[good] / np.sqrt((query @ query) * energy[good])
    i = int(np.nanargmax(abs(scores)))
    return dict(best_start_sample=i, best_start_s=i / RATE, r=round(float(scores[i]), 6),
                highest_signed_r=round(float(np.nanmax(scores)), 6), lowest_signed_r=round(float(np.nanmin(scores)), 6),
                possible_starts=len(good), eligible_starts=int(good.sum()))


def aligned_scores(reference, audio, alignment_sample, times):
    rows = []
    for t in times:
        i = alignment_sample + (t - QUERY_TIME) * RATE
        if i < 0 or i + DURATION * RATE > len(audio):
            rows.append(dict(nov19_s=t, target_sample=i, r=None))
            continue
        a = reference[t * RATE:(t + DURATION) * RATE]
        b = audio[i:i + len(a)]
        rows.append(dict(nov19_s=t, target_sample=i, r=correlation(a - a.mean(), b - b.mean())))
    return rows


def spectral_search(query, target, fit):
    # Use the existing 18-band statistic at every available 50 ms alignment.
    start, stop = fit
    lags = range(-start * spectral.FPS, len(target[0]) - stop * spectral.FPS + 1)
    evaluated = []
    for lag in lags:
        value = spectral.score(query, target, start, stop, lag)
        if value is not None:
            evaluated.append((value, lag))
    if not evaluated:
        raise ValueError("insufficient audible material for spectral calibration")
    best, lag = max(evaluated)
    validation = []
    for t in range(30, 150, 10):
        if start <= t < stop:
            continue
        value = spectral.score(query, target, t, t + 10, lag)
        controls = [spectral.score(query, target, t, t + 10, lag + d * spectral.FPS)
                    for d in spectral.NEGATIVES]
        available = [v for v in controls if v is not None]
        qualified = value is not None and bool(available) and value >= .30 and value >= max(available) + .10
        validation.append(dict(nov19_s=t, score=spectral.rounded(value),
                               wrong_time=[spectral.rounded(v) for v in controls], passes=qualified))
    return dict(fit_nov19_seconds=fit, evaluated_lags=len(evaluated), best_score=spectral.rounded(best),
                target_minus_query_s=lag / spectral.FPS, separate_windows=validation)


def run(directory, release, fetch):
    directory.mkdir(parents=True, exist_ok=True)
    archives, sources, features = {}, {}, {}
    for day, start in (("19", 2559), ("20", 2548)):
        path, source = get_source(day, directory, fetch)
        data, receipt = decode(path, start, 300)
        archives[day] = window(data, 0, 300)  # strip AAC reader's verification/lag margins
        samples, digest = spectral.decode(path, start)
        features[day] = spectral.features(samples)
        sources[day] = dict(source=source, decoded=receipt, spectral_input_pcm_sha256=digest)
    ref, day20 = archives["19"], archives["20"]
    query = ref[QUERY_TIME * RATE:(QUERY_TIME + DURATION) * RATE]
    # The public comparison fitted this lag on 05:00:40–05:01:00 on the two earlier days.
    day20_index = round((QUERY_TIME - 9.317375) * RATE)
    known = aligned_scores(ref, day20, day20_index, (*PREVIOUS_WINDOWS, QUERY_TIME))
    samples, provenance = read_release(release)
    features["25"] = spectral.features(samples)
    released = band(samples, 300, 3000)
    best = search(query, released)
    aligned = aligned_scores(ref, released, best["best_start_sample"], PREVIOUS_WINDOWS)
    sign = np.sign(best["r"])
    passed = sum(row["r"] is not None and sign * row["r"] >= .15 for row in aligned)

    return dict(archive_sources=sources, release=provenance, analysis_rate_hz=RATE, band_hz=[300, 3000],
                query_duration_s=DURATION, query_nov19_filename_clock="05:01:40", min_window_rms_dbfs=-55,
                nov20_fixed_lag_s=-9.317375, nov20_fixed_alignment=known,
                nov20_free_search=search(query, day20), nov25_whole_release=best,
                nov25_other_windows_at_selected_alignment=aligned,
                nov25_reversed_query_free_search=search(query[::-1], released),
                spectral_comparisons=dict(
                    scope="18-band energy changes. Search the five-minute Nov20 excerpt or the entire Nov25 release. "
                          "Time zero is 05:00 on the earlier archive filename clocks and the file start on Nov25. "
                          "The 10 s fit can select a separate instance of the recurring motif. "
                          "The 60 s fit uses the same minute as the original two-day spectral check. "
                          "Out-of-fit ten-second bins are compared at the selected lag with fixed wrong-time offsets.",
                    wrong_time_offsets_s=spectral.NEGATIVES,
                    targets={day: [spectral_search(features["19"], features[day], fit)
                                   for fit in ((90, 100), spectral.FIT)] for day in ("20", "25")}),
                descriptive_test=dict(min_query_abs_r=.30, min_same_sign_r_other_windows=.15,
                                      other_windows=len(aligned), other_windows_passing=int(passed),
                                      passed=bool(abs(best["r"]) >= .30 and passed == len(aligned))))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive_directory", type=Path)
    parser.add_argument("nov25_wav", type=Path)
    parser.add_argument("--fetch", action="store_true", help="fetch pinned ranges of missing Nov19/20 originals")
    args = parser.parse_args()
    print(json.dumps(run(args.archive_directory, args.nov25_wav, args.fetch), indent=2, allow_nan=False))
