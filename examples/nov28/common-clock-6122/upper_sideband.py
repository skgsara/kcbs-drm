"""Check the synthetic AM programme using just its upper sideband, no DRM or carrier feed."""
import argparse
import json
import numpy as np
from scipy.signal import firwin, oaconvolve
import soundfile as sf

def measure(path):
    pairs, rate = sf.read(path)
    t = np.arange(len(pairs)) % rate / rate
    iq = pairs[:,0] + 1j * pairs[:,1]
    delta = np.arange(-600,601)
    fir = firwin(1201, 650, fs=rate, window=('kaiser', 9)) * np.exp(2j*np.pi*850*delta/rate)
    # The +200..+1500 Hz sideband relative to the synthetic AM carrier.
    upper = oaconvolve(iq * np.exp(2j*np.pi*22000*t), fir, mode='same')
    msg = .32 * np.cos(2*np.pi*500*t) + .23 * np.cos(2*np.pi*1200*t)
    use = slice(rate//10,-rate//10)
    correlation = float(np.corrcoef(upper.real[use],msg[use])[0,1])
    return dict(sideband='upper',relative_passband_hz=[200,1500],rf_offset_band_hz=[-21800,-20500],
                carrier_hz=-22000,assumed_phase_rad=0,trim_seconds_each_end=.1,
                actual_samples=int(len(msg[use])),fixed_lag_samples=0,real_component_correlation=correlation)

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('synthetic_wav')
    print(json.dumps(measure(p.parse_args().synthetic_wav),indent=2))
