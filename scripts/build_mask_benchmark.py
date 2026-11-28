"""Build the labelled benchmark for blind KCBS-2 mask-byte recovery.

The protocol, task definitions and pre-registered splits are documented in
examples/nov28/blind-mask-benchmark/protocol.md; split.json pins every input
and output file by SHA-256.

Layout of one group (all files): 60 frames in slot order
slot = 20*phase + 4*cycle + (position - 1), role = slot % 4, each frame
33 bytes = [mode byte][32 payload bytes] exactly as received (ciphertext).
Mask index m = 11*role + j covers payload byte 3j (frame byte 1 + 3j) of all
15 frames of that role. Index 43 (role 3, j = 10) is clear by convention.
Mask arrays are int16 with -1 for unknown.

Subcommands (run in this order, or `all`):
  real       salvage the six November captures and the March dumps, join keys
             by counter, run the decoder and carousel-copy label checks, write
             real/<capture>.npz
  nov27      export the November 27 receiver groups with their INFERRED
             P2-P4 masks (development only)
  synthetic  encode public and repository audio with the stock EVS encoder at
             13.2 kbps SWB and plant random 44-byte masks with exact truth
  tasks      write per-split, per-task method inputs (targets blanked) and the
             matching truth files
  baselines  score the uniform and mode-prior baselines on the development-side
             sets (dev, syn-dev, nov27-dev) and write baselines-dev.json
  register   write split.json with SHA-256 of every input and output file

Bulky outputs go under --out (default work/benchmark, gitignored).
"""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
from dataclasses import dataclass
import datetime as dt
import glob
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request

import numpy as np

from build_evs_gcc_independent import linux, linux_command
from render_continuous import MODE_POSITIONS, PACKET_STARTS
from render_measured_evs import match_group, measured_groups
from review_supplied_records import review
from salvage_msc_packets import salvage
from tail_fill_audit import idle_prefixes

ROOT = Path(__file__).resolve().parents[1]
FORMAT = 'kcbs-blind-mask-benchmark/1'
SLOTS = 60
FRAME_BYTES = 33
PACKET_BYTES = 179
MASK_BYTES = 44
CLEAR_INDEX = 43                      # role 3, j = 10: payload byte 30 sent in clear
KEYED = np.arange(0, 32, 3)           # payload offsets of the 11 masked bytes
ROLE_OF_SLOT = np.arange(SLOTS) % 4
EVS_DEC = ROOT/'work/evs_gcc_independent/EVS_dec'
EVS_COD = ROOT/'work/evs_gcc_independent/EVS_cod'
EVS_SRC = ROOT/'work/ref/evs/src/c-code'
DEFAULT_OUT = 'work/benchmark'
DOC_DIR = 'examples/nov28/blind-mask-benchmark'

# Per-byte label provenance codes stored in mask_source arrays.
PROVENANCE = {0: 'unknown', 1: 'text_crc_supported', 2: 'idle_tail_crc', 3: 'inferred_dev_only',
              4: 'clear_by_convention', 5: 'synthetic_exact'}
UNKNOWN, TEXT_CRC, IDLE_CRC, INFERRED, CLEAR, SYNTHETIC = range(6)

# Mask indices visible to a method and scored as targets. The clear byte 43 is
# visible in every task. T1 mirrors the real role-1 situation.
TASKS = {
    'T1': dict(visible=list(range(0, 11)) + [CLEAR_INDEX], targets=list(range(11, 16)),
               description='recover role-1 bytes j=0..4 (ks[11..15]); role 0 known, '
                           'role-1 j=5..10 and roles 2-3 unknown'),
    'T0': dict(visible=list(range(11, 16)) + [CLEAR_INDEX], targets=list(range(0, 11)),
               description='recover role-0 bytes (ks[0..10]); role-1 j=0..4 known, '
                           'everything else unknown (harder control)'),
    'TH': dict(visible=list(range(0, 16)) + [CLEAR_INDEX], targets=list(range(16, CLEAR_INDEX)),
               description='recover the 27 bytes the text tail never reveals (role-1 j=5..10, '
                           'role 2, role-3 j=0..9) given ks[0..15]; synthetic and inferred sets only'),
}

REF = 'contrib/kcbsdrm/reference'
KEYS = 'contrib/kcbsdrm/keys'


@dataclass(frozen=True)
class Capture:
    id: str
    split: str
    sources: tuple
    keys: str = None          # contrib key archive; None = March idle tail


CAPTURES = (
    Capture('nov25-0448+0457-3205-hik', 'dev',
            (f'{REF}/sf_2026-11-25_0448KST_3205_hik.bin', f'{REF}/sf_2026-11-25_0457KST_3205_hik.bin'),
            f'{KEYS}/keys_2026-11-25.npz'),
    Capture('nov25-1246-6140-merged', 'dev', (f'{REF}/sf_2026-11-25_1246KST_6140_merged.bin',),
            f'{KEYS}/keys_2026-11-25_1246KST_merged.npz'),
    Capture('nov25-2242-3205-hl5ntr', 'test', (f'{REF}/sf_2026-11-25_2242KST_3205_hl5ntr.bin',),
            f'{KEYS}/keys_2026-11-25_2242KST_3205_hl5ntr.npz'),
    Capture('nov26-0500-3205-hl5ntr', 'test', (f'{REF}/sf_2026-11-26_0500KST_3205_hl5ntr.bin',),
            f'{KEYS}/keys_2026-11-26_0500KST_3205_hl5ntr.npz'),
    Capture('nov26-0642-merged', 'test', (f'{REF}/sf_2026-11-26_0642KST_merged.bin',),
            f'{KEYS}/keys_2026-11-26_0642KST_merged.npz'),
    Capture('nov26-1008-merged', 'test', (f'{REF}/sf_2026-11-26_1008KST_merged.bin',),
            f'{KEYS}/keys_2026-11-26_1008KST_merged.npz'),
    Capture('mar16-3205-hl5ntr', 'transfer', tuple(sorted(
        str(Path(p).relative_to(ROOT)) for p in glob.glob(str(ROOT/'dumps/*.msc.bin'))))),
)

# Synthetic audio sources. A source belongs to exactly one split. `sha256` pins
# downloads; `start`/`seconds` select the excerpt that is encoded.
LIBROSA = 'https://librosa.org/data/audio/'
ARCHIVE = 'https://archive.org/download/'
SOURCES = (
    # ---------------- syn-dev ----------------
    dict(name='nov27-programme', split='syn-dev', kind='g192', path='examples/nov27/programme.192.gz',
         content='music (broadcast, decoded at 32 kHz with the stock EVS decoder)'),
    dict(name='wangjaesan-02-seashore', split='syn-dev', kind='url', content='music (DPRK light music)',
         url=ARCHIVE + 'wangjaesangyongumaktan-che1chip/02.%20%EB%85%B8%EC%9D%84%EB%B9%84%EB%82%80%20'
                       '%EB%B0%94%EB%8B%A4%EA%B0%80%20%3D%20The%20Seashore%20In%20The%20Glow.mp3',
         start=0, seconds=150, sha256='a4428f06910046eebe0a008d75d48055d0db06753f896dce2255e3feb9781c36',
         licence='archive.org upload, no licence stated; local research use only'),
    dict(name='librosa-vibeace', split='syn-dev', kind='url', content='music',
         url=LIBROSA + 'Kevin_MacLeod_-_Vibe_Ace.hq.ogg', start=0, seconds=90,
         sha256='73d6443ef90a7c022f164e5aa90e56c2291585930b39b1656d0765abbc1f1779', licence='CC BY 3.0 (librosa example)'),
    dict(name='librosa-brahms', split='syn-dev', kind='url', content='music',
         url=LIBROSA + 'Hungarian_Dance_number_5_-_Allegro_in_F_sharp_minor_(string_orchestra).hq.ogg',
         start=0, seconds=90,
         sha256='8e93ff0182a93168b15346c497b164cb49d2a97bf1e987a1149ea579e914532e', licence='public domain (librosa example)'),
    dict(name='librosa-fishin', split='syn-dev', kind='url', content='music with vocals',
         url=LIBROSA + 'Karissa_Hobbs_-_Lets_Go_Fishin.hq.ogg', start=0, seconds=90,
         sha256='85901bde0bc5f2cad28acb83487ccf99bd6908d7359f1a449fd799d8bebb3319', licence='CC BY-NC 3.0 (librosa example)'),
    dict(name='librivox-ko-hyun-01', split='syn-dev', kind='url', content='speech (Korean reading)',
         url=ARCHIVE + 'short_stories_hyun_1411_librivox/short_stories_01_hyun_128kb.mp3', start=0, seconds=150,
         sha256='ed452141858a7573edca5254cf4ba1150dfb22d32dbb57f688a6ee424aa78c02',
         licence='public domain (LibriVox)'),
    dict(name='librivox-en-spc160-duringmusic', split='syn-dev', kind='url', content='speech (English poetry)',
         url=ARCHIVE + 'spc160_1610_librivox/spc160_duringmusic_el_128kb.mp3', sha256='ff853bd1263f8fed9f727ad78c716c964fa1f2ad8d61c4c6061dec6402500b10',
         licence='public domain (LibriVox)'),
    dict(name='librivox-en-spc160-withaflower', split='syn-dev', kind='url', content='speech (English poetry)',
         url=ARCHIVE + 'spc160_1610_librivox/spc160_withaflower_ljs_128kb.mp3', sha256='f76de68d452937db825456a3cfc7f76a248fb73dcb1e6ce441114652a1855e14',
         licence='public domain (LibriVox)'),
    dict(name='librivox-en-spc160-anticipation', split='syn-dev', kind='url', content='speech (English poetry)',
         url=ARCHIVE + 'spc160_1610_librivox/spc160_anticipation_ss_128kb.mp3', sha256='02201621eb172d9969a3d4a735ae7f680520663ddc112963399109d3792b5618',
         licence='public domain (LibriVox)'),
    # ---------------- syn-test ----------------
    dict(name='wangjaesan-03-skylark', split='syn-test', kind='url', content='music (DPRK light music)',
         url=ARCHIVE + 'wangjaesangyongumaktan-che1chip/03.%20%EC%A2%85%EB%8B%A4%EB%A6%AC%20%3D%20Skylark.mp3',
         start=0, seconds=150, sha256='13e422405b0d393e7a22ea9319d7e26812f49ec908a705f1400ba20110bc97d5',
         licence='archive.org upload, no licence stated; local research use only'),
    dict(name='librosa-nutcracker', split='syn-test', kind='url', content='music',
         url=LIBROSA + 'Kevin_MacLeod_-_P_I_Tchaikovsky_Dance_of_the_Sugar_Plum_Fairy.hq.ogg', start=0, seconds=90,
         sha256='f062221a56a227cdb7c067cf2e6ac0e250a50012f7693ca0c8e31f05f83e49b1', licence='CC BY 3.0 (librosa example)'),
    dict(name='librosa-pistachio', split='syn-test', kind='url', content='music',
         url=LIBROSA + '442789__lena-orsa__happy-music-pistachio-ice-cream-ragtime.hq.ogg', start=0, seconds=90,
         sha256='1cc83b775e640a8dd409da9e29f5b5e0124bc5ec9bb4fda975919d31d1d893b8', licence='CC BY 3.0 (librosa example)'),
    dict(name='librosa-sweetwaltz', split='syn-test', kind='url', content='music',
         url=LIBROSA + '147793__setuniman__sweet-waltz-0i-22mi.hq.ogg', start=0, seconds=90,
         sha256='248f93b7c729bc0bd6c4cbc107e6b67ec4d60e40c111e313d4d69f77748da26a', licence='CC BY-NC 3.0 (librosa example)'),
    dict(name='librivox-ko-na-04', split='syn-test', kind='url', content='speech (Korean reading)',
         url=ARCHIVE + 'short_stories_na_1412_librivox/shortstories_4_na_128kb.mp3', start=0, seconds=150,
         sha256='c60ba6834f6714e55523777b5b0d56705cd68b123cf8054dbeb95b084d55aded',
         licence='public domain (LibriVox)'),
    dict(name='librivox-en-spc258-barestory', split='syn-test', kind='url', content='speech (English poetry)',
         url=ARCHIVE + 'spc258_2412_librivox/spc258_barestory_mlm_128kb.mp3', sha256='9b8e2a3dab4d621a3013df11e678e88c8f605ef1519fbf1f3854c4aa2cf32ddb',
         licence='public domain (LibriVox)'),
    dict(name='librivox-en-spc258-novembernight', split='syn-test', kind='url', content='speech (English poetry)',
         url=ARCHIVE + 'spc258_2412_librivox/spc258_novembernight_wt_128kb.mp3', sha256='4a22614c74ae9458b167af1dd888d0aabdee3dc8a072b644ddb3561344c3a33b',
         licence='public domain (LibriVox)'),
    dict(name='librivox-en-spc258-end', split='syn-test', kind='url', content='speech (English poetry)',
         url=ARCHIVE + 'spc258_2412_librivox/spc258_end_ts_128kb.mp3', sha256='46ee9b326858c643b2c076c07e56340675482c78e985159a751089996ebd3b4e',
         licence='public domain (LibriVox)'),
    dict(name='librivox-ja-dokoe-12', split='syn-test', kind='url', content='speech (Japanese reading)',
         url=ARCHIVE + 'doko_e_1404_librivox/dokoe_12_masamune_128kb.mp3', sha256='161275fdab2794c445445801bf6e998c67f2de5833f43ead4b51260283a0a948',
         licence='public domain (LibriVox)'),
)
# Repository audio that cannot produce SWB frames: only 16 kHz renders exist, so the
# stock encoder's bandwidth detector selects WB. Measured and reported, not used.
EXCLUDED_SOURCES = (
    dict(name='nov27-radio-mp3', path='examples/nov27/radio.mp3',
         reason='16 kHz render of the same performance as nov27-programme'),
    dict(name='nov27-fully-supplied-12s', path='examples/nov27/fully-supplied-12s.wav',
         reason='16 kHz render of the same performance as nov27-programme'),
    dict(name='nov19-longing', path='examples/nov19/longing-is-my-happiness.mp3', reason='16 kHz render only'),
    dict(name='nov19-mothers-voice', path='examples/nov19/mothers-voice.mp3', reason='16 kHz render only'),
    dict(name='nov19-mothers-voice-8s4', path='examples/nov19/mothers-voice-fully-supplied-8s4.wav',
         reason='16 kHz render only'),
)
ENCODER_OPTIONS = ['-q', '-max_band', 'SWB', '13200', '32']   # no DTX, no channel-aware mode
SYNTH_SEEDS = {'syn-dev': 20261128_1, 'syn-test': 20261128_2}
TARGET_DBFS = -20.0      # lower levels push the encoder's bandwidth detector to WB/NB on music
PEAK_DBFS = -1.0

# Broadcast census quoted in the task brief (1,448 groups), for comparison.
BROADCAST_CENSUS = {'TCX20/SWB': 34.7, 'HQ/SWB': 26.5, 'SWB GEN TBE': 16.1, 'SWB INA(GSC)': 9.9,
                    'SWB VOI TBE': 9.1, 'SWB TRA': 3.1, 'SWB AUD(GSC)': 0.5}
MODE_NAMES = {0: 'NB GEN', 1: 'NB VOI', 2: 'NB TRA', 3: 'NB AUD', 4: 'NB INA', 5: 'WB GEN', 6: 'WB VOI',
              7: 'WB TRA', 8: 'WB AUD(GSC)', 9: 'WB INA', 10: 'SWB GEN TBE', 11: 'SWB VOI TBE', 12: 'SWB TRA',
              13: 'SWB AUD(GSC)', 14: 'SWB INA(GSC)', 15: 'NB GEN0', 16: 'NB VOI0', 17: 'WB GEN0',
              18: 'WB VOI0', 19: 'SWB GEN BWE', 20: 'SWB VOI BWE', 29: 'NB MDCT', 30: 'WB MDCT', 31: 'SWB MDCT'}


# --------------------------------------------------------------------------- helpers

def sha256_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


def rel(path):
    path = Path(path).resolve()
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def npz_content_sha256(path):
    """Digest of an npz's arrays (name, dtype, shape, bytes); stable across rebuilds,
    unlike the file hash, which also covers zip member timestamps."""
    h = hashlib.sha256()
    with np.load(path, allow_pickle=False) as d:
        for name in sorted(d.files):
            a = np.ascontiguousarray(d[name])
            h.update(f'{name}|{a.dtype.str}|{a.shape}|'.encode())
            h.update(a.tobytes())
    return h.hexdigest()


def file_record(path):
    path = Path(path)
    record = dict(path=rel(path), bytes=path.stat().st_size, sha256=sha256_file(path))
    if path.suffix == '.npz':
        record['content_sha256'] = npz_content_sha256(path)
    return record


def mode_family(mode):
    """Coder family of a 13.2 kbps EVS mode byte (top five bits index the mode table)."""
    index = int(mode) >> 3
    if index >= 29:
        return ('TCX20' if mode & 4 else 'HQ') + '/' + ['NB', 'WB', 'SWB'][index - 29]
    return MODE_NAMES.get(index, f'idx{index}')


def census(modes):
    counts = Counter(mode_family(m) for m in np.asarray(modes).ravel())
    total = sum(counts.values())
    return dict(frames=total, percent={k: round(100*v/total, 1) for k, v in counts.most_common()})


def expand_mask(mask):
    """(..., 44) int16 mask with -1 unknown -> (..., 60, 33) uint8 XOR pattern (unknown = 0)."""
    mask = np.asarray(mask)
    known = np.where(mask < 0, 0, mask).astype(np.uint8)
    out = np.zeros(mask.shape[:-1] + (SLOTS, FRAME_BYTES), np.uint8)
    for role in range(4):
        out[..., role::4, 1 + KEYED] = known[..., None, 11*role:11*role + 11]
    return out


def unit_frames(unit, packet_ok):
    """20 frames and per-frame presence for one 716-byte data unit and its packet CRC flags."""
    frames = np.zeros((20, FRAME_BYTES), np.uint8)
    present = np.zeros(20, bool)
    for s, (mode, start) in enumerate(zip(MODE_POSITIONS, PACKET_STARTS)):
        ok = packet_ok[mode // PACKET_BYTES] and packet_ok[start // PACKET_BYTES:(start + 31) // PACKET_BYTES + 1].all()
        if ok:
            present[s] = True
            frames[s, 0] = unit[mode]
            frames[s, 1:] = unit[start:start + 32]
    return frames, present


def runs_of(counters):
    """Run id per group: a new run starts wherever the counter does not advance by one."""
    counters = np.asarray(counters, np.int64)
    return np.concatenate(([0], np.cumsum(np.diff(counters) != 1))).astype(np.int32)


def run_table(counters, run_id):
    rows = []
    for r in np.unique(run_id):
        c = np.asarray(counters)[run_id == r]
        rows.append(dict(run=int(r), first_counter=int(c[0]), last_counter=int(c[-1]), groups=int(len(c))))
    return rows


def write_g192(path, frames, keep):
    with open(path, 'wb') as f:
        for bits, good in zip(np.unpackbits(np.asarray(frames, np.uint8), axis=1), keep):
            if good:
                f.write(np.array([0x6b21, 264], '<u2').tobytes())
                f.write(np.where(bits, 0x81, 0x7f).astype('<u2').tobytes())
            else:
                f.write(np.array([0x6b20, 0], '<u2').tobytes())


def read_g192(path):
    """Frames (n, 33) and a supplied flag per frame from a G.192 file of 264-bit frames."""
    words = np.fromfile(path, '<u2')
    frames, supplied, offset = [], [], 0
    while offset < len(words):
        sync, length = int(words[offset]), int(words[offset + 1])
        bits = words[offset + 2:offset + 2 + length]
        offset += 2 + length
        if length == 264 and sync == 0x6b21:
            frames.append(np.packbits(bits == 0x81))
            supplied.append(True)
        elif length == 0:
            frames.append(np.zeros(FRAME_BYTES, np.uint8))
            supplied.append(False)
        else:
            raise ValueError(f'{path}: unexpected G.192 frame of {length} bits (sync {sync:#x})')
    return np.array(frames, np.uint8).reshape(-1, FRAME_BYTES), np.array(supplied, bool)


def run_tool(command, timeout=600):
    p = subprocess.run(linux_command(*command), capture_output=True, timeout=timeout)
    if p.returncode:
        raise RuntimeError(f'{command[0]} failed: ' + p.stderr.decode(errors='replace')[-2000:])
    return p


# --------------------------------------------------------------------------- decoder label check

TRACE_ANCHOR = b"            /* convert 'float' output data to 'short' */"


def build_traced_decoder(out_dir):
    """Compile the reference decoder with one stderr trace line per frame (bfi, BER_detect).

    The unmodified sources under work/ref are read, never edited: the traced copy of
    decoder.c lives in out_dir. Build flags match build_evs_gcc_independent.py.
    """
    out_dir.mkdir(parents=True, exist_ok=False)
    text = (EVS_SRC/'lib_dec/decoder.c').read_bytes()
    if text.count(TRACE_ANCHOR) != 1:
        raise RuntimeError('trace anchor not found exactly once in decoder.c')
    trace = (b'            fprintf(stderr,"TRACE,%ld,%d,%d,%d\\n",frame,(int)st->bfi,'
             b'(int)st->BER_detect,(int)st->core);\n')
    traced = out_dir/'decoder_traced.c'
    traced.write_bytes(text.replace(TRACE_ANCHOR, trace + TRACE_ANCHOR))
    files = sorted((EVS_SRC/'lib_com').glob('*.c'))
    files += [p for p in sorted((EVS_SRC/'lib_dec').glob('*.c')) if p.name != 'decoder.c']
    binary = out_dir/'EVS_dec_traced'
    arguments = ['-O0', '-std=gnu99', '-fno-strict-aliasing']
    arguments += ['-I' + linux(EVS_SRC/sub) for sub in ('lib_com', 'lib_dec', 'lib_enc')]
    arguments += [linux(traced)] + [linux(p) for p in files] + ['-lm', '-o', linux(binary)]
    rsp = out_dir/'traced.rsp'
    rsp.write_text('\n'.join('"' + s.replace('"', '\\"') + '"' for s in arguments), encoding='utf-8')
    run_tool(['gcc', '@' + linux(rsp)], timeout=1800)
    info = dict(binary=rel(binary), sha256=sha256_file(binary), source=rel(EVS_SRC),
                decoder_c_sha256=sha256_file(EVS_SRC/'lib_dec/decoder.c'),
                patch='one fprintf(stderr, "TRACE,frame,bfi,BER_detect,core") before syn_output; '
                      'all other sources compiled unmodified from work/ref')
    (out_dir/'build.json').write_text(json.dumps(info, indent=2), encoding='utf-8')
    return binary, info


def decode_flags(binary, frames, keep, workdir, tag):
    """Supplied and flagged (bfi or BER_detect) frame counts for one G.192 stream."""
    stream, raw = workdir/(tag + '.192'), workdir/(tag + '.raw')
    write_g192(stream, frames, keep)
    p = run_tool([binary, '-q', '-no_delay_cmp', '32', stream, raw], timeout=300)
    rows = [line.split(',')[1:] for line in p.stderr.decode(errors='replace').splitlines()
            if line.startswith('TRACE,')]
    stream.unlink()
    raw.unlink()
    data = np.array(rows, dtype=np.int64).reshape(-1, 4)
    if len(data) != len(keep):
        raise RuntimeError(f'{tag}: {len(data)} trace lines for {len(keep)} frames')
    flagged = ((data[:, 1] != 0) | (data[:, 2] != 0)) & keep
    return int(keep.sum()), int(flagged.sum())


def role0_flag_check(binary, frames, present, labels, workdir, workers):
    """Decode each group's role-0 frames alone with its label and with a wrong-group label.

    The control uses the role-0 label of the labelled group half the list away, so mode
    bytes, clear bytes, erasures and frame positions are unchanged. Returns arrays of
    supplied, label-flagged and control-flagged frame counts (one per group).
    """
    n = len(frames)
    control = np.roll(np.arange(n), n // 2) if n > 1 else np.arange(n)
    role0 = np.full((n, MASK_BYTES), -1, np.int16)
    role0[:, :11] = labels[:, :11]
    wrong = role0[control]
    keep = present & (ROLE_OF_SLOT == 0)

    def one(i):
        plain = frames[i] ^ expand_mask(role0[i])
        bad = frames[i] ^ expand_mask(wrong[i])
        s, f = decode_flags(binary, plain, keep[i], workdir, f'label_{i}')
        _, g = decode_flags(binary, bad, keep[i], workdir, f'control_{i}')
        return s, f, g

    with ThreadPoolExecutor(max_workers=workers) as pool:
        out = list(pool.map(one, range(n)))
    out = np.array(out, np.int16).reshape(-1, 3)
    return out[:, 0], out[:, 1], out[:, 2], control


# --------------------------------------------------------------------------- real captures

def carousel_period(key_counters, ks, supported, du_counters, phases, du, lo=200, hi=1500):
    """Text-carousel length in 16-byte blocks: the lag with most identical fully keyed blocks."""
    first = int(key_counters[0])
    span = int(key_counters[-1]) - first + 1
    plain = np.zeros((3*span, 16), np.uint8)
    known = np.zeros(3*span, bool)
    index = {int(c): i for i, c in enumerate(key_counters)}
    for c, p, row in zip(du_counters, phases, du):
        i = index.get(int(c))
        if i is None:
            continue
        block = 3*(int(c) - first) + int(p)
        plain[block] = row[698:714] ^ ks[i]
        known[block] = supported[i].all()
    scores = []
    for lag in range(lo, min(hi, len(plain) - 1)):
        same = known[:-lag] & known[lag:] & (plain[:-lag] == plain[lag:]).all(axis=1)
        scores.append((int(same.sum()), lag))
    scores.sort(reverse=True)
    return dict(period=scores[0][1], matches=scores[0][0], runner_up=dict(lag=scores[1][1], matches=scores[1][0]))


COPY_LAGS = (1, 2, 3)        # carousel passes compared on each side of a block
TOGGLE_BIT = 0x80            # record-header item toggle (byte 0 of a header block)


def carousel_copy_check(key_counters, ks, supported, du_counters, phases, du, period, lags=COPY_LAGS):
    """Cross-copy test of fully supported 16-byte labels against the text carousel.

    The scrolling text repeats every `period` 16-byte blocks, so the plaintext of block b
    (its tail XOR its group's key) must equal the plaintext of blocks b +- k*period, which
    are decrypted with other groups' keys. For each key row and byte position, comparisons
    with fully supported copies in other groups are counted as agreeing or disagreeing. A
    difference of exactly 0x80 in byte 0 is ignored: the record-header item toggle flips
    between passes. A key byte that is wrong (for example from a CRC-passing garbled text
    record) disagrees with every copy of every block of its group. Key counters must be
    increasing. Returns per key row: contradicted (some byte position with a disagreement
    and no agreement), confirmed16 (every byte position agreed at least once), compared
    (at least one comparison), and the agree / disagree counts (N, 16).
    """
    key_counters = np.asarray(key_counters, np.int64)
    first = int(key_counters[0])
    span = int(key_counters[-1]) - first + 1
    full = np.asarray(supported, bool).all(axis=1)
    row_of = np.full(span, -1, np.int64)
    row_of[key_counters - first] = np.arange(len(key_counters))
    plain = np.zeros((3*span, 16), np.uint8)
    known = np.zeros(3*span, bool)
    for c, p, unit in zip(du_counters, phases, du):
        offset = int(c) - first
        if not 0 <= offset < span or row_of[offset] < 0 or not full[row_of[offset]]:
            continue
        block = 3*offset + int(p)
        plain[block] = unit[698:714] ^ ks[row_of[offset]]
        known[block] = True
    agree = np.zeros((len(key_counters), 16), np.int32)
    disagree = np.zeros((len(key_counters), 16), np.int32)
    blocks = np.flatnonzero(known)
    for lag in lags:
        for sign in (1, -1):
            other = blocks + sign*lag*period
            ok = (other >= 0) & (other < len(known))
            a, o = blocks[ok], other[ok]
            ok = known[o] & (a // 3 != o // 3)
            a, o = a[ok], o[ok]
            diff = plain[a] ^ plain[o]
            diff[:, 0] = np.where(diff[:, 0] == TOGGLE_BIT, 0, diff[:, 0])
            rows = row_of[a // 3]
            np.add.at(agree, rows, (diff == 0).astype(np.int32))
            np.add.at(disagree, rows, (diff != 0).astype(np.int32))
    contradicted = ((agree == 0) & (disagree > 0)).any(axis=1) & full
    return dict(contradicted=contradicted, confirmed16=(agree > 0).all(axis=1) & full,
                compared=(agree + disagree).sum(axis=1) > 0, agree=agree, disagree=disagree)


def assemble_capture(capture, salvage_dir):
    """Groups of one capture: counters, frames (N,60,33), presence, and complete-group DUs."""
    paths = [ROOT/p for p in capture.sources]
    log = io.StringIO()
    with redirect_stdout(log):
        salvage(paths, salvage_dir, transport_only=True, save_packets=True)
    report = json.loads((salvage_dir/'report.json').read_text(encoding='utf-8'))
    with np.load(salvage_dir/'packets.npz') as d:
        ticks, packets, packet_ok = d['ticks'], d['packets'], d['packet_ok']
    counters = np.unique(ticks // 3)
    index = {int(c): i for i, c in enumerate(counters)}
    frames = np.zeros((len(counters), SLOTS, FRAME_BYTES), np.uint8)
    present = np.zeros((len(counters), SLOTS), bool)
    for tick, body, ok in zip(ticks, packets, packet_ok):
        c, phase = divmod(int(tick), 3)
        f, p = unit_frames(body.reshape(-1), ok)
        frames[index[c], 20*phase:20*phase + 20] = f
        present[index[c], 20*phase:20*phase + 20] = p
    with np.load(salvage_dir/'data_units.npz') as d:
        units = dict(counters=d['counters'].copy(), phases=d['phases'].copy(), du=d['du'].copy())
    with np.load(salvage_dir/'groups.npz') as d:
        complete = dict(counters=d['counters'].copy(), tails=d['tails'].copy())
    return counters.astype(np.uint32), frames, present, units, complete, report


def build_real(args):
    out = Path(args.out).resolve()
    real_dir = out/'real'
    real_dir.mkdir(parents=True, exist_ok=False)
    binary, build_info = build_traced_decoder(out/'tools/evs_dec_traced')
    receipt = dict(format=FORMAT, step='real', created=now(), decoder_check_build=build_info,
                   stock_decoder=file_record(EVS_DEC), captures=[])
    for capture in CAPTURES:
        print(f'[real] {capture.id}: salvaging {len(capture.sources)} file(s)', flush=True)
        counters, frames, present, units, complete, salvage_report = assemble_capture(
            capture, out/'salvage'/capture.id)
        n = len(counters)
        label = np.full((n, MASK_BYTES), -1, np.int16)
        source = np.zeros((n, MASK_BYTES), np.int8)
        label[:, CLEAR_INDEX] = 0
        source[:, CLEAR_INDEX] = CLEAR
        crc_recheck = np.zeros((n, 16), bool)
        repeat_ok = np.zeros((n, 16), bool)
        copy_compared = np.zeros(n, bool)
        copy_confirmed = np.zeros(n, bool)
        copy_contradicted = np.zeros(n, bool)
        index = {int(c): i for i, c in enumerate(counters)}
        info = dict(id=capture.id, split=capture.split, inputs=[file_record(ROOT/p) for p in capture.sources],
                    salvage=salvage_report, groups=n, complete_groups=int(present.all(axis=1).sum()))
        if capture.keys:
            with np.load(ROOT/capture.keys) as k:
                kc, ks, sup = k['counters'].astype(np.int64), k['ks'].copy(), k['crc_supported'].copy()
            order = np.argsort(kc)
            kc, ks, sup = kc[order], ks[order], sup[order]
            info['keys'] = file_record(ROOT/capture.keys)
            period = carousel_period(kc, ks, sup, units['counters'], units['phases'], units['du'])
            checked0, _ = review(kc, ks, sup, units['counters'], units['phases'], units['du'], 0)
            checked1, _ = review(kc, ks, sup, units['counters'], units['phases'], units['du'], period['period'])
            copy = carousel_copy_check(kc, ks, sup, units['counters'], units['phases'], units['du'], period['period'])
            missing = 0
            for row, (c, key, s, a, b) in enumerate(zip(kc, ks, sup, checked0, checked1)):
                i = index.get(int(c))
                if i is None:
                    missing += 1
                    continue
                label[i, :16] = np.where(s, key.astype(np.int16), -1)
                source[i, :16] = np.where(s, TEXT_CRC, UNKNOWN)
                crc_recheck[i], repeat_ok[i] = a, b
                copy_compared[i] = copy['compared'][row]
                copy_confirmed[i] = copy['confirmed16'][row]
                copy_contradicted[i] = copy['contradicted'][row]
            full = (source[:, :16] == TEXT_CRC).all(axis=1)
            info['key_archive'] = dict(groups=int(len(kc)), all16_supported=int(sup.all(axis=1).sum()),
                                       counters_not_received=missing, carousel=period,
                                       crc_recheck_all16=int(crc_recheck.all(axis=1).sum()),
                                       repeat_confirmed_all16=int(repeat_ok.all(axis=1).sum()),
                                       copy_check=dict(lags_in_periods=list(COPY_LAGS),
                                                       compared=int((full & copy_compared).sum()),
                                                       confirmed16=int((full & copy_confirmed).sum()),
                                                       contradicted=int((full & copy_contradicted).sum())))
        else:
            keys, ok = idle_prefixes(complete['tails'])
            for c, key, good in zip(complete['counters'], keys, ok):
                if good:
                    i = index[int(c)]
                    label[i, :16] = key
                    source[i, :16] = IDLE_CRC
                    crc_recheck[i] = repeat_ok[i] = True
            full = (source[:, :16] == IDLE_CRC).all(axis=1)
            info['idle_tail'] = dict(complete_groups=int(len(ok)), idle_crc_passed=int(ok.sum()),
                                     rule='ks[0..15] = phase-0 tail XOR 0xFF; phases 1-2 must decrypt to '
                                          '68 f0 "TextMessage is sending..." with a matching CRC-16')
        # Decoder check of the role-0 part of every full label.
        cand = np.flatnonzero(full)
        supplied = np.full(n, -1, np.int16)
        flag_label = np.full(n, -1, np.int16)
        flag_control = np.full(n, -1, np.int16)
        control_counter = np.zeros(n, np.int64)
        with tempfile.TemporaryDirectory(dir=out) as tmp:
            s, f, g, ctrl = role0_flag_check(binary, frames[cand], present[cand], label[cand], Path(tmp),
                                             args.workers)
        supplied[cand], flag_label[cand], flag_control[cand] = s, f, g
        control_counter[cand] = counters[cand][ctrl]
        dropped_flags = full & (flag_label >= args.max_label_flags + 1)
        dropped_copy = full & copy_contradicted
        dropped = dropped_flags | dropped_copy
        labelled = full & ~dropped
        strict = labelled & crc_recheck.all(axis=1) & repeat_ok.all(axis=1)
        status = np.where(labelled, 'labelled', np.where(dropped_copy, 'dropped_copy_contradiction', np.where(
            dropped, 'dropped_decoder_flags', np.where((source[:, :16] != UNKNOWN).any(axis=1), 'partial_key', 'no_key'))))
        # A dropped label is not trusted anywhere: blank it in the visible label too.
        label[dropped, :CLEAR_INDEX] = -1
        source[dropped, :CLEAR_INDEX] = UNKNOWN
        run_id = runs_of(counters)
        info['label_check'] = dict(
            rule=f'drop a full label when its role-0 frames raise more than {args.max_label_flags} decoder '
                 'flags (bfi or BER_detect) decoded alone; control = role-0 label of another labelled group. '
                 'Also drop a full text label that a text-carousel copy contradicts: some key byte position '
                 f'disagrees with, and never agrees with, the plaintext of blocks +-{list(COPY_LAGS)} carousel '
                 'periods away decrypted with other groups\' keys (0x80 in byte 0 ignored)',
            candidates=int(full.sum()), role0_frames_supplied=int(supplied[cand].sum()),
            label_flagged_frames=int(flag_label[cand].sum()), control_flagged_frames=int(flag_control[cand].sum()),
            groups_with_label_flags=int((flag_label[cand] > 0).sum()),
            groups_with_control_flags=int((flag_control[cand] > 0).sum()),
            dropped=int(dropped.sum()), dropped_counters=[int(c) for c in counters[dropped]],
            dropped_label_flags=[int(x) for x in flag_label[dropped]],
            dropped_decoder_flags=int(dropped_flags.sum()),
            dropped_copy_contradiction=int(dropped_copy.sum()),
            copy_contradicted_counters=[int(c) for c in counters[dropped_copy]],
            decoder_dropped_but_copy_confirmed=int((dropped_flags & copy_confirmed).sum()))
        info['status'] = dict(Counter(status.tolist()))
        info['labelled'] = int(labelled.sum())
        info['strict'] = int(strict.sum())
        info['runs'] = run_table(counters, run_id)
        info['census'] = census(frames[present][:, 0])
        path = real_dir/f'{capture.id}.npz'
        np.savez_compressed(
            path, format=FORMAT, capture=capture.id, split=capture.split,
            group_id=np.array([f'{capture.id}:{int(c)}' for c in counters]), counters=counters,
            frames=frames, present=present, mask_label=label, mask_source=source,
            labelled=labelled, strict=strict, label_status=status, run_id=run_id,
            crc_recheck16=crc_recheck, repeat_confirmed16=repeat_ok, check_supplied=supplied,
            check_label_flags=flag_label, check_control_flags=flag_control, check_control_counter=control_counter,
            check_copy_compared=copy_compared, check_copy_confirmed16=copy_confirmed,
            check_copy_contradicted=copy_contradicted)
        info['output'] = file_record(path)
        receipt['captures'].append(info)
        print(json.dumps({k: info[k] for k in ('id', 'groups', 'labelled', 'strict', 'status')}), flush=True)
        print('  label check: ' + json.dumps({k: v for k, v in info['label_check'].items()
                                               if k not in ('rule', 'dropped_counters', 'dropped_label_flags')}),
              flush=True)
    (real_dir/'receipt.json').write_text(json.dumps(receipt, indent=2), encoding='utf-8')


# --------------------------------------------------------------------------- November 27 (inferred)

def build_nov27(args):
    out = Path(args.out).resolve()
    nov_dir = out/'nov27'
    nov_dir.mkdir(parents=True, exist_ok=False)
    receiver = ROOT/'examples/nov27/receiver'
    manifest_path = ROOT/'dumps/nov27-measured-masks.json'
    groups = measured_groups(json.loads(manifest_path.read_text(encoding='utf-8')))
    with np.load(receiver/'packets.npz') as d:
        ticks, packets, packet_ok = d['ticks'], d['packets'], d['packet_ok']
    with np.load(receiver/'keys.npz') as d:
        keys = {int(c): (k.copy(), s.copy()) for c, k, s in zip(d['counters'], d['ks'], d['crc_supported'])}
    received = {int(t): (b.reshape(-1), ok) for t, b, ok in zip(ticks, packets, packet_ok)}
    counters = np.unique(ticks // 3).astype(np.uint32)
    n = len(counters)
    index = {int(c): i for i, c in enumerate(counters)}
    frames = np.zeros((n, SLOTS, FRAME_BYTES), np.uint8)
    present = np.zeros((n, SLOTS), bool)
    for tick, (unit, ok) in received.items():
        c, phase = divmod(tick, 3)
        f, p = unit_frames(unit, ok)
        frames[index[c], 20*phase:20*phase + 20], present[index[c], 20*phase:20*phase + 20] = f, p
    label = np.full((n, MASK_BYTES), -1, np.int16)
    source = np.zeros((n, MASK_BYTES), np.int8)
    label[:, CLEAR_INDEX], source[:, CLEAR_INDEX] = 0, CLEAR
    inferred_phases = np.zeros((n, 3), bool)
    agreement, rejected, conflicts = Counter(), {}, []
    for c, (key, sup) in keys.items():
        if c in index and sup.any():
            label[index[c], :16] = np.where(sup, key.astype(np.int16), -1)
            source[index[c], :16] = np.where(sup, TEXT_CRC, UNKNOWN)
    for c, (hashes, masks) in groups.items():
        if c not in index:
            rejected[c] = 'outside capture'
            continue
        reason = match_group(c, hashes, received)
        if reason is not None:
            rejected[c] = reason
            continue
        i = index[c]
        inferred_phases[i] = [h is not None for h in hashes]
        for position, mask in masks.items():
            role = position - 1
            for j, value in enumerate(mask):
                m = 11*role + j
                if m == CLEAR_INDEX:
                    if value != 0:
                        conflicts.append(dict(counter=c, index=m, inferred=int(value), text=0))
                    continue
                if source[i, m] == TEXT_CRC:
                    same = int(label[i, m]) == int(value)
                    agreement['agree' if same else 'disagree'] += 1
                    if not same:
                        conflicts.append(dict(counter=c, index=m, inferred=int(value), text=int(label[i, m])))
                    continue
                label[i, m], source[i, m] = int(value), INFERRED
    run_id = runs_of(counters)
    text_full = (source[:, :16] == TEXT_CRC).all(axis=1)
    path = nov_dir/'nov27-receiver.npz'
    np.savez_compressed(
        path, format=FORMAT, capture='nov27-receiver', split='nov27-dev',
        group_id=np.array([f'nov27-receiver:{int(c)}' for c in counters]), counters=counters,
        frames=frames, present=present, mask_label=label, mask_source=source, labelled=text_full,
        strict=np.zeros(n, bool), inferred_phase_eligible=inferred_phases, run_id=run_id,
        note='DEVELOPMENT ONLY. Bytes with mask_source == 3 were INFERRED with FM/CD reference audio '
             '(docs/nov27-mask-validation.md); they are not ground truth.')
    receipt = dict(format=FORMAT, step='nov27', created=now(),
                   inputs=[file_record(receiver/'packets.npz'), file_record(receiver/'keys.npz'),
                           file_record(manifest_path)],
                   groups=n, text_crc_all16_groups=int(text_full.sum()),
                   inferred_bytes=int((source == INFERRED).sum()),
                   inferred_bytes_by_role={str(r): int((source[:, 11*r:11*r + 11] == INFERRED).sum()) for r in range(4)},
                   inferred_vs_text_overlap=dict(agreement), conflicts=conflicts,
                   rejected_manifest_groups={str(k): v for k, v in rejected.items()},
                   runs=run_table(counters, run_id), output=file_record(path),
                   warning='Inferred masks are development labels only (not ground truth).')
    (nov_dir/'receipt.json').write_text(json.dumps(receipt, indent=2), encoding='utf-8')
    print(json.dumps({k: receipt[k] for k in ('groups', 'text_crc_all16_groups', 'inferred_bytes',
                                              'inferred_vs_text_overlap', 'rejected_manifest_groups')}), flush=True)


# --------------------------------------------------------------------------- synthetic

def fetch(source, directory):
    """Download one source into its own new empty directory and verify the pinned hash."""
    directory.mkdir(parents=True, exist_ok=False)
    name = urllib.parse.unquote(source['url'].rsplit('/', 1)[1])
    target = directory/name
    request = urllib.request.Request(source['url'], headers={'User-Agent': 'kcbs-benchmark-builder/1'})
    with urllib.request.urlopen(request, timeout=300) as response, open(target, 'wb') as f:
        shutil.copyfileobj(response, f)
    digest = sha256_file(target)
    if source.get('sha256') and digest != source['sha256']:
        raise RuntimeError(f"{source['name']}: SHA-256 {digest} does not match pinned {source['sha256']}")
    return target


def pcm_32k(path, start=None, seconds=None):
    """Mono 32 kHz int16 PCM via FFmpeg (decode, then trim)."""
    command = ['ffmpeg', '-v', 'error', '-nostdin', '-i', str(path)]
    if start is not None:
        command += ['-ss', str(start)]
    if seconds is not None:
        command += ['-t', str(seconds)]
    command += ['-ac', '1', '-ar', '32000', '-f', 's16le', '-']
    p = subprocess.run(command, capture_output=True, timeout=600)
    if p.returncode:
        raise RuntimeError(p.stderr.decode(errors='replace')[-2000:])
    return np.frombuffer(p.stdout, '<i2').copy()


def normalise(pcm):
    """Scale to TARGET_DBFS RMS, reduced if needed to keep the peak at PEAK_DBFS."""
    x = pcm.astype(np.float64)
    rms = np.sqrt(np.mean(x**2)) or 1.0
    gain = 32768*10**(TARGET_DBFS/20)/rms
    peak = np.max(np.abs(x)) or 1.0
    gain = min(gain, 32767*10**(PEAK_DBFS/20)/peak)
    return np.clip(np.round(x*gain), -32768, 32767).astype('<i2'), 20*np.log10(gain)


def encode(pcm, workdir, tag):
    raw, stream = workdir/(tag + '.32k.raw'), workdir/(tag + '.192')
    pcm.astype('<i2').tofile(raw)
    run_tool([EVS_COD] + ENCODER_OPTIONS + [raw, stream], timeout=1800)
    raw.unlink()
    frames, supplied = read_g192(stream)
    if not supplied.all():
        raise RuntimeError(f'{tag}: encoder produced non-264-bit frames')
    return frames, stream


def source_audio(source, out, workdir):
    if source['kind'] == 'g192':
        path = ROOT/source['path']
        stream, raw = workdir/(source['name'] + '.in.192'), workdir/(source['name'] + '.in.raw')
        stream.write_bytes(gzip.decompress(path.read_bytes()))
        run_tool([EVS_DEC, '-q', '32', stream, raw])
        pcm = np.fromfile(raw, '<i2')
        stream.unlink()
        raw.unlink()
        return pcm, file_record(path)
    download = out/'sources'/source['name']
    existing = sorted(download.glob('*')) if download.exists() else []
    path = existing[0] if existing else fetch(source, download)
    if source.get('sha256') and sha256_file(path) != source['sha256']:
        raise RuntimeError(f"{path}: SHA-256 does not match the pinned value for {source['name']}")
    record = file_record(path)
    record['url'] = source['url']
    return pcm_32k(path, source.get('start'), source.get('seconds')), record


def build_synthetic(args):
    out = Path(args.out).resolve()
    syn_dir = out/'synthetic'
    streams = syn_dir/'streams'
    streams.mkdir(parents=True, exist_ok=False)
    receipt = dict(format=FORMAT, step='synthetic', created=now(), encoder=file_record(EVS_COD),
                   encoder_command='EVS_cod ' + ' '.join(ENCODER_OPTIONS) + ' <input.32k.raw> <out.192>',
                   level=dict(target_rms_dbfs=TARGET_DBFS, peak_limit_dbfs=PEAK_DBFS),
                   broadcast_census_percent=BROADCAST_CENSUS, splits={}, excluded_sources=[])
    with tempfile.TemporaryDirectory(dir=out) as tmp:
        tmp = Path(tmp)
        for split in SYNTH_SEEDS:
            rng = np.random.default_rng(SYNTH_SEEDS[split])
            rows = dict(group_id=[], source=[], frame_offset=[], plaintext=[], run_id=[])
            sources = []
            for run, source in enumerate(s for s in SOURCES if s['split'] == split):
                pcm, record = source_audio(source, out, tmp)
                pcm, gain_db = normalise(pcm)
                frames, stream = encode(pcm, streams, source['name'])
                groups = len(frames) // SLOTS
                for g in range(groups):
                    rows['group_id'].append(f"{split}:{source['name']}:{g}")
                    rows['source'].append(source['name'])
                    rows['frame_offset'].append(g*SLOTS)
                    rows['plaintext'].append(frames[g*SLOTS:(g + 1)*SLOTS])
                    rows['run_id'].append(run)
                sources.append(dict(name=source['name'], content=source['content'], licence=source.get('licence'),
                                    input=record, start=source.get('start'), seconds=source.get('seconds'),
                                    audio_seconds=round(len(pcm)/32000, 2), gain_db=round(gain_db, 2),
                                    frames=int(len(frames)), groups=groups, stream=file_record(stream),
                                    census=census(frames[:groups*SLOTS, 0])))
                print(f"[synthetic] {split} {source['name']}: {groups} groups "
                      f"{json.dumps(sources[-1]['census']['percent'])}", flush=True)
            plain = np.array(rows['plaintext'], np.uint8)
            mask = rng.integers(0, 256, (len(plain), MASK_BYTES), dtype=np.int16)
            mask[:, CLEAR_INDEX] = 0
            cipher = plain ^ expand_mask(mask)
            source_codes = np.full(mask.shape, SYNTHETIC, np.int8)
            source_codes[:, CLEAR_INDEX] = CLEAR
            path = syn_dir/f'{split}.npz'
            np.savez_compressed(
                path, format=FORMAT, capture=split, split=split, group_id=np.array(rows['group_id']),
                source=np.array(rows['source']), frame_offset=np.array(rows['frame_offset'], np.int32),
                counters=np.arange(len(plain), dtype=np.uint32), frames=cipher, plaintext=plain,
                present=np.ones(plain.shape[:2], bool), mask_label=mask, mask_source=source_codes,
                labelled=np.ones(len(plain), bool), strict=np.ones(len(plain), bool),
                run_id=np.array(rows['run_id'], np.int32), seed=SYNTH_SEEDS[split])
            receipt['splits'][split] = dict(seed=SYNTH_SEEDS[split], groups=int(len(plain)), sources=sources,
                                            census=census(plain[:, :, 0]), output=file_record(path))
            print(f"[synthetic] {split}: {len(plain)} groups, census "
                  f"{json.dumps(receipt['splits'][split]['census']['percent'])}", flush=True)
        for source in EXCLUDED_SOURCES:
            pcm, _ = normalise(pcm_32k(ROOT/source['path']))
            frames, stream = encode(pcm, tmp, source['name'])
            receipt['excluded_sources'].append(dict(source, input=file_record(ROOT/source['path']),
                                                    census=census(frames[:, 0])))
    names = [s['name'] for s in SOURCES]
    if len(set(names)) != len(names):
        raise RuntimeError('duplicate synthetic source names')
    (syn_dir/'receipt.json').write_text(json.dumps(receipt, indent=2), encoding='utf-8')


# --------------------------------------------------------------------------- task files

def split_members(out):
    """Label files per split, in a fixed order."""
    members = {}
    for capture in CAPTURES:
        members.setdefault(capture.split, []).append(out/'real'/f'{capture.id}.npz')
    for split in SYNTH_SEEDS:
        members[split] = [out/'synthetic'/f'{split}.npz']
    members['nov27-dev'] = [out/'nov27/nov27-receiver.npz']
    return members


SPLIT_TASKS = {'dev': ('T1', 'T0'), 'test': ('T1', 'T0'), 'transfer': ('T1', 'T0'),
               'syn-dev': ('T1', 'T0', 'TH'), 'syn-test': ('T1', 'T0', 'TH'), 'nov27-dev': ('T1', 'T0', 'TH')}


def task_view(label, source, labelled, present, task):
    """Visible mask (int16, -1 hidden) and target flags for one task.

    Visible bytes are the task's visible indices wherever a trusted label exists (also on
    unlabelled neighbour groups). Targets are the task's target indices on labelled groups
    where the label exists and the role has at least one received frame. For TH the
    targets are the bytes with synthetic or inferred truth.
    """
    spec = TASKS[task]
    visible = np.zeros(MASK_BYTES, bool)
    visible[spec['visible']] = True
    targets = np.zeros(MASK_BYTES, bool)
    targets[spec['targets']] = True
    known = np.where(visible & (label >= 0), label, -1).astype(np.int16)
    role_present = present.reshape(len(present), 15, 4).any(axis=1)          # (N, 4)
    role_of_index = np.repeat(np.arange(4), 11)
    has_frames = role_present[:, role_of_index]
    if task == 'TH':
        truth_ok = np.isin(source, (SYNTHETIC, INFERRED))
    else:
        truth_ok = np.isin(source, (TEXT_CRC, IDLE_CRC, SYNTHETIC))
    target = targets & (label >= 0) & truth_ok & has_frames
    if task != 'TH':
        target &= labelled[:, None]
    return known, target


def build_tasks(args):
    out = Path(args.out).resolve()
    task_dir = out/'tasks'
    task_dir.mkdir(parents=True, exist_ok=False)
    receipt = dict(format=FORMAT, step='tasks', created=now(), tasks=TASKS, files={})
    for split, paths in split_members(out).items():
        parts = [dict(np.load(p, allow_pickle=False)) for p in paths]
        cat = {k: np.concatenate([p[k] for p in parts]) for k in
               ('group_id', 'counters', 'frames', 'present', 'mask_label', 'mask_source', 'labelled', 'strict')}
        # Synthetic groups report their audio source as the capture, so per-capture
        # breakdowns are per source.
        cat['capture'] = np.concatenate([np.char.add(f"{p['capture']}:", p['source']) if 'source' in p
                                         else np.full(len(p['group_id']), str(p['capture'])) for p in parts])
        offsets = np.cumsum([0] + [int(p['run_id'].max()) + 1 for p in parts[:-1]])
        cat['run_id'] = np.concatenate([p['run_id'] + o for p, o in zip(parts, offsets)]).astype(np.int32)
        for task in SPLIT_TASKS[split]:
            known, target = task_view(cat['mask_label'], cat['mask_source'], cat['labelled'], cat['present'], task)
            base = f'{split}.{task}'
            inputs = task_dir/f'{base}.inputs.npz'
            truth = task_dir/f'{base}.truth.npz'
            np.savez_compressed(inputs, format=FORMAT, split=split, task=task, group_id=cat['group_id'],
                                capture=cat['capture'], counters=cat['counters'], run_id=cat['run_id'],
                                frames=cat['frames'], present=cat['present'], known=known, target=target,
                                labelled=cat['labelled'])
            np.savez_compressed(truth, format=FORMAT, split=split, task=task, group_id=cat['group_id'],
                                capture=cat['capture'], target=target,
                                truth=np.where(target, cat['mask_label'], -1).astype(np.int16),
                                truth_source=np.where(target, cat['mask_source'], 0).astype(np.int8),
                                strict=cat['strict'])
            receipt['files'][base] = dict(
                inputs=file_record(inputs), truth=file_record(truth), groups=int(len(target)),
                target_groups=int(target.any(axis=1).sum()), items=int(target.sum()),
                strict_items=int((target & cat['strict'][:, None]).sum()),
                items_per_index={str(m): int(target[:, m].sum()) for m in TASKS[task]['targets']})
            print(f"[tasks] {base}: {receipt['files'][base]['target_groups']} groups, "
                  f"{receipt['files'][base]['items']} items", flush=True)
    (task_dir/'receipt.json').write_text(json.dumps(receipt, indent=2), encoding='utf-8')


# --------------------------------------------------------------------------- DEV baselines

# Baselines are reported only on development-side sets; TEST, syn-test and TRANSFER
# are not scored here.
BASELINE_RUNS = ('dev.T1', 'dev.T0', 'syn-dev.TH', 'syn-dev.T1', 'syn-dev.T0', 'nov27-dev.T1', 'nov27-dev.TH')


def compact_metrics(block):
    """The headline numbers of one evaluator metrics block."""
    bits = block['bits']
    return dict(top1=block['bytes']['top1_accuracy'], topk=block['bytes']['topk_accuracy'],
                mean_rank=block['bytes']['mean_rank'], median_rank=block['bytes']['median_rank'],
                mean_log2_loss=block['bytes']['mean_log2_loss'],
                bits_at_precision={t: {k: v[k] for k in ('called', 'precision', 'threshold', 'bits_per_group')}
                                   for t, v in bits['at_precision'].items()},
                bits_at_nominal_confidence={t: {k: v[k] for k in ('called', 'precision', 'bits_per_group')}
                                            for t, v in bits['at_nominal_confidence'].items()},
                per_role_j={k: dict(top1=v['bytes']['top1_accuracy'], mean_rank=v['bytes']['mean_rank'],
                                    bits_called_at_98=v['bits']['at_precision']['0.98']['called'])
                            for k, v in block.get('per_role_j', {}).items()})


def build_baselines(args):
    out = Path(args.out).resolve()
    base = out/'baselines'
    base.mkdir(parents=True, exist_ok=False)
    prior = [str(out/'real'/f'{c.id}.npz') for c in CAPTURES if c.split == 'dev']
    summary = dict(format=FORMAT, created=now(), evaluator=file_record(ROOT/'scripts/eval_mask_predictions.py'),
                   prior_training=[rel(p) for p in prior],
                   note='Uniform and mode-conditioned per-bit prior baselines on development-side sets only. '
                        'DEV items are scored with their own capture left out of the prior.', runs={})
    for run in BASELINE_RUNS:
        report = base/f'{run}.json'
        command = [sys.executable, str(ROOT/'scripts/eval_mask_predictions.py'), '--truth', str(out/'tasks'/f'{run}.truth.npz'),
                   '--prior-train', *prior, '--write-baseline-predictions', str(base/'predictions'), '--out', str(report)]
        p = subprocess.run(command, capture_output=True, text=True, timeout=3600)
        if p.returncode:
            raise RuntimeError(p.stderr[-2000:])
        doc = json.loads(report.read_text(encoding='utf-8'))
        row = dict(items=doc['items'], groups=doc['groups'], report=file_record(report))
        for name, block in doc['metrics']['baselines'].items():
            row[name] = compact_metrics(block)
            if 'strict_subset' in block:
                row[name]['strict_subset'] = dict(items=block['strict_subset']['items'],
                                                  **{k: v for k, v in compact_metrics(block['strict_subset']).items()
                                                     if k != 'per_role_j'})
        summary['runs'][run] = row
        print(p.stdout.strip(), flush=True)
    path = ROOT/DOC_DIR/'baselines-dev.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, indent=2) + '\n', encoding='utf-8')
    print(f'wrote {rel(path)}', flush=True)


# --------------------------------------------------------------------------- registration

def git_head():
    p = subprocess.run(['git', '-C', str(ROOT), 'rev-parse', 'HEAD'], capture_output=True, text=True)
    return p.stdout.strip() or None


def build_register(args):
    out = Path(args.out).resolve()
    doc = ROOT/DOC_DIR
    doc.mkdir(parents=True, exist_ok=True)
    real = json.loads((out/'real/receipt.json').read_text(encoding='utf-8'))
    syn = json.loads((out/'synthetic/receipt.json').read_text(encoding='utf-8'))
    nov = json.loads((out/'nov27/receipt.json').read_text(encoding='utf-8'))
    tasks = json.loads((out/'tasks/receipt.json').read_text(encoding='utf-8'))
    splits = {}
    for capture in real['captures']:
        s = splits.setdefault(capture['split'], dict(kind='real', captures=[]))
        s['captures'].append(dict(id=capture['id'], inputs=capture['inputs'],
                                  keys=capture.get('keys'), groups=capture['groups'],
                                  labelled=capture['labelled'], strict=capture['strict'],
                                  label_check={k: v for k, v in capture['label_check'].items() if k != 'rule'},
                                  output=capture['output']))
    for name, info in syn['splits'].items():
        splits[name] = dict(kind='synthetic', seed=info['seed'], groups=info['groups'], output=info['output'],
                            sources=[dict(name=s['name'], content=s['content'], input=s['input'],
                                          start=s['start'], seconds=s['seconds'], groups=s['groups'])
                                     for s in info['sources']])
    splits['nov27-dev'] = dict(kind='inferred (development only)', inputs=nov['inputs'], output=nov['output'],
                               groups=nov['groups'], warning=nov['warning'])
    sealed = {'test': 'sealed: final verification only', 'syn-test': 'sealed: final verification only'}
    for name, s in splits.items():
        s['use'] = sealed.get(name, 'development' if name in ('dev', 'syn-dev', 'nov27-dev') else
                              'transfer check (different month, idle-tail labels)')
    receipts = {name: file_record(out/name/'receipt.json') for name in ('real', 'synthetic', 'nov27', 'tasks')}
    protocol = doc/'protocol.md'
    registration = dict(
        format=FORMAT, registered=now(), git_head=git_head(),
        builder=file_record(ROOT/'scripts/build_mask_benchmark.py'),
        evaluator=file_record(ROOT/'scripts/eval_mask_predictions.py'),
        protocol=file_record(protocol) if protocol.exists() else None,
        baselines=file_record(doc/'baselines-dev.json') if (doc/'baselines-dev.json').exists() else None,
        label_check_rule=real['captures'][0]['label_check']['rule'],
        tools=dict(stock_decoder=file_record(EVS_DEC), stock_encoder=file_record(EVS_COD),
                   decoder_check_build=real['decoder_check_build']),
        layout=dict(slot='20*phase + 4*cycle + (position-1)', role='slot % 4',
                    frame='33 bytes: mode byte + 32 payload bytes, ciphertext as received',
                    mask_index='11*role + j -> payload byte 3j (frame byte 1+3j) of the 15 frames of that role',
                    clear_index=CLEAR_INDEX, unknown=-1, provenance_codes=PROVENANCE),
        tasks=TASKS, split_tasks={k: list(v) for k, v in SPLIT_TASKS.items()}, splits=splits,
        task_files=tasks['files'], receipts=receipts)
    (doc/'split.json').write_text(json.dumps(registration, indent=2) + '\n', encoding='utf-8')
    print(f'wrote {rel(doc/"split.json")}', flush=True)


def now():
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('step', choices=('real', 'nov27', 'synthetic', 'tasks', 'baselines', 'register', 'all'))
    ap.add_argument('--out', default=DEFAULT_OUT, help='benchmark directory (default %(default)s)')
    ap.add_argument('--workers', type=int, default=os.cpu_count() or 1, help='parallel decoder processes')
    ap.add_argument('--max-label-flags', type=int, default=0,
                    help='drop a label whose role-0 frames raise more decoder flags than this')
    a = ap.parse_args()
    a.out = str((ROOT/a.out).resolve())
    steps = ('real', 'nov27', 'synthetic', 'tasks', 'baselines', 'register') if a.step == 'all' else (a.step,)
    for step in steps:
        dict(real=build_real, nov27=build_nov27, synthetic=build_synthetic, tasks=build_tasks,
             baselines=build_baselines, register=build_register)[step](a)


if __name__ == '__main__':
    main()
