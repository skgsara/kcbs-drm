"""Regression control for frame variation and decoder history on clear EVS audio."""
from pathlib import Path
import subprocess
import tempfile
import unittest

import numpy as np

from build_evs_gcc_independent import linux_command


BIN_DIR = Path(__file__).resolve().parents[1] / 'work' / 'evs_gcc_independent'
RATE = 16000
SAMPLES_PER_FRAME = 320
FRAMES_PER_GROUP = 60


@unittest.skipUnless(all((BIN_DIR / name).is_file() for name in ('EVS_cod', 'EVS_dec')),
                     'requires the optional local EVS reference encoder and decoder')
class ClearFrameControl(unittest.TestCase):
    def test_frame_variation_and_decoder_history(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pcm_file = root / 'signal.s16le'
            bitstream = root / 'signal.192'
            group_samples = FRAMES_PER_GROUP * SAMPLES_PER_FRAME
            t = np.arange(group_samples * 2) / RATE
            # A chirp and an independently changing harmonic give each frame different input.
            signal = (8500 * np.sin(2*np.pi * (180*t + 95*t*t))
                      + 2300 * np.sin(2*np.pi * (675*t + 7*t*t)))
            np.rint(signal).astype('<i2').tofile(pcm_file)
            encode = linux_command(BIN_DIR/'EVS_cod', '-q', '-no_delay_cmp', '-max_band', 'SWB',
                                   13200, 16, pcm_file, bitstream)
            subprocess.run(encode, check=True, capture_output=True, timeout=30)

            frames = np.fromfile(bitstream, '<u2').reshape(-1, 266)
            self.assertEqual(len(frames), 2 * FRAMES_PER_GROUP)
            self.assertTrue(np.all(frames[:, 0] == 0x6b21))
            self.assertTrue(np.all(frames[:, 1] == 264))
            self.assertTrue(np.isin(frames[:, 2:], [0x7f, 0x81]).all())
            group = frames[FRAMES_PER_GROUP:]
            payload = np.packbits(group[:, 2:] == 0x81, axis=1)
            role_one = payload[1::4]
            for position in (16, 19, 22, 25, 28, 31):
                with self.subTest(byte_position=position):
                    self.assertGreater(np.unique(role_one[:, position]).size, 1)

            isolated_stream = root / 'isolated.192'
            group.tofile(isolated_stream)

            def decode(stream, name):
                destination = root / name
                cmd = linux_command(BIN_DIR/'EVS_dec', '-q', '-no_delay_cmp', 16, stream, destination)
                subprocess.run(cmd, check=True, capture_output=True, timeout=30)
                return np.fromfile(destination, '<i2')

            isolated = decode(isolated_stream, 'isolated.s16le')
            continuous = decode(bitstream, 'continuous.s16le')
            repeated = decode(isolated_stream, 'repeated.s16le')
            self.assertEqual(len(isolated), group_samples)
            self.assertEqual(len(continuous), 2 * group_samples)
            np.testing.assert_array_equal(isolated, repeated)
            self.assertFalse(np.array_equal(isolated, continuous[group_samples:]))


if __name__ == '__main__':
    unittest.main()
