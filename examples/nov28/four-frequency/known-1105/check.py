"""Reproduce the 11:05 UTC AM/DRM programme match on the original November 27 handoff."""
import argparse
import gzip
import hashlib
import io
import json
import struct
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

import numpy as np
from scipy.signal import fftconvolve


AM = "audio/3250-AM-12k-mono.wav"
G192 = "replay/known-first-position.192.gz"
PINS = {
    "capture.json": "64a643485cc1a1ef5852a5149f7ba7e976fec1d8a5125aaf488229f2ff770cf0",
    AM: "aba74efd3bf82bd43c52adb866880ff3f9a3600839e9e34688bf79f5e73aabda",
    G192: "e35b777d0ef1183bb0455a33f7c24fd54ea465a10d426847c645736a724e1647",
}
ORIGINAL_PCM = "61149bf53d84dd3eec6d269693bf63e2b33bb30043b926d0fe453a0a47738a21"
GRID_HZ = 100
BANDS = (200, 350, 500, 700, 950, 1250, 1650, 2150, 2800, 3400)
DRIFTS_PPM = (0, -100, 100, -200, 200)
TARGET = 43869343


def pinned(directory, name):
    data = (directory / name).read_bytes()
    if hashlib.sha256(data).hexdigest() != PINS[name]:
        raise ValueError(f"SHA-256 differs for {name}")
    return data


def supplied_slots(data):
    """Accept only the archived 264-bit P1 word or an explicit zero-length erasure."""
    offset = 0
    slot = 0
    supplied = []
    while offset < len(data):
        sync, length = struct.unpack_from("<HH", data, offset)
        offset += 4
        if (sync, length) == (0x6b21, 264) and slot % 4 == 0:
            bits = np.frombuffer(data, offset=offset, dtype="<u2", count=length)
            if not np.all((bits == 0x81) | (bits == 0x7f)):
                raise ValueError(f"invalid G.192 symbol in slot {slot}")
            supplied.append(slot)
        elif (sync, length) != (0x6b20, 0):
            raise ValueError(f"unexpected G.192 header in slot {slot}")
        offset += 2 * length
        slot += 1
    if (slot, len(supplied)) != (11700, 1545):
        raise ValueError("unexpected G.192 timeline")
    return slot, np.asarray(supplied)


def read_am(data):
    with wave.open(io.BytesIO(data)) as f:
        if (f.getframerate(), f.getnchannels(), f.getsampwidth(), f.getnframes()) != (12000, 1, 2, 2880000):
            raise ValueError("unexpected AM PCM format")
        return np.frombuffer(f.readframes(f.getnframes()), dtype="<i2").astype(float) / 32768


def decode(data, count, decoder):
    with tempfile.TemporaryDirectory() as name:
        src = Path(name) / "first.192"
        dest = Path(name) / "first.pcm"
        src.write_bytes(data)
        subprocess.run([str(decoder), "-q", "-no_delay_cmp", "16", str(src), str(dest)], check=True,
                       stdout=subprocess.DEVNULL)
        raw = dest.read_bytes()
    if len(raw) != count * 320 * 2:
        raise ValueError("stock decoder did not produce the expected 16 kHz PCM timeline")
    return np.frombuffer(raw, dtype="<i2").astype(float) / 32768, hashlib.sha256(raw).hexdigest()


def features(signal, rate, times):
    # Each 16 ms Hann window has a 2 ms margin on either side of a supplied 20 ms word.
    radius = round(rate * .008)
    offsets = np.arange(-radius, radius)
    centers = np.rint(times * rate).astype(int)
    size = 1 << (len(offsets) - 1).bit_length()
    hz = np.fft.rfftfreq(size, 1 / rate)
    result = np.empty((len(centers), len(BANDS) - 1))
    window = np.hanning(len(offsets))
    for start in range(0, len(centers), 1024):
        block = signal[centers[start:start + 1024, None] + offsets] * window
        power = abs(np.fft.rfft(block, size)) ** 2
        for j, (lo, hi) in enumerate(zip(BANDS, BANDS[1:])):
            band = power[:, (hz >= lo) & (hz < hi)]
            result[start:start + len(block), j] = np.log(band.mean(axis=1) + 1e-10)
    return result - result.mean(axis=1, keepdims=True)


def mean_pearson(left, right):
    left = left - left.mean(axis=0)
    right = right - right.mean(axis=0)
    scale = np.sqrt((left * left).sum(axis=0) * (right * right).sum(axis=0))
    return float(np.mean(np.divide((left * right).sum(axis=0), scale, out=np.zeros_like(scale),
                                   where=scale > 1e-8)))


def fit_lag(observations, ticks, reference):
    """Mean per-band Pearson at each lag, using only the supplied centers common to both files."""
    observations = observations - observations.mean(axis=0)
    reference = reference - reference.mean(axis=0)
    timeline = np.zeros((ticks.max() + 1, observations.shape[1]))
    timeline[ticks] = observations
    present = np.zeros((len(timeline), 1))
    present[ticks] = 1
    ones = np.ones((len(reference), 1))

    def correlate(a, b):
        return fftconvolve(a, b[::-1], axes=0)

    count = np.maximum(1., np.rint(correlate(ones, present)))
    qsum = correlate(ones, timeline)
    rsum = correlate(reference, present)
    covariance = correlate(reference, timeline) - qsum * rsum / count
    qvar = correlate(ones, timeline**2) - qsum**2 / count
    rvar = correlate(reference**2, present) - rsum**2 / count
    scale = np.sqrt(np.maximum(0., qvar) * np.maximum(0., rvar))
    correlations = np.divide(covariance, scale, out=np.zeros_like(covariance), where=scale > 1e-8)
    scores = correlations.mean(axis=1)
    scores[count[:, 0] < max(60, .8 * len(ticks))] = -np.inf
    best = int(np.argmax(scores))
    if not np.isfinite(scores[best]):
        raise ValueError("insufficient training overlap")
    return float(scores[best]), best - len(timeline) + 1


def ref_ticks(times, ppm):
    # The first AM feature center is at 0.01 s, i.e. array index zero.
    return np.rint(times * GRID_HZ * (1 + ppm * 1e-6)).astype(int) - 1


def evaluate(times, query, reference):
    width = times[-1] - times[0]
    train = times <= times[0] + .45 * width
    test = times >= times[0] + .55 * width
    for mask in (train, test):
        if mask.sum() < 60 or np.ptp(times[mask]) < 8:
            raise ValueError("insufficient observations or time span for a split")
    best = -np.inf
    for ppm in DRIFTS_PPM:
        score, lag = fit_lag(query[train], ref_ticks(times[train], ppm), reference)
        if score > best:
            best, best_lag, best_ppm = score, lag, ppm
    train_indices = ref_ticks(times[train], best_ppm) + best_lag
    paired_train = (train_indices >= 0) & (train_indices < len(reference))
    indices = ref_ticks(times[test], best_ppm) + best_lag
    valid = (indices >= 0) & (indices < len(reference))
    if valid.sum() < max(60, .8 * len(indices)):
        raise ValueError("insufficient matched times in held-out segment")
    left, right = query[test][valid], reference[indices[valid]]
    middle = len(left) // 2
    heldout = mean_pearson(left, right)
    halves = [mean_pearson(left[:middle], right[:middle]), mean_pearson(left[middle:], right[middle:])]
    shifts = np.unique(np.linspace(15, len(left) - 15, 199, dtype=int))
    null = np.array([mean_pearson(left, np.roll(right, k, axis=0)) for k in shifts])
    q99 = float(np.quantile(null, .99))
    threshold = max(.28, q99 + .03)
    passed = best >= .28 and heldout >= threshold and min(halves) >= .15
    return dict(lag_seconds=best_lag / GRID_HZ, drift_ppm=best_ppm, training_count=int(train.sum()),
                training_in_range=int(paired_train.sum()), training_score=best, heldout_count=len(left), heldout_score=heldout,
                heldout_half_scores=halves, cyclic_controls=len(null), cyclic_q99=q99,
                cyclic_max=float(null.max()), cyclic_at_least_observed=int((null >= heldout).sum()),
                heldout_threshold=threshold, supports_shared_programme=bool(passed))


def run(directory, decoder):
    meta = json.loads(pinned(directory, "capture.json"))
    g192 = gzip.decompress(pinned(directory, G192))
    am = read_am(pinned(directory, AM))
    count, slots = supplied_slots(g192)
    pcm, pcm_digest = decode(g192, count, decoder)
    times = (slots + .5) / 50
    query = features(pcm, 16000, times)
    reference = features(am, 12000, np.arange(1, len(am) * GRID_HZ // 12000) / GRID_HZ)
    fit = evaluate(times, query, reference)
    group = meta["drm_clock_first_complete_counter"] + slots // 60
    target = group == TARGET
    if target.sum() != 15:
        raise ValueError("expected 15 first-position observations in target group")
    other = evaluate(times[~target], query[~target], reference)
    indices = ref_ticks(times[target], other["drift_ppm"]) + round(other["lag_seconds"] * GRID_HZ)
    if np.any((indices < 0) | (indices >= len(reference))):
        raise ValueError("target lies outside the AM track at the fitted lag")
    target_score = mean_pearson(query[target], reference[indices])
    return dict(receiver_start_utc=meta["receiver_first_callback_utc"], nominal_drm_hz=meta["drm_center_hz"],
                nominal_am_hz=meta["am_center_hz"], slots=count, supplied_p1=len(slots),
                erasures_excluded=count - len(slots), stock_pcm_sha256=pcm_digest,
                same_pcm_as_reference=pcm_digest == ORIGINAL_PCM, comparison=fit,
                calibration_without_target=other, heldout_target=dict(counter=TARGET, words=int(target.sum()),
                first_g192_slot=int(slots[target][0]), last_g192_slot=int(slots[target][-1]), score=target_score))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("handoff", type=Path, help="original extracted handoff directory containing capture.json")
    parser.add_argument("--decoder", required=True, help="stock TS 26.443 EVS_dec executable or name on PATH")
    args = parser.parse_args()
    try:
        result = run(args.handoff, args.decoder)
    except (OSError, ValueError, struct.error, subprocess.CalledProcessError) as exc:
        parser.exit(2, f"{exc}\n")
    print(json.dumps(result, indent=2, allow_nan=False))
    return 0 if result["comparison"]["supports_shared_programme"] else 1


if __name__ == "__main__":
    sys.exit(main())
