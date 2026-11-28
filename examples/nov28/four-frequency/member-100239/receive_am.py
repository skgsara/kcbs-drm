"""Check the submitted 6100 kHz IQ and export envelope audio on the original sample timeline."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys
import wave

import numpy as np
from scipy.signal import butter, sosfiltfilt

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from analog import RATE, demod, quality

SOURCE_SHA256 = "1ac44532df79af572e19fc87a6fb1a1b5b6410bedd13832d519ab7665d9c4ada"


def receive(source, destination):
    raw = source.read_bytes()
    if len(raw) != 300 * RATE * 8 or sha256(raw).hexdigest() != SOURCE_SHA256:
        raise ValueError("expected the submitted five-minute 6100 kHz CF32 file")
    iq = np.frombuffer(raw, dtype="<c8")
    if not np.isfinite(iq).all():
        raise ValueError("nonfinite I/Q component")

    # One-Hz bins. Track the strongest line within 100 Hz of nominal center.
    seconds = iq.reshape(-1, RATE)
    power = np.abs(np.fft.fft(seconds * np.hanning(RATE), axis=1)) ** 2
    bins = np.arange(-100, 101)
    carrier_offsets = bins[np.argmax(power[:, bins], axis=1)]
    global_bins = np.argmax(power, axis=1)
    strongest = global_bins == carrier_offsets % RATE

    channel = demod(iq)
    intervals = []
    for start, end in ((0, 126), (126, 300)):
        windows = [quality(channel, s) for s in range(start, end, 6)]
        intervals.append(dict(start_s=start, end_s=end, six_second_windows=len(windows),
                              informative_windows=sum(w["informative"] for w in windows),
                              seconds_with_global_peak_near_center=int(strongest[start:end].sum()),
                              median_carrier_offset_hz=float(np.median(carrier_offsets[start:end])),
                              median_carrier_over_sideband_bin_db=float(np.median(
                                  [w["carrier_over_sideband_bin_db"] for w in windows])),
                              exact_zero_iq=int(np.count_nonzero(seconds[start:end] == 0))))

    offset = float(np.median(carrier_offsets))
    centered = iq * np.exp((-2j * np.pi * offset / RATE) * np.arange(len(iq)))
    baseband = sosfiltfilt(butter(6, 4400, fs=RATE, output="sos"), centered)
    audio = sosfiltfilt(butter(4, (70, 3500), fs=RATE, btype="bandpass", output="sos"), abs(baseband))
    pcm = np.rint(audio * (32767 * 10 ** (-1 / 20) / np.max(abs(audio)))).astype("<i2")
    with wave.open(str(destination), "wb") as wav:
        wav.setparams((1, 2, RATE, 0, "NONE", "not compressed"))
        wav.writeframes(pcm.tobytes())
    return dict(source=source.name, source_sha256=SOURCE_SHA256, nominal_rate_hz=RATE,
                complex_samples=len(iq), wav_sha256=sha256(destination.read_bytes()).hexdigest(),
                audio_samples=len(pcm), intervals=intervals)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_cf32", type=Path)
    parser.add_argument("destination_wav", type=Path)
    args = parser.parse_args()
    print(json.dumps(receive(args.source_cf32, args.destination_wav), indent=2, allow_nan=False))
