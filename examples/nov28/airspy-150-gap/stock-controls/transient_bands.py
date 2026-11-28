"""Generate the 120-second transient_bands stimulus as mono 32 kHz little-endian PCM16."""
import argparse
from pathlib import Path

import numpy as np


RATE = 32000
SEED = 241668


def unit_rms(signal):
    return signal / max(1e-10, np.mean(signal * signal) ** 0.5)


def generate(output):
    rng = np.random.Generator(np.random.PCG64(SEED))
    time = np.arange(RATE) / RATE
    frequency = np.fft.rfftfreq(RATE, 1 / RATE)
    harmonics = np.arange(1, 30)

    with output.open("xb") as stream:
        for _ in range(120):
            white = rng.normal(size=RATE)
            spectrum = np.fft.rfft(white)
            low_corner = rng.uniform(200, 1300)
            high_center = rng.uniform(5500, 12000)
            low = unit_rms(np.fft.irfft(spectrum / (1 + (frequency / low_corner) ** 4)))
            mid_center = rng.uniform(1200, 3700)
            mid_filter = (np.exp(-0.5 * ((frequency - mid_center) / 900) ** 2)
                          + 0.15 * np.exp(-0.5 * ((frequency - 5000) / 1000) ** 2))
            mid = unit_rms(np.fft.irfft(spectrum * mid_filter))
            high_width = rng.uniform(700, 1900)
            high_filter = np.exp(-0.5 * ((frequency - high_center) / high_width) ** 2)
            high = unit_rms(np.fft.irfft(spectrum * high_filter))

            phase = rng.uniform(0, 2 * np.pi)
            fundamental = rng.uniform(85, 290)
            glide = rng.uniform(-0.13, 0.13)
            pitch = fundamental * (time + 0.5 * glide * time * time)
            pitch += rng.uniform(0.01, 0.09) * np.sin(2 * np.pi * 4 * time + phase)
            peaks = rng.uniform([350, 1100, 2100], [900, 2000, 3100])
            bands = np.exp(-((harmonics[:, None] * fundamental - peaks) / 210) ** 2)
            weights = (1 + 2.9 * np.sum(bands, axis=1)) / harmonics ** 0.8
            oscillators = np.sin(2 * np.pi * harmonics[:, None] * pitch + phase)
            voiced = unit_rms(np.sum(weights[:, None] * oscillators, axis=0))

            # The original eight-stimulus generator drew two envelope parameters here.
            # Keep the generator state aligned through the unused envelope.
            rng.uniform(1.8, 6.5)
            rng.uniform(1, 3)
            high_gain = rng.uniform(0.25, 1.1)
            pulse_rate = rng.uniform(3, 28)
            clock = (pulse_rate * time + phase) % 1
            attack = np.exp(-clock * rng.uniform(4, 28))
            sample = (0.3 * low + mid + high_gain * high + 0.2 * voiced) * attack + 0.04 * (white + high)
            amplitude = rng.uniform(1900, 13000)
            pcm = np.rint(np.clip(amplitude * sample, -30000, 30000)).astype("<i2")
            stream.write(pcm.tobytes())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, help="new raw PCM file")
    generate(parser.parse_args().output)
