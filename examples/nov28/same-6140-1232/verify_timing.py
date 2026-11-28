"""Replay the two-station RF timing measurement. Run python verify_timing.py with NumPy, SciPy and SoundFile."""
import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path

import numpy as np
from scipy.signal import correlate, resample_poly
import soundfile as sf


HERE = Path(__file__).resolve().parent
SITES = ("edogawa", "yokohama")
RATE = 12000
PIECE = 600  # 50 ms at the analysis rate
RADIUS = 960  # Search 80 ms either side of the station-clock alignment.


def checked_json(path, expected):
    data = path.read_bytes()
    if sha256(data).hexdigest() != expected:
        raise ValueError(f"Checksum mismatch in {path.name}")
    return json.loads(data)


def read_iq(folder, site, source):
    path = folder / "iq" / f"{site}-6140khz-iq48.flac"
    with sf.SoundFile(path) as recording:
        if (recording.subtype, recording.samplerate, recording.channels) != ("PCM_16", 48000, 2):
            raise ValueError(f"Unexpected IQ format in {path.name}")
        samples = recording.read(dtype="int16")
    if len(samples) != source["frames"] or sha256(samples.astype("<i2", copy=False)).hexdigest() != source["pcm_sha256"]:
        raise ValueError(f"Decoded PCM differs from the {site} source seal")
    normalized = samples.astype("float32") / 32768
    return resample_poly(normalized[:, 0] + 1j * normalized[:, 1], 1, 4)


def compare_groups(left, right):
    """Compare published native DU digests across exact or deliberately shifted counter pairs."""
    rows = []
    for counter in sorted(left.keys() & right.keys()):
        first = left[counter]["phase0_row"]
        second = right[counter]["phase0_row"]
        rows.append(dict(counter=counter, edogawa_row=first, yokohama_row=second, row_offset=second - first))
    controls = {}
    for shift in (-1, 0, 1):
        partners = [(group, right[c + shift]) for c, group in left.items() if c + shift in right]
        exact = sum(a["du_sha256"] == b["du_sha256"] for a, b in partners)
        controls[shift] = dict(exact_three_du_digests=exact, different=len(partners) - exact,
                               missing=len(left) - len(partners))

    spacing = Counter()
    for previous, current in zip(rows, rows[1:]):
        step = current["counter"] - previous["counter"]
        expected = 3 * step
        regular = all(current[key] - previous[key] == expected for key in ("edogawa_row", "yokohama_row"))
        spacing["consecutive" if step == 1 else "gapped"] += 1
        spacing["consistent_three_rows_per_counter" if regular else "inconsistent"] += 1
    return dict(shared_phase0_rows=rows, spacing_of_shared_groups=spacing,
                group_digest_comparison_by_peer_counter_shift=controls)


def peak_lag(edogawa, yokohama, start, center):
    """Average magnitudes of normalized complex correlations over eight consecutive 50-ms pieces."""
    scores = np.zeros(2 * RADIUS + 1)
    for offset in range(start, start + 8 * PIECE, PIECE):
        source = edogawa[offset:offset + PIECE]
        source = source - source.mean()
        begin = offset + center - RADIUS
        search = yokohama[begin:begin + PIECE + 2 * RADIUS]
        if len(source) != PIECE or len(search) != PIECE + 2 * RADIUS:
            raise ValueError("Timing comparison extends beyond the recorded IQ")
        # Center each sliding peer window and normalize by the energy at that lag.
        sums = np.r_[0, np.cumsum(search, dtype=np.complex128)]
        energy = np.r_[0, np.cumsum(abs(search) ** 2, dtype=float)]
        peer_energy = energy[PIECE:] - energy[:-PIECE] - abs(sums[PIECE:] - sums[:-PIECE]) ** 2 / PIECE
        magnitudes = abs(correlate(search, source, mode="valid", method="fft"))
        scores += magnitudes / np.sqrt(np.maximum(peer_energy, 1e-15) * np.vdot(source, source).real)
    index = int(np.argmax(scores))
    return index - RADIUS, float(scores[index] / 8)


def replay(folder):
    report = json.loads((folder / "comparison.json").read_bytes())
    sources = checked_json(folder / "sealed-sources.json", report["official_source_sha256"])["sources"]
    groups = []
    iq = []
    for site in SITES:
        receipt = checked_json(folder / f"{site}-native.json", report["stations"][site])
        groups.append({row["counter"]: row for row in receipt["direct_complete_groups"]})
        iq.append(read_iq(folder, site, sources[site]))
    delta_ns = sources["edogawa"]["utc_bounds_ns"][0] - sources["yokohama"]["utc_bounds_ns"][0]
    center = round(delta_ns * RATE / 1e9)
    samples = []
    for elapsed in range(4, 84, 10):
        row = {"edogawa_start_s": elapsed}
        for label, shift in (("same_epoch", 0), ("peer_plus_1_2_s", 14400)):
            lag, score = peak_lag(*iq, elapsed * RATE, center + shift)
            row[label] = dict(residual_ms=(center + lag) * 1000 / RATE - delta_ns / 1e6,
                              peak_correlation=score)
        samples.append(row)
    return dict(station_start_difference_ns_edogawa_minus_yokohama=delta_ns, **compare_groups(*groups),
                waveform_comparisons=samples,
                interpretation="Negative residual places matching modulation earlier on the Yokohama station clock. "
                               "The observed lag combines propagation, multipath, receiver delays and clock differences. "
                               "Native row indices describe decoder output order.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", type=Path, default=HERE, help="directory containing this public case")
    args = parser.parse_args()
    try:
        print(json.dumps(replay(args.case), indent=2))
    except (OSError, ValueError) as error:
        parser.exit(1, f"{error}\n")
