"""Deterministic mono PCM for the one selected stock SWB encoder example."""
import numpy as np

RATE = 32000
ANCHOR = 5100
SAMPLES_PER_WORD = RATE // 50


def waveform():
    # Preserve the seed and draw order of the eight-recipe synthetic control.
    rng = np.random.default_rng(257506)
    time = np.arange(RATE) / RATE
    hz = np.fft.rfftfreq(RATE, 1 / RATE)
    harmonic = np.arange(1, 30)
    chunks = []

    def normalized(x):
        return x / max(1e-10, np.mean(x * x) ** 0.5)

    for second in range(103):
        white = rng.normal(size=RATE)
        spectrum = np.fft.rfft(white)
        rng.uniform(200, 1300)  # Low-band draw reserved by the original stimulus.
        high_center = rng.uniform(5500, 12000)
        rng.uniform(1200, 3700)  # Mid-band draw.
        high_width = rng.uniform(700, 1900)
        highs = normalized(np.fft.irfft(spectrum * np.exp(-0.5 * ((hz - high_center) / high_width) ** 2)))
        phase = rng.uniform(0, 2 * np.pi)
        f0 = rng.uniform(85, 290)
        slope = rng.uniform(-0.13, 0.13)
        pitch = f0 * (time + 0.5 * slope * time * time)
        pitch += rng.uniform(0.01, 0.09) * np.sin(2 * np.pi * 4 * time + phase)
        peaks = rng.uniform([350, 1100, 2100], [900, 2000, 3100])
        weights = (1 + 2.9 * np.sum(np.exp(-((harmonic[:, None] * f0 - peaks) / 210) ** 2), axis=1))
        weights /= harmonic ** 0.8
        voiced = normalized(np.sum(
            weights[:, None] * np.sin(2 * np.pi * harmonic[:, None] * pitch + phase), axis=0,
        ))
        envelope = (0.5 + 0.5 * np.sin(2 * np.pi * rng.uniform(1.8, 6.5) * time + phase))
        envelope **= rng.uniform(1, 3)
        rng.uniform(0.25, 1.1)  # Independent high-band gain draw.
        cutoff = (1800, 3300, 6500, 10000, 14000)[second % 5]
        noise = normalized(np.fft.irfft(spectrum / (1 + (hz / cutoff) ** 12)))
        mixed = voiced * envelope + (noise + 0.08 * highs) * rng.uniform(0.2, 1.0)
        samples = rng.uniform(1000, 6600) * mixed
        chunks.append(np.rint(np.clip(samples, -30000, 30000)).astype("<i2"))

    # The reference encoder sees 102 seconds of history, then the selected 60 ms.
    start = ANCHOR * SAMPLES_PER_WORD
    end = start + 3 * SAMPLES_PER_WORD
    result = np.concatenate(chunks)[:end].copy()
    onset = result[start:].astype(float)
    frequencies = np.fft.rfftfreq(len(onset), 1 / RATE)
    window = (frequencies > 1160) & (frequencies < 1620)
    response = np.ones(len(frequencies))
    response[window] = 0.04 + 3.9 * np.exp(-0.5 * ((frequencies[window] - 1575) / 50) ** 2)
    emphasized = np.fft.irfft(np.fft.rfft(onset) * response)
    gain = float.fromhex("0x1.c153bf5df9847p-1")
    mixed = gain * (onset + 0.95 * (emphasized - onset))
    result[start:] = np.rint(np.clip(mixed, -31000, 31000)).astype("<i2")
    return result.tobytes()
