"""Check CS8 tuning, antialias filtering and continuity across input blocks."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import numpy as np
from scipy.signal import resample_poly
import soundfile as sf

from resample_iq import convert_cs8


class Cs8Test(unittest.TestCase):
    def test_tuned_912k_capture(self):
        rate, target, offset = 912000, 48000, 120000
        t = np.arange(610007) / rate
        # Wanted signal is in the lower sideband. The upper tone must be filtered
        # before decimation, as it would alias into the selected channel.
        iq = (.38 * np.exp(2j*np.pi*(offset - 1225)*t)
              + .48 * np.exp(2j*np.pi*(offset + 55000)*t))
        raw = np.rint(128*np.column_stack((iq.real, iq.imag))).astype(np.int8)
        with tempfile.TemporaryDirectory() as directory:
            src, out = (Path(directory) / name for name in ('test.cs8', 'test.wav'))
            raw.tofile(src)
            subprocess.run([sys.executable, str(Path(__file__).with_name('resample_iq.py')),
                            str(src), str(out), '--sample-rate', str(rate),
                            '--offset-hz', str(offset)], check=True, capture_output=True)
            result, freq = sf.read(out)
        self.assertEqual(freq, target)
        baseband = (raw[:, 0].astype(float) + 1j*raw[:, 1]) / 128 * np.exp(-2j*np.pi*offset*t)
        expected = resample_poly(baseband, 1, 19)
        actual = result[:, 0] + 1j*result[:, 1]
        self.assertEqual(actual.shape, expected.shape)
        np.testing.assert_allclose(actual, expected, atol=5e-5)
        wanted = .38 * np.exp(-2j*np.pi*1225*np.arange(len(actual))/target)
        self.assertLess(np.max(np.abs((actual-wanted)[128:-128])), .01)

    def test_tuning_in_a_bounded_window(self):
        rate, offset = 912000, 81000
        start, length = 137, 13129
        t = np.arange(start + length + 3) / rate
        tone = .6 * np.exp(2j*np.pi*(offset - 1537)*t)
        raw = np.rint(128*np.column_stack((tone.real, tone.imag))).astype(np.int8)
        with tempfile.TemporaryDirectory() as directory:
            src, out = (Path(directory) / name for name in ('window.cs8', 'window.wav'))
            raw.tofile(src)
            convert_cs8(src, out, rate, 12000, offset, start, length)
            y, _ = sf.read(out)
        iq = (raw[:, 0].astype(float) + 1j*raw[:, 1])/128 * np.exp(-2j*np.pi*offset*t)
        expected = resample_poly(iq[start:start + length], 1, 76)
        np.testing.assert_allclose(y[:, 0] + 1j*y[:, 1], expected, atol=5e-5)

    def test_incomplete_pair(self):
        with tempfile.TemporaryDirectory() as directory:
            src = Path(directory) / 'test.cs8'
            src.write_bytes(b'123')
            with self.assertRaisesRegex(ValueError, 'complete signed I,Q pairs'):
                convert_cs8(src, src.with_suffix('.wav'), 912000, 12000, 0.)


if __name__ == '__main__':
    unittest.main()
