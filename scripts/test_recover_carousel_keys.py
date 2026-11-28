"""Synthetic carousel tests for the guarded text-tail key label generator."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

import recover_carousel_keys as R
from tail_fill_audit import crc
from test_text_records import make_opening

WORDS = ('평양', '신의주', '해주', '사리원', '원산', '함흥', '청진', '남포', '개성', '날씨', '기온', '바람',
         '눈이', '내리겠습니다', '흐리겠으며', '주로', '개이겠습니다', '오후부터', '새벽', '아침', '최저',
         '기상정보', '문화정보', '경제정보', '전반적지역에서', '조선동해해상', '서풍이', '불고')


def record(text, sequence, toggle, final, fill_after_final=True):
    body = text.encode('utf-16le')
    raw = bytes([(0x80 if toggle else 0) | (0x20 if final else 0) | len(body) >> 4,
                 sequence << 4 | (len(body) & 15)]) + body
    raw += crc(raw).to_bytes(2, 'big')
    raw += bytes(-len(raw) % 16)
    return raw + (b'\xbb' * 16 if not final or fill_after_final else b'')


def sentence(rng, chars):
    out = ''
    while len(out) < chars:
        out += WORDS[rng.integers(len(WORDS))] + ' '
    return out[:chars]


class Carousel:
    """A synthetic text carousel: items of an opening, two full records and a final record.

    Per-copy fields change between passes as on air: the header item toggle (so the CRC block
    too), the opening's serial bytes, and one item-metadata block.
    """

    def __init__(self, seed=7, items=5, passes=3.6, start=41, first=5000, drop=0.0):
        rng = np.random.default_rng(seed)
        self.items = [dict(title=sentence(rng, 12), texts=[sentence(rng, 46), sentence(rng, 46),
                                                           sentence(rng, int(rng.integers(4, 30)))])
                      for _ in range(items)]
        self.period = len(self.one_pass(0, rng)) // 16
        stream = b''.join(self.one_pass(k, rng) for k in range(int(np.ceil(passes)) + 1))
        n = int(passes * self.period) // 3 * 3
        self.plain = np.frombuffer(stream, np.uint8).reshape(-1, 16)[start:start + n]
        self.first = first
        self.keys = {first + g: rng.integers(0, 256, 16, dtype=np.uint8) for g in range(n // 3)}
        self.tails = {}
        for i, block in enumerate(self.plain):
            if drop and rng.random() < drop:
                continue
            t = 3 * first + i
            self.tails[t] = block ^ self.keys[t // 3]
        self.rng = rng

    def one_pass(self, k, rng):
        out = bytearray()
        for item in self.items:
            out += b'\xbb' * 16
            out += make_opening(item['title'], toggle=k % 2, per_copy=bytes(rng.integers(0, 256, 6, dtype=np.uint8)))
            for j, text in enumerate(item['texts']):
                out += record(text, j + 1, k % 2, j == len(item['texts']) - 1)
            out += bytes(rng.integers(0, 256, 16, dtype=np.uint8))
        return bytes(out)

    def subset(self, fraction, seed=3):
        rng = np.random.default_rng(seed)
        return {c: k for c, k in self.keys.items() if rng.random() < fraction}

    def corpus(self, directory):
        rows = [[dict(text=t, ok=True) for t in item['texts']] for item in self.items]
        path = Path(directory)/'items_synthetic.json'
        path.write_text(json.dumps(dict(tag='synthetic', items=rows), ensure_ascii=False), encoding='utf-8')
        titles = Path(directory)/'titles_synthetic.json'
        titles.write_text(json.dumps([dict(opening=item['title']) for item in self.items], ensure_ascii=False),
                          encoding='utf-8')
        return [path, titles]

    def data_units(self, path):
        ticks = sorted(self.tails)
        du = np.random.default_rng(11).integers(0, 256, (len(ticks), 716), dtype=np.uint8)
        for row, t in zip(du, ticks):
            row[1] = (t % 3) << 4 | (row[1] & 15)
            row[664:668] = list((t // 3).to_bytes(4, 'big'))
            row[698:714] = self.tails[t]
            row[714:716] = list(crc(bytes(row[:714])).to_bytes(2, 'big'))
        np.savez_compressed(path, counters=np.array([t // 3 for t in ticks], np.uint32),
                            phases=np.array([t % 3 for t in ticks], np.uint8), du=du)


def correct(recovered, truth):
    good = sum(np.array_equal(k, truth[c]) for c, k in recovered.items())
    return good, len(recovered) - good


class CarouselRecoveryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.car = Carousel()

    def test_seeded_run_detects_period_and_recovers_only_correct_keys(self):
        car = self.car
        seeds = car.subset(0.7)
        strict, _, _, strict_report = R.recover(car.tails, seeds, {})
        good, bad = correct({c: k for c, k in strict.items() if c not in seeds}, car.keys)
        self.assertEqual((bad, strict_report['seed_audit']['contradicted']), (0, 0))
        self.assertGreater(good, 0)                  # default: record-backed sources only
        keys, prov, rnd, report = R.recover(car.tails, seeds, {}, record_sources=False)
        self.assertEqual(report['status'], 'ok')
        self.assertEqual(report['period']['period'], car.period)
        self.assertTrue(report['period']['confirmed'])
        self.assertFalse(report['xorlink']['blocked'])
        new = {c: k for c, k in keys.items() if c not in seeds}
        self.assertGreaterEqual(len(new), good)
        good, bad = correct(new, car.keys)
        self.assertEqual(bad, 0)
        self.assertGreater(good, 0.15 * (len(car.keys) - len(seeds)))
        self.assertEqual({prov[c] for c in new}, {'xorlink'})
        _, _, _, cheaper = R.recover(car.tails, seeds, {}, rule='strict+second', record_sources=False)
        self.assertGreaterEqual(cheaper['xorlink']['links'], good)
        for entry in report['rounds']:
            self.assertEqual(set(entry['control_links'].values()), {0})

    def test_wrong_periods_yield_zero_links(self):
        car = self.car
        seeds = car.subset(0.7)
        for off in R.CONTROL_OFFSETS:
            for rule in ('strict2', 'strict+second'):
                with self.subTest(offset=off, rule=rule):
                    self.assertEqual(R.xor_link(car.tails, seeds, car.period + off, rule), {})
        self.assertGreater(len(R.xor_link(car.tails, seeds, car.period)), 0)

    def test_wrong_manual_period_is_not_confirmed_and_its_controls_block_xorlink(self):
        car = self.car
        seeds = car.subset(0.7)
        keys, prov, _, report = R.recover(car.tails, seeds, {}, period=car.period + 1)
        self.assertEqual(report['status'], 'no_confirmed_period')
        self.assertEqual(keys.keys(), seeds.keys())
        # Forced through: with the ambiguous-source filter (computed modulo the wrong period) nothing
        # links at all; without it, P+1's control at offset -1 is the true period and blocks.
        result = R.iterate(car.tails, seeds, {}, car.period + 1)
        self.assertFalse(result['blocked'])
        self.assertEqual(set(result['provenance'].values()), {'seed'})
        result = R.iterate(car.tails, seeds, {}, car.period + 1, filter_ambiguous=False, record_sources=False)
        self.assertTrue(result['blocked'])
        self.assertGreater(result['control_links']['-1'], 0)

    def test_seedless_run_with_phrase_corpus(self):
        car = self.car
        with tempfile.TemporaryDirectory() as td:
            corpus = R.build_corpus(car.corpus(td))
        proposals, _ = R.all_proposals(car.tails, corpus)
        keys, prov, rnd, report = R.recover(car.tails, {}, proposals)
        self.assertEqual(report['period']['period'], car.period)
        good, bad = correct(keys, car.keys)
        self.assertEqual(bad, 0)
        self.assertGreater(good, 0.6 * len(car.keys))
        self.assertTrue({'fill', 'phrase', 'xorlink'} <= set(prov.values()))
        self.assertFalse(report['xorlink']['blocked'])

    def test_wrong_proposals_never_pass_gate_a(self):
        car = self.car
        rng = np.random.default_rng(5)
        proposals = {c: (rng.integers(0, 256, 16, dtype=np.uint8), 'phrase') for c in car.keys}
        keys, prov, _, report = R.recover(car.tails, {}, proposals, period=car.period)
        self.assertEqual(report['status'], 'no_confirmed_period')
        self.assertEqual(keys, {})

    def test_dropped_phases_still_give_only_correct_keys(self):
        car = Carousel(seed=19, passes=4.2, drop=0.08)
        seeds = car.subset(0.75, seed=4)
        for backed in (True, False):
            with self.subTest(record_sources=backed):
                keys, _, _, report = R.recover(car.tails, seeds, {}, record_sources=backed)
                good, bad = correct({c: k for c, k in keys.items() if c not in seeds}, car.keys)
                self.assertEqual((bad, report['xorlink']['blocked']), (0, False))
        self.assertGreater(good, 0)

    def test_gate_a_requires_recurrence_at_the_same_offset_mod_period(self):
        car = self.car
        records = R.scan(car.keys, car.tails, car.first, len(car.keys))
        self.assertTrue(records)
        self.assertEqual(len(R.gate_a(records, car.period)), len(records) - sum(
            1 for r in records if sum(R.family(s, car.period) == R.family(r, car.period) for s in records) < 2))
        self.assertLess(len(R.gate_a(records, car.period + 1)), len(R.gate_a(records, car.period)) // 4)
        one_copy = [r for r in records if r.offset // 16 < car.period]
        self.assertEqual(R.gate_a(one_copy, car.period), [])

    def test_period_detection_ignores_short_repeats(self):
        car = self.car
        records = R.scan(car.keys, car.tails, car.first, len(car.keys))
        self.assertEqual(R.repeat_distances(records).most_common(1)[0][0], car.period)
        self.assertEqual(R.repeat_distances(records, min_distance=car.period + 1).get(car.period), None)


class SwapFixture:
    """Random carousel blocks repeating exactly every P, all groups trusted but one target.

    Blocks 4 apart around the target are equal (F at target-2 and target+2, A at target): at
    the wrong period P+2 the source of phase 2 is phase 0's own block, so phases 0 and 2 agree
    on the wrong key k ^ A ^ F at one displacement, and phase 0 alone reproduces it at another.
    """

    def __init__(self, period=100, passes=5, first=700):
        rng = np.random.default_rng(23)
        content = rng.integers(0, 256, (period, 16), dtype=np.uint8)
        self.target_block = 2 * period + 49                 # first block of the target group
        pos = self.target_block % period
        content[pos - 2] = content[pos + 2] = 0xBB
        plain = np.tile(content, (passes, 1))
        n = len(plain) // 3 * 3
        self.period, self.first = period, first
        self.keys = {first + g: rng.integers(0, 256, 16, dtype=np.uint8) for g in range(n // 3)}
        self.tails = {3 * first + i: plain[i] ^ self.keys[first + i // 3] for i in range(n)}
        self.target = first + self.target_block // 3
        self.wrong = self.keys[self.target] ^ content[pos] ^ content[pos - 2]
        self.trusted = {c: k for c, k in self.keys.items() if c != self.target}


class ShiftFixture:
    """Passes 0-1 carry content C; pass 2 carries C moved by two blocks (a carousel edit).

    A target in pass 2 sees every trusted copy two blocks off. With equal blocks 4 apart in C
    (fill, or any repeated value), phases 0 and 2 produce the same wrong key at both
    displacements, which strict2 alone admits; the ambiguous-source filter removes it.
    """

    def __init__(self, repeated=b'\xbb' * 16, period=90, first=400):
        rng = np.random.default_rng(29)
        content = rng.integers(0, 256, (period, 16), dtype=np.uint8)
        q0 = 45
        content[q0 - 2] = content[q0 + 2] = np.frombuffer(repeated, np.uint8)
        plain = np.vstack([content, content, np.roll(content, 2, axis=0)])
        self.period, self.first = period, first
        self.keys = {first + g: rng.integers(0, 256, 16, dtype=np.uint8) for g in range(len(plain) // 3)}
        self.tails = {3 * first + i: plain[i] ^ self.keys[first + i // 3] for i in range(len(plain))}
        self.target = first + (2 * period + q0) // 3
        self.wrong = self.keys[self.target] ^ content[q0 - 2] ^ content[q0]
        self.trusted = {c: k for c, k in self.keys.items() if 3 * (c - first) + 2 < 2 * period}


class LinkRuleTest(unittest.TestCase):
    def setUp(self):
        self.fx = SwapFixture()
        self.assertEqual(3 * self.fx.first + self.fx.target_block, 3 * self.fx.target)

    def test_phase0_phase2_swap_is_admitted_by_weaker_rules(self):
        fx = self.fx
        for rule in ('upstream', 'strict', 'strict+second'):
            with self.subTest(rule=rule):
                links = R.xor_link(fx.tails, fx.trusted, fx.period + 2, rule)
                self.assertIn(fx.target, links)
                np.testing.assert_array_equal(links[fx.target], fx.wrong)

    def test_phase0_phase2_swap_is_rejected_by_default_rule(self):
        fx = self.fx
        for off in R.CONTROL_OFFSETS:
            with self.subTest(offset=off):
                self.assertEqual(R.xor_link(fx.tails, fx.trusted, fx.period + off), {})
        links = R.xor_link(fx.tails, fx.trusted, fx.period)
        np.testing.assert_array_equal(links[fx.target], fx.keys[fx.target])

    def test_ambiguous_source_filter_rejects_the_swap_under_every_strict_rule(self):
        fx = self.fx
        ambiguous = R.ambiguous_blocks(fx.tails, fx.trusted, fx.period)
        for rule in ('strict', 'strict+second', 'strict2'):
            with self.subTest(rule=rule):
                for off in R.CONTROL_OFFSETS:
                    self.assertEqual(R.xor_link(fx.tails, fx.trusted, fx.period + off, rule,
                                                ambiguous=ambiguous), {})
                links = R.xor_link(fx.tails, fx.trusted, fx.period, rule, ambiguous=ambiguous)
                np.testing.assert_array_equal(links[fx.target], fx.keys[fx.target])

    def test_constant_shift_swap_needs_the_ambiguous_source_filter(self):
        rng = np.random.default_rng(3)
        for repeated in (b'\xbb' * 16, bytes(rng.integers(0, 256, 16, dtype=np.uint8))):
            fx = ShiftFixture(repeated)
            with self.subTest(fill=repeated == b'\xbb' * 16):
                links = R.xor_link(fx.tails, fx.trusted, fx.period, 'strict2')
                np.testing.assert_array_equal(links[fx.target], fx.wrong)
                ambiguous = R.ambiguous_blocks(fx.tails, fx.trusted, fx.period)
                self.assertIn(repeated, ambiguous)
                for rule in ('strict', 'strict+second', 'strict2'):
                    self.assertNotIn(fx.target, R.xor_link(fx.tails, fx.trusted, fx.period, rule,
                                                           ambiguous=ambiguous))
                result = R.iterate(fx.tails, fx.trusted, {}, fx.period)
                self.assertFalse(result['blocked'])
                self.assertNotIn(fx.target, result['confirmed'])

    def test_swap_with_one_sided_copies_is_rejected_by_both_second_displacement_rules(self):
        fx = self.fx
        later = fx.first + (fx.target_block + fx.period) // 3 - 2
        trusted = {c: k for c, k in fx.trusted.items() if c < later}
        self.assertIn(fx.target, R.xor_link(fx.tails, trusted, fx.period + 2, 'strict'))
        for rule in ('strict+second', 'strict2'):
            with self.subTest(rule=rule):
                self.assertNotIn(fx.target, R.xor_link(fx.tails, trusted, fx.period + 2, rule))

    def test_controls_block_a_capture_where_the_weak_rule_links_at_a_wrong_period(self):
        fx = self.fx
        seeds = dict(fx.trusted)
        # The fixture is random blocks without records, so every trusted block may be a source here.
        weak = R.iterate(fx.tails, seeds, {}, fx.period, rule='strict', filter_ambiguous=False,
                         record_sources=False)
        self.assertTrue(weak['blocked'])
        self.assertGreater(weak['control_links']['+2'], 0)
        for rule, filtered in (('strict2', False), ('strict2', True), ('strict', True)):
            with self.subTest(rule=rule, filtered=filtered):
                strong = R.iterate(fx.tails, seeds, {}, fx.period, rule=rule, filter_ambiguous=filtered,
                                   record_sources=False)
                self.assertFalse(strong['blocked'])
                np.testing.assert_array_equal(strong['confirmed'][fx.target], fx.keys[fx.target])
        backed = R.iterate(fx.tails, seeds, {}, fx.period)      # no records: no source, no link
        self.assertEqual(set(backed['provenance'].values()), {'seed'})

    def test_ambiguous_strict_candidates_do_not_link(self):
        a, b = b'\x01' * 16, b'\x02' * 16
        support = {a: {-300: {0, 1}, 300: {0, 2}}, b: {-600: {1, 2}}}
        self.assertIsNone(R.decide_link(support))
        self.assertEqual(R.decide_link({a: support[a]}), a)
        self.assertIsNone(R.decide_link({a: {-300: {0, 1}, 300: {2}}}))
        self.assertEqual(R.decide_link({a: {-300: {0, 1}, 300: {2}}}, 'strict+second'), a)


class FillRecordFillTest(unittest.TestCase):
    """[fill, R, fill] in one group (R a one-block item-final record) is, under the key
    K ^ fill ^ R, the plaintext [R, fill, R]: CRC-valid, recurring in every pass, and the reading
    the fill proposal prefers. Only records shared with a neighbouring group pin the key."""

    @classmethod
    def setUpClass(cls):
        rng = np.random.default_rng(41)
        items = [dict(title=sentence(rng, 12), texts=[sentence(rng, 46), sentence(rng, 46)], last=sentence(rng, 5))
                 for _ in range(4)]

        def one_pass(k):
            out, at = bytearray(), []
            for item in items:
                body = (b'\xbb' * 16 + make_opening(item['title'], toggle=k % 2, per_copy=bytes(6))
                        + b''.join(record(t, j + 1, k % 2, False) for j, t in enumerate(item['texts'])))
                out += bytes(rng.integers(0, 256, 16 * ((1 - (len(out) + len(body)) // 16) % 3), dtype=np.uint8))
                out += body
                at.append(len(out) // 16)                      # the final record: phase 1 of its group
                out += record(item['last'], 3, k % 2, True)     # one block, then a fill block
            out += bytes(rng.integers(0, 256, 16 * (-(len(out) // 16) % 3), dtype=np.uint8))
            return bytes(out), at

        first_pass, cls.at = one_pass(0)
        cls.period = len(first_pass) // 16
        assert cls.period % 3 == 0 and all(b % 3 == 1 for b in cls.at)
        plain = np.frombuffer(first_pass + b''.join(one_pass(k)[0] for k in (1, 2, 3)), np.uint8).reshape(-1, 16)
        cls.first = 9000
        cls.keys = {cls.first + g: rng.integers(0, 256, 16, dtype=np.uint8) for g in range(len(plain) // 3)}
        cls.tails = {3 * cls.first + i: b ^ cls.keys[cls.first + i // 3] for i, b in enumerate(plain)}
        cls.plain = plain
        cls.groups = [cls.first + (b + m * cls.period) // 3 for b in cls.at for m in range(4)]
        cls.swapped = {c: cls.keys[c] ^ plain[3 * (c - cls.first)] ^ plain[3 * (c - cls.first) + 1]
                       for c in cls.groups}
        with tempfile.TemporaryDirectory() as td:
            path = Path(td)/'items_fixture.json'
            rows = [[dict(text=t, ok=True) for t in item['texts'] + [item['last']]] for item in items]
            path.write_text(json.dumps(dict(items=rows), ensure_ascii=False), encoding='utf-8')
            cls.corpus = R.build_corpus([path])

    def test_swapped_key_gives_a_recurring_crc_valid_record_that_pins_nothing(self):
        for c in self.groups:
            b = 3 * (c - self.first)
            self.assertEqual(bytes(self.plain[b]), b'\xbb' * 16)
            self.assertEqual(bytes(self.plain[b + 2]), b'\xbb' * 16)
        keys = {**self.keys, **self.swapped}
        records = R.scan(keys, self.tails, self.first, len(self.keys))
        recurring = R.gate_a(records, self.period)
        inside = [r for r in recurring if self.first + r.offset // 16 // 3 in self.swapped and r.final]
        self.assertGreaterEqual(len(inside), 2 * len(self.groups) - len(self.at))   # gate A alone is fooled
        spanning = [r for r in inside if r.offset // 48 != (r.offset + r.size - 16) // 48]
        self.assertTrue(spanning)        # some even reach the next group through an optional fill block
        touched = {t // 3 for t in R.record_ticks(recurring, self.first)}
        self.assertFalse(touched & set(self.swapped))
        # under the true keys the preceding record's mandatory fill pins the same groups
        true_records = R.gate_a(R.scan(self.keys, self.tails, self.first, len(self.keys)), self.period)
        self.assertTrue(set(self.groups) <= {t // 3 for t in R.record_ticks(true_records, self.first)})

    def test_the_fill_proposal_prefers_the_swapped_key_and_it_is_never_output(self):
        proposals, _ = R.all_proposals(self.tails, self.corpus)
        preferred = [c for c in self.groups if c in proposals and np.array_equal(proposals[c][0], self.swapped[c])]
        self.assertGreaterEqual(len(preferred), len(self.groups) - 2)
        keys, prov, _, report = R.recover(self.tails, {}, proposals)
        self.assertEqual((report['status'], report['period']['period']), ('ok', self.period))
        good, bad = correct(keys, self.keys)
        self.assertEqual(bad, 0)
        self.assertGreater(good, 20)
        for c in preferred:
            if c in keys:
                self.assertEqual(prov[c], 'xorlink')

    def test_swapped_seeds_in_every_pass_are_not_link_sources(self):
        victim = self.groups[1]                                 # item 0, second pass
        seeds = {c: k for c, k in {**self.keys, **self.swapped}.items() if c != victim}
        keys, prov, _, report = R.recover(self.tails, seeds, {})
        self.assertEqual(report['status'], 'ok')
        self.assertNotIn(victim, keys)
        self.assertEqual(correct({c: k for c, k in keys.items() if prov[c] != 'seed'}, self.keys)[1], 0)
        records = R.gate_a(R.scan(seeds, self.tails, self.first, len(self.keys)), self.period)
        sources = R.record_ticks(records, self.first)
        self.assertTrue(sources)
        self.assertFalse({3 * c + p for c in self.swapped for p in range(3)} & sources)


class WrongSeedTest(unittest.TestCase):
    """Seeds are inputs, and the supplied archives hold wrong ones (found on DEV data): a phase
    swap repeated at one carousel position in every pass, and a CRC-16 collision in one copy."""

    @classmethod
    def setUpClass(cls):
        cls.car = Carousel(seed=3, passes=4.6)
        assert cls.car.period % 3 == 0

    def position(self):
        """A carousel position whose three blocks are distinct record text in every pass."""
        car = self.car
        step = car.period // 3
        for r in R.scan(car.keys, car.tails, car.first, len(car.keys)):
            block = r.offset // 16 + 1                         # blocks 1..4 of a full record are text only
            block += -block % 3
            g = car.first + block // 3
            copies = [g + m * step for m in range(-1, 4) if g + m * step in car.keys]
            if (r.body_length == 92 and block - r.offset // 16 <= 2 and len(copies) >= 4
                    and car.period <= block < 2 * car.period
                    and all(3 * c + p in car.tails for c in copies for p in range(3))):
                return g, copies
        self.fail('no suitable carousel position')

    def test_error_repeated_in_every_trusted_copy_is_not_copied_onto_the_last_copy(self):
        car = self.car
        target, copies = self.position()
        trusted = [c for c in copies if c != target]
        seeds = dict(car.keys)
        del seeds[target]
        error = (car.tails[3 * trusted[0]] ^ car.tails[3 * trusted[0] + 1])     # phases 0 and 1 swapped
        self.assertTrue(error.any())
        for c in trusted:
            seeds[c] = car.keys[c] ^ error
            np.testing.assert_array_equal(car.tails[3 * c] ^ car.tails[3 * c + 1], error)
        wrong = car.keys[target] ^ error
        loose = R.iterate(car.tails, seeds, {}, car.period, record_sources=False)
        self.assertFalse(loose['blocked'])                      # the P+-1..3 controls cannot see it
        np.testing.assert_array_equal(loose['confirmed'][target], wrong)
        keys, prov, _, report = R.recover(car.tails, seeds, {})
        self.assertFalse(report['xorlink']['blocked'])
        self.assertNotIn(target, keys)
        self.assertEqual(report['seed_audit']['contradicted'], 0)   # consistent copies: audit is blind
        self.assertEqual(correct({c: k for c, k in keys.items() if prov[c] != 'seed'}, car.keys)[1], 0)

    def test_single_wrong_seed_is_dropped_by_the_audit_and_never_propagates(self):
        car = self.car
        victim, _ = self.position()
        rng = np.random.default_rng(8)
        for error in (rng.integers(1, 256, 16, dtype=np.uint8), np.eye(16, dtype=np.uint8)[0] * 0x80,
                      car.tails[3 * victim] ^ car.tails[3 * victim + 2]):
            seeds = dict(car.keys)
            seeds[victim] = car.keys[victim] ^ error
            for backed in (True, False):
                with self.subTest(error=error.tobytes().hex(), record_sources=backed):
                    keys, prov, _, report = R.recover(car.tails, seeds, {}, record_sources=backed)
                    self.assertEqual([d['counter'] for d in report['seed_audit']['dropped']], [victim])
                    self.assertEqual(report['seed_audit']['dropped'][0]['linked'], car.keys[victim].tobytes().hex())
                    np.testing.assert_array_equal(keys[victim], car.keys[victim])
                    self.assertEqual(prov[victim], 'xorlink')
                    self.assertEqual(correct(keys, car.keys)[1], 0)
            kept, prov, _, report = R.recover(car.tails, seeds, {}, seed_audit=False)
            self.assertNotIn('seed_audit', report)
            self.assertEqual(prov[victim], 'seed')
            self.assertEqual(correct({c: k for c, k in kept.items() if prov[c] != 'seed'}, car.keys)[1], 0)

    def test_manual_period_that_only_aligns_some_copies_is_not_confirmed(self):
        car = self.car
        records = R.scan(car.keys, car.tails, car.first, len(car.keys))
        for manual in (2 * car.period // 3, 3 * car.period // 2, 4 * car.period // 3):
            with self.subTest(period=manual):
                info = R.choose_period(records, manual)
                self.assertFalse(info['confirmed'])
        self.assertIn('does not divide', R.choose_period(records, 2 * car.period // 3)['reason'])
        self.assertGreater(len(R.gate_a(records, 2 * car.period // 3)), R.MIN_CONFIRM_RECORDS)
        for manual in (car.period, 2 * car.period):
            self.assertTrue(R.choose_period(records, manual)['confirmed'])


class SealedCounterTest(unittest.TestCase):
    def test_counters_in_the_sealed_test_window_are_refused_whatever_the_path(self):
        self.assertIsNone(R.sealed_counter_reason([43679422, 43680792, 43703353, 43704034, 5000]))
        for counter in (43733365, 43757756, 43768176):          # split.json, test captures
            self.assertIn('sealed TEST', R.sealed_counter_reason([5000, counter]))
        car = Carousel(seed=31, first=43757000, passes=2.2)
        with tempfile.TemporaryDirectory() as td:
            path = Path(td)/'innocent-name.npz'
            car.data_units(path)
            with self.assertRaisesRegex(PermissionError, 'sealed TEST'):
                R.load_data_units([path])
            with contextlib.redirect_stderr(io.StringIO()) as err, self.assertRaises(SystemExit):
                R.main(['--data-units', str(path), '--no-phrases', '--out', str(Path(td)/'out')])
            self.assertIn('sealed TEST', err.getvalue())
            self.assertFalse((Path(td)/'out').exists())
            tails, _, _ = R.load_data_units([path], allow_sealed=True)
            self.assertEqual(len(tails), len(car.tails))


class ExclusionTest(unittest.TestCase):
    SEALED = (
        'contrib/kcbsdrm/reference/items_2026-11-25_2242KST_3205_hl5ntr.json',
        'contrib/kcbsdrm/reference/items_2026-11-26_0500KST_3205_hl5ntr.json',
        'contrib/kcbsdrm/reference/items_2026-11-26_0642KST_merged.json',
        'contrib/kcbsdrm/reference/items_2026-11-26_1008KST_merged.json',
        'contrib/kcbsdrm/reference/titles_2026-11-26.json',
        'contrib/kcbsdrm/reference/titles_2026-11-25.json',
        'contrib/kcbsdrm/reference/bulletin_2026-11-25_all.txt',
        'contrib/kcbsdrm/reference/KCBS2_text_2026-11-25_0448KST_3205kHz_hik.iptime.org.txt',
        'work/benchmark/salvage/nov25-2242-3205-hl5ntr/data_units.npz',
        'work/benchmark/salvage/nov26-0642-merged/data_units.npz',
        'work/benchmark/salvage/mar16-3205-hl5ntr/data_units.npz',
        'work/benchmark/tasks/test.T1.inputs.npz',
        'work/benchmark/tasks/syn-test.T0.truth.npz',
        'work/benchmark/tasks/transfer.T1.inputs.npz',
        'examples/nov28/member-3205-20min/member-dus.npz',
        'examples/nov28/member-text-leads.md',
        'examples/nov27/validation/late-payload/edogawa-data-units.npz',
        'examples/nov27/validation/swb-gsc/edogawa-data-units.npz',
        'examples/nov28/gsc-fields/data_units.npz',
        'work/acquire/seg-001/data_units.npz',
        'work/catchup/next/C/data_units.npz',
        '/home/user/quarantine/koryofront-2026-11-28/run/x/keys.npz',
        'dumps/0001.msc.bin',
    )
    DEV = ('contrib/kcbsdrm/reference/items_2026-11-25.json',
           'contrib/kcbsdrm/reference/items_2026-11-25_1246KST_merged.json',
           'work/benchmark/salvage/nov25-0448+0457-3205-hik/data_units.npz',
           'work/benchmark/salvage/nov25-1246-6140-merged/data_units.npz',
           'work/benchmark/real/nov25-0448+0457-3205-hik.npz')

    def test_hard_coded_list_covers_sealed_test_transfer_and_live_sources(self):
        for path in self.SEALED:
            with self.subTest(path=path):
                self.assertIsNotNone(R.excluded_reason(R.ROOT/path))
                self.assertIsNotNone(R.excluded_reason(path))
        for path in self.DEV:
            with self.subTest(path=path):
                self.assertIsNone(R.excluded_reason(R.ROOT/path))

    def test_default_corpus_is_the_two_dev_item_files(self):
        used, excluded = R.resolve_corpus()
        self.assertEqual([p.name for p in used],
                         ['items_2026-11-25.json', 'items_2026-11-25_1246KST_merged.json'])
        names = {Path(e['path']).name for e in excluded}
        self.assertTrue({'titles_2026-11-25.json', 'titles_2026-11-26.json',
                         'items_2026-11-25_2242KST_3205_hl5ntr.json'} <= names)
        used, _ = R.resolve_corpus(extra_excludes=['*items_2026-11-25.json'])
        self.assertEqual([p.name for p in used], ['items_2026-11-25_1246KST_merged.json'])

    def test_explicit_excluded_corpus_file_is_an_error(self):
        with self.assertRaisesRegex(ValueError, 'excluded'):
            R.resolve_corpus([str(R.ROOT/self.SEALED[0])])
        with tempfile.TemporaryDirectory() as td:
            path = Path(td)/'member-3205-notes.txt'
            path.write_text('평양\n', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'live source'):
                R.resolve_corpus([str(path)])
            used, excluded = R.resolve_corpus([td])
            self.assertEqual((used, len(excluded)), ([], 1))

    def test_cli_refuses_sealed_data_units_before_reading_them(self):
        with tempfile.TemporaryDirectory() as td, contextlib.redirect_stderr(io.StringIO()):
            for path in ('nov26-1008-merged/data_units.npz', 'edogawa-data-units.npz'):
                with self.subTest(path=path), self.assertRaises(SystemExit):
                    R.main(['--data-units', str(Path(td)/path), '--out', str(Path(td)/'out')])
            self.assertFalse((Path(td)/'out').exists())


class CliTest(unittest.TestCase):
    def test_end_to_end_outputs_and_seed_cleaning(self):
        car = Carousel(seed=31)
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            car.data_units(td/'data_units.npz')
            files = car.corpus(td)
            counters = np.array(sorted(car.keys), np.uint32)
            labelled = np.random.default_rng(2).random(len(counters)) < 0.5
            label = np.full((len(counters), 44), -1, np.int16)
            label[:, :16] = np.stack([car.keys[int(c)] for c in counters])
            label[3, 0] = (label[3, 0] + 1) % 256        # a wrong key the benchmark did not label
            labelled[3] = False
            np.savez_compressed(td/'labels.npz', counters=counters, mask_label=label, labelled=labelled)
            with contextlib.redirect_stdout(io.StringIO()):
                R.main(['--data-units', str(td/'data_units.npz'), '--seeds', str(td/'labels.npz'),
                        '--phrase-corpus', str(files[0]), '--holdout', '0.3',
                        '--proposal-cache', str(td/'cache.npz'), '--out', str(td/'out')])
            with np.load(td/'out'/'keys.npz', allow_pickle=False) as k:
                self.assertEqual((k['counters'].dtype, k['ks'].dtype, k['ks'].shape[1]),
                                 (np.uint32, np.uint8, 16))
                self.assertEqual(str(k['content_sha256']), R.content_sha256(k['counters'], k['ks']))
                self.assertTrue(set(k['provenance'].tolist()) <= set(R.PROVENANCE))
                for c, key in zip(k['counters'], k['ks']):
                    np.testing.assert_array_equal(key, car.keys[int(c)])
            report = json.loads((td/'out'/'report.json').read_text(encoding='utf-8'))
            self.assertEqual(report['period']['period'], car.period)
            self.assertEqual(report['holdout'].get('xorlink_wrong', 0) + report['holdout'].get('fill_wrong', 0)
                             + report['holdout'].get('phrase_wrong', 0), 0)
            self.assertEqual(report['output']['content_sha256'],
                             hashlib_content(td/'out'/'keys.npz'))
            self.assertEqual(report['corpus']['files'][0]['path'], str(files[0]))
            self.assertFalse(report['proposal_cache']['hit'])
            with contextlib.redirect_stdout(io.StringIO()):
                R.main(['--data-units', str(td/'data_units.npz'), '--phrase-corpus', str(files[0]),
                        '--proposal-cache', str(td/'cache.npz'), '--out', str(td/'out2')])
            self.assertTrue(json.loads((td/'out2'/'report.json').read_text())['proposal_cache']['hit'])

            np.savez_compressed(td/'archive.npz', counters=counters, ks=label[:, :16].astype(np.uint8),
                                crc_supported=np.ones((len(counters), 16), bool))
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                R.main(['--data-units', str(td/'data_units.npz'), '--seeds', str(td/'archive.npz'),
                        '--no-phrases', '--out', str(td/'out3')])

    def test_split_dropped_counters_are_removed_and_sealed_splits_refused(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            split = dict(splits=dict(
                dev=dict(captures=[dict(id='devcap', label_check=dict(dropped_counters=[11, 12]))]),
                test=dict(captures=[dict(id='testcap', label_check=dict(dropped_counters=[]))])))
            (td/'split.json').write_text(json.dumps(split))
            self.assertEqual(R.dropped_counters(td/'split.json', 'devcap'), ('dev', [11, 12]))
            with self.assertRaisesRegex(ValueError, 'refusing'):
                R.dropped_counters(td/'split.json', 'testcap')
            np.savez_compressed(td/'a.npz', counters=np.array([10, 11, 12, 13], np.uint32),
                                ks=np.zeros((4, 16), np.uint8),
                                crc_supported=np.array([[True] * 16] * 3 + [[False] + [True] * 15]))
            seeds, info = R.load_seeds(td/'a.npz', dropped=[11, 12])
            self.assertEqual((sorted(seeds), info['dropped_counters_applied']), ([10], [11, 12]))


class EvsCheckTest(unittest.TestCase):
    def test_flagged_keys_are_rejected_and_the_capture_rerun(self):
        car = Carousel(seed=7)
        seeds = car.subset(0.7)
        _, prov0, _, _ = R.recover(car.tails, seeds, {})
        victim = min(c for c, p in prov0.items() if p == 'xorlink')
        calls = []

        def checker(counters, ks, units):
            calls.append(list(counters))
            flags = np.array([int(c) == victim for c in counters], np.int64)
            return np.full(len(counters), 15), flags, np.ones(len(counters), np.int64), counters[::-1]

        keys, prov, _, report = R.recover(car.tails, seeds, {}, checker=checker, units={})
        self.assertNotIn(victim, keys)
        self.assertEqual(report['evs_check']['rejected'], [victim])
        self.assertIn(victim, calls[0])
        self.assertTrue(all(victim not in later for later in calls[1:]))
        self.assertEqual(len(report['evs_check']['iterations']), 2)   # re-run after the rejection
        self.assertEqual(report['evs_check']['iterations'][0]['label_flagged_groups'], 1)
        good, bad = correct({c: k for c, k in keys.items() if c not in seeds}, car.keys)
        self.assertEqual(bad, 0)


class EvsLeftoverTest(unittest.TestCase):
    def test_keys_first_seen_after_the_last_check_are_not_output(self):
        car = Carousel(seed=7)
        seeds = car.subset(0.7)
        seen = []

        def checker(counters, ks, units):               # flags one new key in every call
            seen.extend((int(c), k.tobytes()) for c, k in zip(counters, ks))
            flags = np.zeros(len(counters), np.int64)
            flags[0] = 1
            return np.full(len(counters), 15), flags, flags, counters

        keys, prov, _, report = R.recover(car.tails, seeds, {}, checker=checker, units={},
                                          evs_iterations=1, record_sources=False)
        rejected = set(report['evs_check']['rejected'])
        self.assertEqual(len(rejected), 1)
        self.assertGreater(sum(v != 'seed' for v in prov.values()), 0)
        for c, k in keys.items():
            if prov[c] != 'seed':
                self.assertNotIn(c, rejected)
                self.assertIn((c, k.tobytes()), seen)
        self.assertEqual(len(report['evs_check']['flagged_in_last_iteration']), 1)


def hashlib_content(path):
    with np.load(path, allow_pickle=False) as k:
        return R.content_sha256(k['counters'], k['ks'])


if __name__ == '__main__':
    unittest.main()
