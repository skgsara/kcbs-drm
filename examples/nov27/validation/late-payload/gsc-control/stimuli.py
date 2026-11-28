"""Two independently seeded artificial reference-encoder stimuli, little-endian PCM16."""
import numpy as np

def make_pcm():
    # PCG64 seed 13200, deterministic four-stimulus alternation.
    rng = np.random.default_rng(13200)
    rate = 32000
    t = np.arange(rate) / rate
    chunks = []
    for i in range(48):
        f = (128, 165, 230, 320, 115, 145)[i % 6]
        amp = (0.5 + 0.5 * np.sin(2 * np.pi * 3.2 * t)) ** 2
        harmonic = sum(np.cos(2*np.pi*j*(f*t+0.5*(5+i%17)*t*t))/(j**0.8) for j in range(1, 80))
        noise = rng.normal(size=rate)
        sample = (harmonic*amp, 0.4*noise*amp, harmonic*0.05+0.1*noise, np.zeros(rate))[i % 4]
        chunks.append((np.clip(3500*sample, -32000, 32000)).astype("<i2"))
    return np.concatenate(chunks).tobytes()

def synthesize():
    rng = np.random.default_rng(314159)
    t = np.arange(16000) / 16000
    chunks = []
    for j in range(480):
        base = rng.uniform(90,235)
        noise = rng.normal(0,.12,len(t))
        if j % 4 in (0,1):
            wave = np.zeros_like(t)
            centers = rng.uniform([350,1200,2300], [800,2000,3200])
            for k in range(1,31):
                freq = k * base
                peak = sum(np.exp(-((freq - c)/160)**2) for c in centers)
                wave += (1+4*peak)/k * np.sin(2*np.pi*(freq*t + k*.8*np.sin(2*np.pi*2.4*t)))
            wave *= .24 + .76*np.sin(2*np.pi*rng.uniform(1.7,4.1)*t)**2
            wave += .07*noise
        elif j % 4 == 2:
            wave = (np.sin(2*np.pi*(base*t + 71*t**2))
                    + .55*np.sin(2*np.pi*(3.21*base*t + 136*t**2))
                    + .23*np.sin(2*np.pi*(6.91*base*t + 9*t**2)) + .17*noise)
        else:
            wave = (noise*.5 + np.roll(noise,1)*.35 + np.roll(noise,2)*.2)
        chunks.append(np.rint(10200*wave/np.max(np.abs(wave))).astype('<i2'))
    return np.concatenate(chunks)
