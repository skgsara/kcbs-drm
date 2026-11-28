"""Exercise real IF through the normal demodulator entry point with artificial signals."""
from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import subprocess

import numpy as np
import soundfile as sf

from demod_iq_window import input_info, main


class RealIFTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.base = Path(directory.name)
        self.source = self.base/'mono.wav'

    def run_receiver(self, *options):
        out = self.base/'run'

        def inspect_input(command, **_):
            wav = Path(command[command.index('-f') + 1])
            self.assertEqual(sf.info(wav).subtype, 'PCM_16')
            self.receiver_pairs, self.receiver_rate = sf.read(wav, always_2d=True)
            return subprocess.CompletedProcess(command, 0)

        args = ['demod_iq_window.py', str(self.source), str(out), *options]
        with patch.object(sys, 'argv', args), patch('demod_iq_window.subprocess.run', side_effect=inspect_input), \
                redirect_stdout(io.StringIO()):
            main()
        return json.loads((out/'manifest.json').read_text())

    def test_downconversion_rejects_blocker_and_negative_image(self):
        rate, center = 96000, 24100
        t = np.arange(rate) / rate
        # Without the anti-image filter the negative-frequency copy around
        # -2*IF aliases back inside the desired band during 2:1 decimation.
        audio = (.21*np.cos(2*np.pi*(center + 3400)*t)
                 + .18*np.cos(2*np.pi*(center - 5050)*t + .4)
                 + .35*np.cos(2*np.pi*(center + 6600)*t))
        sf.write(self.source, audio, rate, subtype='PCM_24')
        start = 127  # Mixer phase refers to the WAV sample clock, including this offset.
        with patch('demod_iq_window.BLOCK_FRAMES', 723):
            r = self.run_receiver('--real-if-hz', str(center), '--start', str(start/rate), '--seconds', '.75')
        n = len(self.receiver_pairs)
        self.assertEqual((self.receiver_rate, n), (48000, 36000))
        self.assertEqual(r['real_if']['output_frame_zero_source_frame'], start)
        self.assertEqual(r['real_if']['pcm16_out_of_range_components'], 0)
        clock = start/rate + np.arange(n)/48000
        expected = .21*np.exp(2j*np.pi*3400*clock) + .18*np.exp(-2j*np.pi*5050*clock + .4j)
        got = self.receiver_pairs[:,0] + 1j*self.receiver_pairs[:,1]
        np.testing.assert_allclose(got[200:-200], expected[200:-200], rtol=0, atol=.00010)

    def test_equal_rates_still_filter_and_expose_pcm16_saturation(self):
        t = np.arange(48000)/48000
        # A floating-point WAV can exceed the integer output range. Keep the
        # gain fixed and count the affected components in the receiver receipt.
        sf.write(self.source, 1.25*np.cos(2*np.pi*6850*t), 48000, subtype='FLOAT')
        r = self.run_receiver('--real-if-hz', '6000')
        wave = 1.25*np.exp(2j*np.pi*850*t)
        pairs = np.column_stack((wave.real, wave.imag))
        reference = np.clip(pairs, -1., 32767/32768)
        np.testing.assert_allclose(self.receiver_pairs[160:-160], reference[160:-160], rtol=0, atol=.00010)
        self.assertGreater(r['real_if']['pcm16_out_of_range_components'], 1000)

    def test_rational_clock_first_and_last_sample(self):
        rate, center, count, start = 44100, 12000, 21051, 11
        t = np.arange(start + count)/rate
        sf.write(self.source, .41*np.cos(2*np.pi*(center+888)*t), rate)
        with patch('demod_iq_window.BLOCK_FRAMES', 503):
            r = self.run_receiver('--real-if-hz', str(center), '--start', str(start/rate), '--seconds', '600')
        expected_count = (count*160+146)//147
        self.assertEqual(r['sample_count'], count)
        self.assertEqual(r['real_if']['output_frames'], expected_count)
        self.assertEqual(len(self.receiver_pairs), expected_count)
        clock = start/rate + np.arange(expected_count)/48000
        got = self.receiver_pairs[:,0] + 1j*self.receiver_pairs[:,1]
        np.testing.assert_allclose(got[200:-200], .41*np.exp(2j*np.pi*888*clock[200:-200]),
                                   rtol=0, atol=.00010)

    def test_mono_requires_explicit_valid_if_and_stereo_keeps_original_path(self):
        sf.write(self.source, np.zeros(32), 48000)
        for args, message in (([], 'mono audio'), (['--real-if-hz', '0'], 'Nyquist'),
                              (['--real-if-hz', '5500'], 'Nyquist'), (['--real-if-hz', '18100'], 'Nyquist'),
                              (['--real-if-hz', 'nan'], 'Nyquist')):
            with self.subTest(args=args), patch.object(sys, 'argv', ['demod', str(self.source),
                       str(self.base/'out'), *args]), redirect_stderr(io.StringIO()) as err, \
                       self.assertRaises(SystemExit):
                main()
            self.assertIn(message, err.getvalue())
            self.assertFalse((self.base/'out').exists())
        with self.assertRaisesRegex(ValueError, 'mono PCM WAV'):
            input_info(self.base/'raw.cs8', 912000, 12000)
        sf.write(self.source, np.zeros((32,2)), 48000)
        with self.assertRaisesRegex(ValueError, 'mono uncompressed PCM WAV'):
            input_info(self.source, None, 12000)
        r = self.run_receiver()
        self.assertNotIn('real_if', r)
        self.assertEqual(self.receiver_pairs.shape, (32,2))


if __name__ == '__main__':
    unittest.main()
