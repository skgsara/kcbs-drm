import gzip
from pathlib import Path
import subprocess
import tempfile
import unittest

import numpy as np

from evs_candidates import (CandidateDecoder, DecoderError, DIAG_DTYPE, FRAME_BYTES, KEYED,
                            apply_role_mask, binary_available, encode_frames, known_mask_from_text,
                            make_frames, read_g192, role_byte_candidates, unmask_group, write_g192)

ROOT = Path(__file__).resolve().parents[1]
PROGRAMME = ROOT/'examples/nov27/programme.192.gz'
EVS_DEC = ROOT/'work/evs_gcc_independent/EVS_dec'


def programme(tmp, n=None):
    path = Path(tmp)/'programme.192'
    path.write_bytes(gzip.decompress(PROGRAMME.read_bytes()))
    frames, good = read_g192(path)
    return (frames, good) if n is None else (frames[:n], good[:n])


def random_group(seed):
    rng = np.random.default_rng(seed)
    return rng.integers(0, 256, (60, FRAME_BYTES), dtype=np.uint8), rng


class FrameHelpersTest(unittest.TestCase):
    def test_make_frames_prepends_mode_byte(self):
        payload = np.arange(64, dtype=np.uint8).reshape(2, 32)
        frames = make_frames([7, 9], payload)
        self.assertEqual(frames.shape, (2, 33))
        np.testing.assert_array_equal(frames[:, 0], [7, 9])
        np.testing.assert_array_equal(frames[:, 1:], payload)

    def test_encode_frames_records(self):
        frames = np.arange(66, dtype=np.uint8).reshape(2, 33)
        wire = encode_frames(frames, [True, False])
        self.assertEqual(len(wire), 4 + 33 + 4)
        self.assertEqual(wire[:4], bytes([0, 0, 264 & 0xff, 264 >> 8]))
        self.assertEqual(wire[4:37], frames[0].tobytes())
        self.assertEqual(wire[37:], bytes([1, 0, 0, 0]))

    def test_g192_roundtrip(self):
        frames, rng = random_group(1)
        good = rng.random(60) < 0.8
        with tempfile.TemporaryDirectory() as tmp:
            write_g192(Path(tmp)/'x.192', frames, good)
            size = (Path(tmp)/'x.192').stat().st_size
            back, back_good = read_g192(Path(tmp)/'x.192')
        self.assertEqual(size, 2 * (60 * 2 + int(good.sum()) * 264))
        np.testing.assert_array_equal(back_good, good)
        np.testing.assert_array_equal(back[good], frames[good])

    def test_apply_role_mask_touches_one_byte_of_one_role(self):
        frames, _ = random_group(2)
        out = apply_role_mask(frames, role=2, j=4, value=0x5a)
        diff = np.argwhere(out != frames)
        self.assertEqual(len(diff), 15)
        self.assertTrue(np.all(diff[:, 0] % 4 == 2))
        self.assertTrue(np.all(diff[:, 1] == 1 + KEYED[4]))
        np.testing.assert_array_equal(apply_role_mask(out, 2, 4, 0x5a), frames)

    def test_known_mask_from_text(self):
        mask, known = known_mask_from_text(np.arange(1, 17, dtype=np.uint8))
        self.assertEqual(int(known.sum()), 17)
        self.assertTrue(known[0].all() and known[1, :5].all() and not known[1, 5:].any())
        self.assertTrue(known[3, 10] and mask[3, 10] == 0)
        np.testing.assert_array_equal(mask.ravel()[:16], np.arange(1, 17))

    def test_role_byte_candidates_recovers_plaintext_at_true_value(self):
        plain, rng = random_group(3)
        mask = rng.integers(0, 256, (4, 11), dtype=np.uint8)
        mask[3, 10] = 0
        received = plain.copy()
        for r in range(4):
            for j in range(11):
                received = apply_role_mask(received, r, j, mask[r, j])
        known = np.zeros((4, 11), bool)
        known[0] = True
        known[1, :5] = True
        known[3, 10] = True
        cands, good = role_byte_candidates(received, mask, known, role=1, j=5)
        self.assertEqual(cands.shape, (256, 60, 33))
        self.assertEqual(good.shape, (256, 60))
        true = cands[mask[1, 5]]
        rows1 = np.arange(1, 60, 4)
        np.testing.assert_array_equal(true[0::4], plain[0::4])            # role 0 fully known
        np.testing.assert_array_equal(true[rows1][:, :1 + KEYED[6]], plain[rows1][:, :1 + KEYED[6]])
        # role 1 bytes j=6..10 stay masked, roles 2 and 3 are erased
        self.assertTrue(good[:, 0::4].all() and good[:, 1::4].all())
        self.assertFalse(good[:, 2::4].any() or good[:, 3::4].any())
        # candidates differ only in role-1 payload byte 15
        diff = np.argwhere((cands != cands[0]).any(0))
        self.assertTrue(np.all(diff[:, 0] % 4 == 1) and np.all(diff[:, 1] == 1 + KEYED[5]))
        np.testing.assert_array_equal(unmask_group(received, mask, np.ones((4, 11), bool)), plain)

    def test_role_byte_candidates_explicit_erasures(self):
        frames, _ = random_group(4)
        mask, known = known_mask_from_text(np.zeros(16, np.uint8))
        _, good = role_byte_candidates(frames, mask, known, role=2, j=0, erase_roles=(),
                                       values=[1, 2, 3])
        self.assertEqual(good.shape, (3, 60))
        self.assertTrue(good.all())


@unittest.skipUnless(binary_available(), 'candidate decoder not built '
                     '(python scripts/build_evs_candidate_decoder.py)')
class CandidateDecoderTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.frames, cls.good = programme(cls.tmp.name, 320)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def candidates(self, start, n, k, seed):
        rng = np.random.default_rng(seed)
        cands = np.repeat(self.frames[None, start:start + n], k, axis=0).copy()
        good = np.repeat(self.good[None, start:start + n], k, axis=0).copy()
        for c in range(1, k):
            for _ in range(12):
                i, b = rng.integers(0, n), rng.integers(0, 264)
                cands[c, i, b // 8] ^= np.uint8(1 << (7 - b % 8))
            good[c, rng.integers(0, n, 2)] = False
        return cands, good

    @unittest.skipUnless(EVS_DEC.exists(), 'reference EVS_dec not built')
    def test_feed_matches_reference_decoder(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_g192(Path(tmp)/'s.192', self.frames, self.good)
            subprocess.run([str(EVS_DEC), '-q', '-no_delay_cmp', '16', str(Path(tmp)/'s.192'),
                            str(Path(tmp)/'s.raw')], check=True, capture_output=True)
            ref = np.fromfile(Path(tmp)/'s.raw', '<i2')
        with CandidateDecoder(16000) as dec:
            a, diag = dec.feed(self.frames[:100], self.good[:100])
            b, _ = dec.feed(self.frames[100:], self.good[100:])
        np.testing.assert_array_equal(np.concatenate([a, b]).ravel(), ref)
        self.assertEqual(diag.dtype, DIAG_DTYPE)
        np.testing.assert_array_equal(diag['bfi_in'], ~self.good[:100])
        np.testing.assert_array_equal(diag['next_bit_pos'][self.good[:100]], 264)

    def test_eval_equals_fresh_decoding_and_keeps_base(self):
        split, n, k = 150, 40, 6
        cands, good = self.candidates(split, n, k, seed=5)
        with CandidateDecoder(16000, jobs=3) as dec:
            dec.feed(self.frames[:split], self.good[:split])
            res = dec.eval(cands, good)
            after, _ = dec.feed(self.frames[split:split + n], self.good[split:split + n])
            self.assertTrue((res.status == 0).all())
            self.assertEqual(res.pcm.shape, (k, n, 320))
            for c in range(k):
                dec.reset(16000)
                dec.feed(self.frames[:split], self.good[:split])
                pcm, diag = dec.feed(cands[c], good[c])
                np.testing.assert_array_equal(res.pcm[c], pcm)
                self.assertEqual(res.diag[c].tobytes(), diag.tobytes())
            np.testing.assert_array_equal(after, res.pcm[0])     # candidate 0 is the original

    def test_prefix_is_decoded_once_and_shared(self):
        cands, good = self.candidates(200, 20, 4, seed=6)
        cands[:, :7] = self.frames[200:207]
        good[:, :7] = self.good[200:207]
        with CandidateDecoder(16000, jobs=2) as dec:
            dec.feed(self.frames[:200], self.good[:200])
            res = dec.eval(cands, good)
            same = dec.eval(np.repeat(cands[:1], 3, axis=0), np.repeat(good[:1], 3, axis=0))
            light = dec.eval(cands, good, pcm=False)
        self.assertGreaterEqual(res.prefix, 7)
        self.assertEqual(same.prefix, 20)
        np.testing.assert_array_equal(same.pcm[2], res.pcm[0])
        self.assertIsNone(light.pcm)
        self.assertEqual(light.diag.tobytes(), res.diag.tobytes())

    def test_jobs_do_not_change_results(self):
        cands, good = self.candidates(100, 15, 9, seed=7)
        out = []
        for jobs in (1, 4):
            with CandidateDecoder(32000, jobs=jobs) as dec:
                dec.feed(self.frames[:100], self.good[:100])
                out.append(dec.eval(cands, good))
        np.testing.assert_array_equal(out[0].pcm, out[1].pcm)
        self.assertEqual(out[0].diag.tobytes(), out[1].diag.tobytes())

    def test_checkpoint_restore_and_info(self):
        with CandidateDecoder(16000) as dec:
            dec.feed(self.frames[:120], self.good[:120])
            dec.checkpoint('a')
            dec.feed(self.frames[200:230], self.good[200:230])
            dec.restore('a')
            restored, _ = dec.feed(self.frames[120:160], self.good[120:160])
            info = dec.info()
            self.assertEqual(info['checkpoints'], ['a'])
            self.assertEqual(info['frames_committed'], 160)
            dec.drop('a')
            self.assertEqual(dec.info()['checkpoints'], [])
            with self.assertRaises(DecoderError):
                dec.restore('a')
            dec.reset(16000)
            dec.feed(self.frames[:120], self.good[:120])
            straight, _ = dec.feed(self.frames[120:160], self.good[120:160])
        np.testing.assert_array_equal(restored, straight)

    def test_replies_over_4gib_are_rejected_before_decoding(self):
        # 4096 x 534 erased frames at 48 kHz: 2.19 M frames, about 4.3 GB of PCM + diag
        K, N = 4096, 534
        erased = bytes([1, 0, 0, 0])
        with CandidateDecoder(48000) as dec:
            dec.feed(self.frames[:50], self.good[:50])
            with self.assertRaisesRegex(DecoderError, '4 GiB'):
                dec._call(3, np.array([K, N, 0], '<u4').tobytes() + erased * (K * N))
            with self.assertRaisesRegex(DecoderError, '4 GiB'):
                dec._call(2, np.array([K * N], '<u4').tobytes() + erased * (K * N))
            light = dec.eval(np.zeros((K, 2, FRAME_BYTES), np.uint8), np.zeros((K, 2), bool), pcm=False)
            self.assertTrue((light.status == 0).all())
            self.assertEqual(dec.info()['frames_committed'], 50)    # nothing was decoded
            after, _ = dec.feed(self.frames[50:60], self.good[50:60])
            dec.reset(48000)
            dec.feed(self.frames[:50], self.good[:50])
            straight, _ = dec.feed(self.frames[50:60], self.good[50:60])
        np.testing.assert_array_equal(after, straight)

    def test_errors_keep_the_process_usable(self):
        with CandidateDecoder(16000) as dec:
            with self.assertRaises(DecoderError):
                dec.reset(44100)
            with self.assertRaises(DecoderError):
                dec._call(2, b'\x01\x00\x00\x00' + bytes([0, 0, 7, 0]))   # 7-bit frame
            with self.assertRaises(DecoderError):
                dec._call(99, b'xyz')
            pcm, _ = dec.feed(self.frames[:5], self.good[:5])
            self.assertEqual(pcm.shape, (5, 320))
            self.assertEqual(dec.output_frame, 320)
            self.assertEqual(dec.dec_delay, 37)


if __name__ == '__main__':
    unittest.main()
