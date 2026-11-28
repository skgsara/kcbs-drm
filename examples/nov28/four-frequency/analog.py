"""Frozen two-channel AM programme comparison for the first 90 seconds.

Pass 6100 then 3250 kHz nominally centred, stereo I/Q WAVs. Time zero is the
first sample of each file. Positive lag means a feature occurs later in the
3250 file. Lag can include a difference in file start times and receiver delay.
The 6 s training windows start at 7, 19 and 31 s. Fit offset, drift and
polarity on training alone. At 50, 63 and 76 s, score the fixed prediction
and four wrong-lag controls. A local peak is used only to check the residual.
The thresholds below define a test choice; no population error rate is known.
An inconclusive outcome includes both weak reception and different content.
"""
import argparse
import hashlib
import itertools
import json
from pathlib import Path

import numpy as np
from scipy import signal
import soundfile as sf


RATE = 12000
SPAN = 6 * RATE
TRAIN = (7, 19, 31)
TEST = (50, 63, 76)
SHIFTS = (-3, -2, 2, 3)


def demod(iq):
    base = signal.sosfilt(signal.butter(6, 4200, fs=RATE, output="sos"), iq)
    env = abs(base)
    audio_filter = signal.butter(4, [350, 2450], btype="bandpass", fs=RATE, output="sos")
    return base, env, signal.sosfilt(audio_filter, env)


def quality(channel, start):
    i = int(round(start * RATE))
    base, env, audio = [v[i:i + SPAN] for v in channel]
    f, p = signal.welch(audio, fs=RATE, nperseg=2048)
    bands = np.array([p[(f >= a) & (f < a + 525)].sum() for a in (350, 875, 1400, 1925)])
    total = max(bands.sum(), 1e-30)
    nwide = int((bands / total >= .05).sum())
    conc = float(np.convolve(p[(f >= 350) & (f < 2450)], np.ones(4), "valid").max() / total)
    f, p = signal.welch(base, fs=RATE, nperseg=2048, detrend=False, return_onesided=False)
    noise = np.median(p[(abs(f) >= 600) & (abs(f) <= 2000)])
    carrier = float(10 * np.log10(max(p[abs(f) <= 100].max(), 1e-30) / max(noise, 1e-30)))
    mod = float(np.std(audio) / max(np.mean(env), 1e-15))
    return {"informative": bool(nwide >= 3 and conc <= .35 and carrier >= 10 and mod >= .01),
            "wide_subbands": nwide, "strongest_23hz_fraction": conc,
            "carrier_over_sideband_bin_db": carrier, "audio_rms_over_envelope_mean": mod}


def correlations(ref, segment):
    """One demeaned correlation per valid starting sample of segment."""
    ref = ref - ref.mean()
    n = len(ref)
    y = segment - segment.mean()
    sums = np.r_[0., np.cumsum(y)]
    squares = np.r_[0., np.cumsum(y*y)]
    energy = squares[n:] - squares[:-n] - (sums[n:] - sums[:-n])**2 / n
    denominator = np.sqrt(max(np.dot(ref, ref), 1e-25) * np.maximum(energy, 1e-25))
    return np.clip(signal.correlate(y, ref, mode="valid", method="fft") / denominator, -1, 1)


def peak(ref, y, start, center, radius, polarity=None):
    lo = round((start + center - radius) * RATE)
    hi = round((start + center + radius) * RATE)
    cc = correlations(ref, y[lo:hi + len(ref)])
    ranked = abs(cc) if polarity is None else polarity * cc
    k = int(ranked.argmax())
    lag = (lo + k) / RATE - start
    return lag, float(cc[k]), cc, k


def train(a, b):
    rows = []
    for start in TRAIN:
        x = a[2][start*RATE:start*RATE + SPAN]
        lag, corr, cc, k = peak(x, b[2], start, 0, 4)
        outside = abs(np.arange(len(cc)) - k) > .1 * RATE
        advantage = abs(corr) - float(abs(cc[outside]).max())
        qa, qb = quality(a, start), quality(b, start + lag)
        rows.append(dict(start_s=start, measured_lag_s=lag, signed_correlation=corr,
                         peak_advantage=advantage, quality_6100=qa, quality_3250=qb,
                         eligible=bool(qa["informative"] and qb["informative"]
                                       and abs(corr) >= .30 and advantage >= .10)))
    eligible = [r for r in rows if r["eligible"]]
    for size in (3, 2):
        combos = sorted(itertools.combinations(eligible, size),
                        key=lambda c: -min(abs(r["signed_correlation"]) for r in c))
        for subset in combos:
            signs = {int(np.sign(r["signed_correlation"])) for r in subset}
            centers = np.array([r["start_s"] + 3 for r in subset])
            lags = [r["measured_lag_s"] for r in subset]
            slope, offset = np.polyfit(centers, lags, 1)
            residual = max(abs(np.array(lags) - (offset + slope*centers)))
            if len(signs) == 1 and abs(slope) <= 150e-6 and residual <= .003:
                return rows, dict(offset_s=float(offset), drift_ppm=float(slope*1e6),
                                  polarity=signs.pop(), train_starts_s=[r["start_s"] for r in subset])
    return rows, None


def fixed_score(x, y, start, model, shift):
    t = start + np.arange(len(x)) / RATE
    idx = RATE * (t + model["offset_s"] + t * model["drift_ppm"] / 1e6 + shift)
    lo, hi = int(np.floor(idx[0])), int(np.ceil(idx[-1])) + 1
    aligned = np.interp(idx-lo, np.arange(hi-lo), y[lo:hi])
    return float(correlations(x, aligned)[0])


def compare(iq6100, iq3250):
    a, b = demod(iq6100), demod(iq3250)
    training, model = train(a, b)
    result = {"decision": "inconclusive", "training": training, "model": model, "held_out": []}
    if model is None:
        result["reason"] = "training did not establish a unique repeatable lag and polarity"
        return result
    for start in TEST:
        lag = model["offset_s"] + model["drift_ppm"] / 1e6 * (start + 3)
        pol = model["polarity"]
        x = a[2][start*RATE:start*RATE + SPAN]
        raw = fixed_score(x, b[2], start, model, 0)
        wrong = {str(s): fixed_score(x, b[2], start, model, s) for s in SHIFTS}
        local, localcorr, _, _ = peak(x, b[2], start, lag, .020, pol)
        qa, qb = quality(a, start), quality(b, start + lag)
        result["held_out"].append(dict(start_s=start, predicted_lag_s=lag,
            raw_signed_correlation=raw, polarity_adjusted_correlation=pol*raw,
            wrong_shift_signed_correlations=wrong, advantage=pol*raw-max(map(abs, wrong.values())),
            residual_lag_ms=(local-lag)*1000, local_peak_signed_correlation=localcorr,
            informative=qa["informative"] and qb["informative"], quality_6100=qa, quality_3250=qb))
    rows = [r for r in result["held_out"] if r["informative"]]
    passing = sum(r["polarity_adjusted_correlation"] >= .30 and abs(r["residual_lag_ms"]) <= 5 for r in rows)
    result["informative_windows"], result["passing_windows"] = len(rows), passing
    if len(rows) >= 2 and passing >= np.ceil(2*len(rows)/3):
        if (np.median([r["polarity_adjusted_correlation"] for r in rows]) >= .40
                and np.median([r["advantage"] for r in rows]) >= .15):
            result["decision"] = "shared_modulation_supported"
    return result


def self_test():
    rng = np.random.default_rng(20261128)
    t = np.arange(90*RATE) / RATE
    bp = signal.butter(3, [400, 2300], fs=RATE, btype="bandpass", output="sos")

    def modulation():
        s = signal.sosfilt(bp, rng.standard_normal(len(t)))
        return s * (.40 / abs(s).max())

    def iq(s, hz):
        noise = .005 * (rng.standard_normal(len(t)) + 1j*rng.standard_normal(len(t)))
        return (1+s) * np.exp(2j*np.pi*hz*t) + noise

    s, delay, drift = modulation(), .43, 37e-6
    first = iq(s, 22)
    delayed = np.interp((t-delay)/(1+drift), t, s)
    results = {}
    for name, second, expected in (("same_inverted", -delayed, -1),
                                   ("same_positive", delayed, 1),
                                   ("unrelated", modulation(), None),
                                   ("tone", .2*np.sin(2*np.pi*800*t), None)):
        lhs = first if name != "tone" else iq(second, 22)
        v = compare(lhs, iq(second, -31))
        if expected is None:
            assert v["decision"] == "inconclusive", name
        else:
            m = v["model"]
            assert v["decision"] == "shared_modulation_supported" and m["polarity"] == expected, name
            assert abs(m["offset_s"]-delay) < .001 and abs(m["drift_ppm"]-drift*1e6) < 12, name
        results[name] = {"decision": v["decision"], "model": v["model"],
                         "fixed_scores": [r["polarity_adjusted_correlation"] for r in v["held_out"]]}
    return results


def read_channel(path):
    with sf.SoundFile(path) as f:
        if f.samplerate != RATE or f.channels != 2 or f.frames < 90*RATE:
            raise ValueError(f"{path.name} requires at least 90 seconds of stereo 12 kHz I/Q")
        samples = f.read(90*RATE, dtype="float64")
        if not np.isfinite(samples).all():
            raise ValueError(f"{path.name} contains nonfinite samples")
        record = {"file": path.name, "samples_in_file": f.frames, "sample_rate": RATE}
    with path.open("rb") as f:
        record["file_sha256"] = hashlib.file_digest(f, "sha256").hexdigest()
    return samples[:, 0] + 1j*samples[:, 1], record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("iq", nargs="*", type=Path, metavar="WAV")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test and not args.iq:
        result = self_test()
    elif len(args.iq) == 2 and not args.self_test:
        (a, ma), (b, mb) = map(read_channel, args.iq)
        result = compare(a, b)
        result["inputs"] = {"6100": ma, "3250": mb}
    else:
        parser.error("supply 6100.wav 3250.wav, or --self-test")
    print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
