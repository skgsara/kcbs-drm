"""Check signed RF tuning, decimation rejection, and the original IQ sample clock."""

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import soundfile as sf

from extract_iq_channel import extract, OUTPUT_RATE


class ExtractIQTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.source = Path(temporary.name) / 'source.wav'
        self.output = Path(temporary.name) / 'channel.wav'

    def write(self, samples, rate):
        sf.write(self.source, np.column_stack((samples.real, samples.imag)), rate, subtype='FLOAT')

    def read(self):
        pairs, rate = sf.read(self.output, always_2d=True)
        self.assertEqual(rate, OUTPUT_RATE)
        self.assertEqual(sf.info(self.output).subtype, 'FLOAT')
        return pairs[:, 0] + 1j * pairs[:, 1]

    def test_tune_both_signs_and_reject_adjacent_alias(self):
        rate, n = 192000, 288001
        t = np.arange(n) / rate
        # One tone is at the declared passband edge. A blocker just beyond the
        # 6 kHz output Nyquist limit would alias into the wanted recording.
        for offset in (32000.25, -32000.25):
            with self.subTest(offset=offset):
                iq = (.3 * np.exp(2j*np.pi*(offset-5050)*t)
                      + .8 * np.exp(2j*np.pi*(offset+6100)*t)
                      + .3 * np.exp(2j*np.pi*(offset+12000+740)*t))
                self.write(iq, rate)
                with patch('extract_iq_channel.BLOCK_FRAMES', 8192):
                    extract(self.source, self.output, offset)
                actual = self.read()
                expected = .3 * np.exp(-2j*np.pi*5050*np.arange(len(actual))/OUTPUT_RATE)
                self.assertLess(np.max(np.abs(actual[40:-40]-expected[40:-40])), 0.00015)
                self.output.unlink()

    def test_rational_sample_clock_and_block_seams(self):
        rate, offset, n = 44100, -7300.5, 56917
        t = np.arange(n) / rate
        self.write(.42 * np.exp(2j*np.pi*(offset + 2100)*t), rate)
        timestamp = '2026-11-28T00:42:07.683056108Z'
        with patch('extract_iq_channel.BLOCK_FRAMES', 701):
            info = extract(self.source, self.output, offset, source_start_utc=timestamp)
        actual = self.read()
        self.assertEqual(len(actual), (n*40+146)//147)
        self.assertEqual(info['output_start_utc'], timestamp)
        self.assertEqual(info['source_frames_per_output_frame'], {'numerator':147, 'denominator':40})
        expected = .42 * np.exp(2j*np.pi*2100*np.arange(len(actual))/OUTPUT_RATE)
        self.assertLess(np.max(np.abs(actual[48:-48]-expected[48:-48])), .00008)
        self.output.unlink()
        with patch('extract_iq_channel.BLOCK_FRAMES', n+147):
            extract(self.source, self.output, offset)
        # Different mixer phase origins differ only at floating-point rounding scale.
        np.testing.assert_allclose(self.read(), actual, atol=2e-8, rtol=0)

    def test_first_sample_and_impulses_on_grid(self):
        rate, n = 192000, 32001
        samples = np.zeros(n, dtype=np.complex128)
        for i in (0, 16000, 32000):
            samples[i] = .9 + .55j
        self.write(samples, rate)
        with patch('extract_iq_channel.BLOCK_FRAMES', 16000):
            extract(self.source, self.output, 0.)
        actual = self.read()
        self.assertEqual(len(actual), 2001)
        for first, end, k in ((0,40,0),(960,1040,1000),(1960,2001,2000)):
            self.assertEqual(first+np.argmax(np.abs(actual[first:end])), k)
        np.testing.assert_allclose(actual[:25], actual[1000:1025], atol=1e-9)
        np.testing.assert_allclose(actual[-25:], actual[976:1001], atol=1e-9)

    def test_declines_existing_unsupported_and_nonfinite_inputs(self):
        self.write(np.zeros(900), 48000)
        with self.assertRaisesRegex(ValueError, 'Nyquist'):
            extract(self.source, self.output, 20000)
        self.assertFalse(self.output.exists())
        self.output.write_bytes(b'existing output')
        with self.assertRaises(FileExistsError):
            extract(self.source, self.output, 0.)
        self.assertEqual(self.output.read_bytes(), b'existing output')
        self.output.unlink()
        samples = np.zeros(900, dtype=complex)
        samples[-1] = complex(float('nan'), 0.)
        self.write(samples, 48000)
        with self.assertRaisesRegex(ValueError, 'non-finite'):
            extract(self.source, self.output, 0.)
        self.assertFalse(self.output.exists())
        # A finite 64-bit recording may still exceed the destination's range.
        sf.write(self.source, np.full((900, 2), 1e50), 48000, subtype='DOUBLE')
        with self.assertRaisesRegex(ValueError, 'float32 WAV range'):
            extract(self.source, self.output, 0.)
        self.assertFalse(self.output.exists())
        sf.write(self.source, np.zeros(20), 48000)
        with self.assertRaisesRegex(ValueError, 'stereo'):
            extract(self.source, self.output, 0.)


if __name__ == '__main__':
    unittest.main()
