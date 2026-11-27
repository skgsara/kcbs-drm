"""Conceal missing EVS frames using two synchronized KCBS receiver WAVs.

Give the fully received-frame render first, then the partial-frame listening
render. Both must start on a role-0 frame, use mono 16 kHz PCM16, and preserve
the 20 ms frame clock. The output is a listening reconstruction.
"""
import argparse
from pathlib import Path

import numpy as np
from scipy import signal
import soundfile as sf


RATE = 16000
FRAME = 320
CYCLE = 4 * FRAME


def spectrum(audio, window, hop):
    return signal.stft(audio, fs=RATE, nperseg=window, noverlap=window-hop,
                       boundary='zeros', padded=True)[2]


def waveform(spectrogram, window, hop, length):
    return signal.istft(spectrogram, fs=RATE, nperseg=window,
                        noverlap=window-hop)[1][:length]


def spectral_blend(strict, listening):
    """Combine the power and phase of the two receiver outputs."""
    a = spectrum(strict, 640, 160)
    b = spectrum(listening, 640, 160)
    magnitude = np.sqrt(0.85 * np.abs(a)**2 + 0.15 * np.abs(b)**2)
    phase = 0.85 * a + 0.15 * b
    return waveform(magnitude * phase / np.maximum(np.abs(phase), 1e-9),
                    640, 160, len(strict))


def interpolate_block(strict, listening):
    base = spectral_blend(strict, listening)
    # Analyze every 5 ms. The observed role-0 frame starts every 80 ms.
    # The 15 ms analysis position within it was selected on the Nov 19 control.
    window, hop = 960, 80
    z = spectrum(base, window, hop).T.copy()
    magnitude = np.abs(z)
    times = np.arange(len(z))
    anchors = np.unique(np.r_[0, np.arange(3, len(z), CYCLE//hop), len(z)-1])
    pair = np.searchsorted(anchors, times, side='right').clip(1, len(anchors)-1) - 1
    before, after = anchors[pair], anchors[pair+1]
    fraction = ((times-before)/(after-before))[:, None].astype('f')
    target = (1-fraction)*magnitude[before] + fraction*magnitude[after]
    phase = z/np.maximum(magnitude, 1e-8)
    return waveform((phase*target).T, window, hop, len(strict))


def interpolate(strict, listening):
    if strict.ndim != 1 or strict.shape != listening.shape:
        raise ValueError('inputs must have the same number of mono samples')
    if not len(strict) or len(strict) % FRAME:
        raise ValueError('inputs must contain a whole number of 20 ms frames')
    result = np.zeros_like(strict)
    # Bound the transform memory. A two-cycle overlap gives every interior
    # point both neighboring anchors plus the two STFT synthesis windows.
    block, overlap = 400*CYCLE, 2*CYCLE
    for start in range(0, len(strict), block):
        stop = min(start+block, len(strict))
        left, right = max(0, start-overlap), min(len(strict), stop+overlap)
        padded = max(0, 960-(right-left))
        a = np.pad(strict[left:right], (0, padded))
        b = np.pad(listening[left:right], (0, padded))
        x = interpolate_block(a, b)
        result[start:stop] = x[start-left:stop-left]
    # The receiver explicitly silences unknown groups. Preserve every aligned
    # frame that both receiver exports marked with digital silence.
    empty = (~strict.reshape(-1, FRAME).any(1) & ~listening.reshape(-1, FRAME).any(1))
    result.reshape(-1, FRAME)[empty] = 0
    return result


def read(path):
    with sf.SoundFile(path) as wav:
        if (wav.format, wav.subtype, wav.channels, wav.samplerate) != ('WAV','PCM_16',1,RATE):
            raise ValueError(f'{path} must be a 16 kHz mono PCM16 WAV')
        return wav.read(dtype='float32')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('strict', type=Path)
    parser.add_argument('listening', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    if args.output.resolve() in (args.strict.resolve(), args.listening.resolve()):
        parser.error('provide a separate output path')
    try:
        result = interpolate(read(args.strict), read(args.listening))
    except (ValueError, sf.LibsndfileError) as error:
        parser.error(str(error))
    sf.write(args.output, np.clip(result, -1., 32767/32768), RATE, subtype='PCM_16')


if __name__ == '__main__':
    main()
