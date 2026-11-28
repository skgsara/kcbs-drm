"""Synthetic checks for the end-to-end pipeline's frame assembly and fills."""
import importlib.util
import json
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
spec = importlib.util.spec_from_file_location('pfq', HERE/'partial_frame_quality.py')
pfq = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pfq)
import kcbs_decode_audio as aio
import demod_iq_window as demod
import render_continuous as continuous
from compare_evs_group import read_words


class PipelineTests(unittest.TestCase):
    def test_aggregate_cache_tracks_all_dumps_and_run_options(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            demod = root/'demod'
            demod.mkdir()
            first, second = demod/'a.bin', demod/'b.bin'
            first.write_bytes(b'one')
            second.write_bytes(b'two')
            args = SimpleNamespace(inputs=['a.wav'], phrase_keys=False, rate=16000)

            def complete(signature):
                (root/'manifest.json').write_text(json.dumps({'aggregate_inputs': signature}))
                for folder, names in {
                    'salvage': ('groups.npz', 'data_units.npz', 'report.json', 'provenance.json'),
                    'keys': ('keys.npz', 'report.json', 'segments.json', 'crc_supported_text.json'),
                    'audio': ('prior.wav',),
                }.items():
                    directory = root/folder
                    directory.mkdir(exist_ok=True)
                    for name in names:
                        (directory/name).touch()

            # A legacy, unsigned aggregate cannot certify which windows it used.
            complete(None)
            single = aio.prepare_aggregate(root, [first], args)
            self.assertFalse((root/'salvage').exists())
            self.assertEqual(len(list((root/'previous-runs').glob('*/audio/prior.wav'))), 1)
            complete(dict(single, version=1))
            self.assertEqual(aio.prepare_aggregate(root, [first], args), single)
            self.assertFalse((root/'salvage').exists())
            self.assertEqual(first.read_bytes(), b'one')
            complete(single)
            self.assertEqual(aio.prepare_aggregate(root, [first], args), single)
            self.assertTrue((root/'salvage/groups.npz').exists())

            args.inputs.append('b.wav')
            pair = aio.prepare_aggregate(root, [first, second], args)
            self.assertFalse((root/'keys').exists())
            self.assertFalse((root/'audio').exists())
            self.assertTrue(second.exists())
            complete(pair)
            second.write_bytes(b'new')  # same path and number of bytes
            changed = aio.prepare_aggregate(root, [first, second], args)
            self.assertNotEqual(pair, changed)
            self.assertFalse((root/'manifest.json').exists())
            complete(changed)
            args.rate = 32000
            self.assertNotEqual(aio.prepare_aggregate(root, [first, second], args), changed)
            self.assertFalse((root/'audio/prior.wav').exists())

    def test_dream_discovery_and_wsl_override(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve()
            source_build = root/'build/dream-src/dream'
            source_build.parent.mkdir(parents=True)
            source_build.touch()
            with patch.object(demod, '__file__', str(root/'scripts/demod_iq_window.py')), \
                 patch.object(demod, 'os') as host, \
                 patch.object(demod, 'linux', side_effect=str):
                host.name, host.environ = 'posix', {}
                self.assertEqual(demod.dream_binary(), str(source_build))
                prebuilt = root/'work/dream-build/dream'
                prebuilt.parent.mkdir(parents=True)
                prebuilt.touch()
                self.assertEqual(demod.dream_binary(), str(prebuilt))
                host.name, host.environ = 'nt', {'KCBS_DREAM': '/home/radio/special/dream'}
                self.assertEqual(demod.dream_binary(), '/home/radio/special/dream')
                host.environ = {}
                self.assertEqual(demod.dream_binary(), str(prebuilt))
                prebuilt.unlink()
                source_build.unlink()
                self.assertEqual(demod.dream_binary(), demod.WSL_LEGACY_DREAM)

    def test_packet_and_mode_positions_match_container(self):
        self.assertEqual(aio.PACKET_STARTS[:4], [7, 40, 73, 106])
        self.assertEqual(aio.MODE_POSITIONS[:4], [2, 39, 72, 105])
        for j, start in enumerate(aio.PACKET_STARTS):
            self.assertLessEqual(start + 32, 662)
            role = j % 4
            cycle = j // 4
            if role == 0:
                self.assertEqual(aio.MODE_POSITIONS[j], 2 + cycle)
            else:
                self.assertEqual(aio.MODE_POSITIONS[j], start - 1)

    def test_role_slot_alignment(self):
        slot = (np.arange(180) % 4)
        for k in range(3):
            for phase in range(3):
                for j in range(20):
                    self.assertEqual(slot[k*60 + phase*20 + j], j % 4)

    def test_fills_touch_only_unknown_bytes(self):
        rng = np.random.default_rng(3)
        frames = rng.integers(0, 256, (120, 33), dtype=np.uint8)
        slot = np.arange(120) % 4
        for name in ('role1_zeros', 'role1_random', 'role1_donor'):
            built, keep = pfq.apply_strategy(frames, name, np.random.default_rng(1), frames)
            np.testing.assert_array_equal(built[slot == 0], frames[slot == 0])
            known = [i for i in range(33) if i not in set(pfq.ROLE1_UNKNOWN.tolist())]
            np.testing.assert_array_equal(built[np.ix_(np.flatnonzero(slot == 1), known)],
                                          frames[np.ix_(np.flatnonzero(slot == 1), known)])
            self.assertTrue(keep[slot == 0].all())
            self.assertTrue(keep[slot == 1].all())
            self.assertFalse(keep[slot == 2].any())
            self.assertFalse(keep[slot == 3].any())

    def test_erase_all_supplies_only_role0(self):
        frames = np.zeros((80, 33), np.uint8)
        built, keep = pfq.apply_strategy(frames, 'erase_all', np.random.default_rng(0), frames)
        np.testing.assert_array_equal(built, frames)
        self.assertEqual(int(keep.sum()), 20)

    def test_continuous_p2_fill_preserves_direct_bytes_and_tier_b_donor(self):
        units = np.arange(2 * 3 * 716, dtype=np.uint16).astype(np.uint8).reshape(2, 3, 716)
        key = np.full(16, 2, dtype=np.uint8)
        words = []

        def capture_stream(command, **kwargs):
            words.extend(read_words(command[-2]))
            np.zeros(len(words) * 320, dtype='<i2').tofile(command[-1])
            return SimpleNamespace(returncode=0)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            np.savez(root/'groups.npz', counters=[10, 11], du=units)
            np.savez(root/'keys.npz', counters=[10], ks=key[None, :],
                     candidate_mask=np.ones((1, 16), dtype=bool))
            args = ['render_continuous.py', str(root), str(root/'keys.npz'),
                    '--out', str(root/'output'), '--rate', '16000']
            with patch.object(sys, 'argv', args), patch.object(continuous, 'linux', str), \
                    patch.object(continuous.subprocess, 'run', side_effect=capture_stream), \
                    patch('builtins.print'):
                continuous.main()

        self.assertEqual(len(words), 120)
        donor_modes, donor_payloads = continuous.group_frames(units[0], key)
        peer_modes, peer_payloads = continuous.group_frames(units[1], None)
        for slot in range(60):
            with self.subTest(slot=slot):
                role = slot % 4
                expected = donor_payloads[slot].copy()
                if role == 1:
                    # p15, p18, ..., p30 come from the immediately preceding P1.
                    expected[15::3] = donor_payloads[slot - 1, 15::3]
                keyed_word = bytes([donor_modes[slot]]) + expected.tobytes()
                self.assertEqual(words[slot], keyed_word if role < 2 else b'')

                # The later group uses the original tier-B donor at the same slot.
                peer = peer_payloads[slot].copy()
                peer[::3] = donor_payloads[slot, ::3]
                self.assertEqual(words[60 + slot], bytes([peer_modes[slot]]) + peer.tobytes())


    def test_discontinuous_runs_use_their_own_prefix(self):
        counters = np.array([10, 12], dtype=np.uint32)
        keys = np.tile(np.array([[17], [51]], dtype=np.uint8), (1, 16))
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            groups, archive = root/'groups.npz', root/'keys.npz'
            np.savez(groups, counters=counters, du=np.zeros((2, 3, 716), dtype=np.uint8))
            np.savez(archive, counters=counters, ks=keys, crc_supported=np.ones_like(keys, bool))
            streams = []

            def inspect(frames, *args):
                streams.append(frames.copy())
                return pfq.apply_strategy(frames, *args)

            def fake_decoder(*args, **kwargs):
                counter = counters[len(streams)-1]
                raw = root/'audio'/f'run_{counter}-{counter}.raw'
                np.zeros(60 * 320, dtype='<i2').tofile(raw)
                return aio.subprocess.CompletedProcess(args, 0)

            with patch.object(aio.pfq, 'apply_strategy', side_effect=inspect), \
                    patch.object(aio.subprocess, 'run', side_effect=fake_decoder):
                aio.stage_audio(groups, archive, root, 16000, 'erase_all', [])
            for frames, key in zip(streams, keys):
                np.testing.assert_array_equal(frames[0, 1 + aio.KEYED], key[:11])
                np.testing.assert_array_equal(frames[1, 1 + aio.KEYED[:5]], key[11:16])

    def test_text_stage_separates_verified_from_candidates(self):
        import json, tempfile
        from tail_fill_audit import crc
        body = ('가나다라마바사아자차카타파하' * 4)[:46]
        good = bytes([0x85, 0x2c]) + body.encode('utf-16le')
        good = good + crc(good).to_bytes(2, 'big') + bytes([0xbb]) * 16
        bad = bytearray(good)
        bad[94] ^= 1
        with tempfile.TemporaryDirectory() as td:
            keys_dir = Path(td) / 'keys'
            keys_dir.mkdir()
            (keys_dir / 'crc_supported_text.json').write_text(json.dumps([
                dict(start=300, header_ok=True, fill_ok=True, crc_ok=True,
                     plaintext_hex=good.hex(), text=body)]), encoding='utf-8')
            (keys_dir / 'segments.json').write_text(json.dumps([
                dict(start=300, header_ok=True, fill_ok=True, crc_ok=True,
                     plaintext_hex=good.hex()),
                dict(start=307, header_ok=True, fill_ok=True, crc_ok=False,
                     plaintext_hex=bytes(bad).hex())]), encoding='utf-8')
            out = Path(td) / 'out'
            out.mkdir()
            salvage = Path(td) / 'salvage'
            salvage.mkdir()
            report = aio.stage_text(keys_dir, salvage, out, [])
            self.assertEqual(report['crc_valid_text_segments'], 1)
            self.assertEqual(report['distinct_text_bodies'], 1)
            self.assertEqual(report['unverified_text_candidates'], 1)
            written = (out / 'text' / 'kcbs2_text.txt').read_text(encoding='utf-8')
            self.assertIn('counter 100 phase 0', written)
            self.assertIn('NOT VERIFIED', written)
            self.assertIn(body[:12], written)
            verified_part, candidate_part = written.split('CANDIDATE SEGMENTS THAT FAILED')
            self.assertIn('crc=False', candidate_part)
            self.assertNotIn('crc=False', verified_part)
            self.assertIn('TEXT FROM FILL-CRIB CANDIDATE KEYS', written)

    def test_montage_requires_opt_in_and_keeps_prefix_sources_separate(self):
        counters = np.array([50, 51], dtype=np.uint32)
        keys = np.zeros((2,16), dtype=np.uint8)
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            groups, archive = root/'groups.npz', root/'keys.npz'
            np.savez(groups, counters=counters, du=np.zeros((2,3,716), dtype=np.uint8))
            candidates = np.ones_like(keys, dtype=bool)
            supported = np.zeros_like(candidates)
            supported[0,0] = True
            np.savez(archive, counters=counters, ks=keys, crc_supported=supported,
                     candidate_mask=candidates)

            def silence(frames, supplied, rate, temporary):
                return np.zeros(len(frames)*(rate//50), dtype=np.int16)

            scored = (counters, keys, np.array([False, True]), np.array([0, 20]))
            with patch.object(aio, 'hangul_validated', return_value=scored) as hangul,                  patch.object(aio, 'decode_evs', side_effect=silence) as decode:
                rendered, report = aio.stage_montage(groups, archive, root, 16000, 0, False)
                self.assertEqual(rendered, [])
                self.assertEqual(report['key_source'], 'none')
                hangul.assert_not_called()
                decode.assert_not_called()
                rendered, report = aio.stage_montage(groups, archive, root, 16000, 0, True)
                self.assertEqual(report['crc_verified_key_groups'], 0)
                self.assertEqual(report['audio_key_groups'], 1)
                self.assertIn('HANGUL_CANDIDATE', rendered[0]['file'])
                self.assertEqual(report['seconds'], 2.4)

                supported[0] = True
                np.savez(archive, counters=counters, ks=keys, crc_supported=supported,
                         candidate_mask=candidates)
                hangul.reset_mock()
                rendered, report = aio.stage_montage(groups, archive, root, 16000, 0, True)
                hangul.assert_not_called()
                self.assertEqual(report['crc_verified_key_groups'], 1)
                self.assertEqual(report['audio_key_groups'], 1)
                self.assertIn('CRC_PREFIX', rendered[0]['file'])

    def test_one_line_collapses_breaks(self):
        self.assertEqual(aio._one_line('a' + chr(13) + chr(10) + 'b'), 'a / b')

    def test_merge_gap_stretch_bounds(self):
        """Stretch grouping must keep the first keyed group and not crash on singletons."""
        import importlib.util
        spec = importlib.util.spec_from_file_location('rc', HERE/'render_continuous.py')
        rc = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(rc)

        def bounds_of(offsets, gap):
            bounds, start, previous = [], offsets[0], offsets[0]
            for o in offsets[1:]:
                if o - previous > gap:
                    bounds.append((start, previous))
                    start = o
                previous = o
            bounds.append((start, previous))
            return bounds

        self.assertEqual(bounds_of([5], 4), [(5, 5)])
        self.assertEqual(bounds_of([0, 99], 4), [(0, 0), (99, 99)])
        self.assertEqual(bounds_of([0, 2, 4, 50, 52], 4), [(0, 4), (50, 52)])
        self.assertEqual(bounds_of([0, 1, 2, 3], 4), [(0, 3)])
        # Every keyed offset must fall inside some stretch.
        offsets = [0, 3, 7, 40, 41, 90]
        covered = {o for lo, hi in bounds_of(offsets, 4) for o in offsets if lo <= o <= hi}
        self.assertEqual(covered, set(offsets))

if __name__ == '__main__':
    unittest.main()
