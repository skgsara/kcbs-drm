"""Python client for the persistent, exact EVS candidate decoder.

The decoder process (scripts/evs_candidate_decoder.c, built into
work/evs_candidate/evs_candidate_decoder by scripts/build_evs_candidate_decoder.py)
holds one committed EVS decoder state.  FEED decodes and commits frames; EVAL
decodes K alternative frame sequences from the current state without changing it,
in parallel, using fork() snapshots.  Every PCM sample is bit-identical to
decoding the corresponding full stream from scratch with
'EVS_dec -q -no_delay_cmp <rate_khz> in.192 out.raw'.

Frames are 264-bit EVS 13.2 kbps frames given as (..., 33) uint8 arrays
(mode byte + 32 payload bytes, bits MSB first); `good` flags mark received
frames, erased frames are sent as G.192 bad frames of length 0.

    with CandidateDecoder(rate=16000) as dec:
        dec.feed(history_frames, history_good)            # commit the past
        cands, good = role_byte_candidates(group, mask, known, role=1, j=5)
        res = dec.eval(cands, good)                       # 256 x 60 frames
        res.pcm[k], res.diag[k]['bfi_out'], res.status[k]

Group helpers model the KCBS-2 masking: within a 1.2 s group of 60 frames, frame
f has role f % 4; payload byte 3j (frame byte 1+3j, j = 0..10) of every role-r
frame is XORed with mask byte ks[11r + j] (`mask[r, j]` here).
"""
from dataclasses import dataclass
import os
from pathlib import Path
import struct
import subprocess

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BINARY = ROOT/'work/evs_candidate/evs_candidate_decoder'

FRAME_BITS = 264
FRAME_BYTES = 33            # mode byte + 32 payload bytes
GROUP_FRAMES = 60
ROLES = 4
MASK_BYTES = 11             # mask bytes per role (payload bytes 0, 3, ..., 30)
KEYED = np.arange(0, 32, 3)   # payload byte offset of mask byte j

CMD_INIT, CMD_FEED, CMD_EVAL, CMD_CHECKPOINT, CMD_RESTORE, CMD_DROP, CMD_INFO, CMD_QUIT = range(1, 9)
PROTOCOL_VERSION = 1

#: per-frame diagnostics; see the header of scripts/evs_candidate_decoder.c for
#: where in the reference decoder each field comes from.
DIAG_DTYPE = np.dtype([
    ('bfi_in', '<i2'), ('bfi_out', '<i2'), ('ber_detect', '<i2'),
    ('codec_mode_in', '<i2'), ('codec_mode', '<i2'), ('core', '<i2'),
    ('coder_type', '<i2'), ('bwidth', '<i2'), ('extl', '<i2'), ('L_frame', '<i2'),
    ('next_bit_pos', '<i2'), ('nbits', '<i2'), ('clas_dec', '<i2'),
    ('hq_core_type', '<i2'), ('mdct_sw', '<i2'), ('m_frame_type', '<i2'),
    ('clip_count', '<i2'), ('cng', '<i2'),
    ('total_brate', '<i4'), ('core_brate', '<i4'), ('peak', '<f4')])
assert DIAG_DTYPE.itemsize == 48

CORE_NAMES = {0: 'ACELP', 1: 'TCX20', 2: 'TCX10', 3: 'HQ', 4: 'AMRWB'}
CODER_TYPE_NAMES = {0: 'INACTIVE', 1: 'UNVOICED', 2: 'VOICED', 3: 'GENERIC',
                    4: 'TRANSITION', 5: 'AUDIO', 6: 'LR_MDCT'}
#: diag['m_frame_type'] holds the reference's unsigned char codes (lib_com/cnst.h)
M_FRAME_TYPE_NAMES = {0xF0: 'ZERO', 0xFA: 'SID', 0xFF: 'ACTIVE'}

STATUS_OK = 0
STATUS_SIGNAL = 0x100
STATUS_EXIT = 0x200
STATUS_NOT_RUN = 0x300


class DecoderError(RuntimeError):
    """The decoder process reported an error or went away."""


@dataclass
class EvalResult:
    """EVAL output: K candidates of N frames."""
    pcm: object            # (K, N, L) int16, or None when pcm=False
    diag: np.ndarray       # (K, N) DIAG_DTYPE
    status: np.ndarray     # (K,) int32; 0 = decoded, else 0x100|signal, 0x200|exit code
    prefix: int            # leading frames shared by all candidates (decoded once)


# --------------------------------------------------------------------------
# frames and the wire format
# --------------------------------------------------------------------------

def make_frames(mode, payload):
    """264-bit frames (..., 33) from mode byte(s) (...) and payload bytes (..., 32)."""
    payload = np.asarray(payload, np.uint8)
    if payload.shape[-1] != FRAME_BYTES - 1:
        raise ValueError('payload must have 32 bytes in its last axis')
    mode = np.broadcast_to(np.asarray(mode, np.uint8), payload.shape[:-1])
    return np.concatenate([mode[..., None], payload], axis=-1)


def _frames_and_flags(frames, good):
    frames = np.ascontiguousarray(frames, np.uint8)
    if frames.shape[-1] != FRAME_BYTES:
        raise ValueError('frames must be (..., 33) uint8 (264-bit EVS frames)')
    lead = frames.shape[:-1]
    good = np.ones(lead, bool) if good is None else np.broadcast_to(np.asarray(good, bool), lead)
    return frames.reshape(-1, FRAME_BYTES), np.ascontiguousarray(good).reshape(-1), lead


def encode_frames(frames, good=None):
    """Wire records for (..., 33) frames: good -> G.192 0x6B21/264 bits, erased -> 0x6B20/0 bits."""
    flat, ok, _ = _frames_and_flags(frames, good)
    rec = np.zeros((len(flat), 4 + FRAME_BYTES), np.uint8)
    rec[:, 0] = ~ok
    rec[ok, 2] = FRAME_BITS & 0xff
    rec[ok, 3] = FRAME_BITS >> 8
    rec[:, 4:] = flat
    keep = np.ones(rec.shape, bool)
    keep[~ok, 4:] = False
    return rec[keep].tobytes()


def read_g192(path):
    """(frames (n, 33) uint8, good (n,) bool) from a G.192 file of 264-bit / empty frames."""
    words = np.fromfile(path, '<u2')
    frames, good, i = [], [], 0
    while i < len(words):
        sync, nbits = int(words[i]), int(words[i + 1])
        bits = words[i + 2:i + 2 + nbits]
        i += 2 + nbits
        if sync not in (0x6B21, 0x6B20) or nbits not in (0, FRAME_BITS):
            raise ValueError('%s: unsupported G.192 frame (sync %#x, %d bits)' % (path, sync, nbits))
        if nbits == 0 and sync == 0x6B21:
            raise ValueError('%s: good NO_DATA frames are not supported' % path)
        good.append(sync == 0x6B21 and nbits == FRAME_BITS)
        frames.append(np.packbits(bits == 0x81) if nbits else np.zeros(FRAME_BYTES, np.uint8))
    return np.array(frames, np.uint8).reshape(-1, FRAME_BYTES), np.array(good, bool)


def write_g192(path, frames, good=None):
    """Write frames as G.192 (good: 0x6B21 + 264 words 0x81/0x7F, erased: 0x6B20 + length 0)."""
    flat, ok, _ = _frames_and_flags(frames, good)
    out = []
    for f, g in zip(flat, ok):
        if g:
            out.append(np.array([0x6B21, FRAME_BITS], '<u2'))
            out.append(np.where(np.unpackbits(f), 0x81, 0x7F).astype('<u2'))
        else:
            out.append(np.array([0x6B20, 0], '<u2'))
    Path(path).write_bytes(np.concatenate(out).tobytes() if out else b'')


# --------------------------------------------------------------------------
# KCBS-2 group masking helpers
# --------------------------------------------------------------------------

def _as_mask(mask, known):
    mask = np.asarray(mask, np.uint8).reshape(ROLES, MASK_BYTES)
    known = np.asarray(known, bool).reshape(ROLES, MASK_BYTES)
    return mask, known


def apply_role_mask(frames, role, j, value):
    """Copy of a group's frames (..., 60, 33) with `value` XORed into payload byte 3j
    (frame byte 1+3j) of every frame of `role` (frame index % 4 == role)."""
    out = np.array(frames, np.uint8, copy=True)
    out[..., role::ROLES, 1 + KEYED[j]] ^= np.uint8(value)
    return out


def known_mask_from_text(ks16):
    """(mask (4, 11), known (4, 11)) from ks[0..15] recovered via the 16-byte text tail:
    role 0 j=0..10 and role 1 j=0..4 known; role 3 j=10 is clear (mask 0, known)."""
    ks = np.zeros(ROLES*MASK_BYTES, np.uint8)
    known = np.zeros(ROLES*MASK_BYTES, bool)
    ks[:16] = np.asarray(ks16, np.uint8)[:16]
    known[:16] = True
    known[3*MASK_BYTES + 10] = True
    return ks.reshape(ROLES, MASK_BYTES), known.reshape(ROLES, MASK_BYTES)


def unmask_group(frames, mask, known):
    """Copy of a group's received frames (60, 33) with every KNOWN mask byte removed."""
    mask, known = _as_mask(mask, known)
    out = np.array(frames, np.uint8, copy=True)
    for r in range(ROLES):
        cols = 1 + KEYED[known[r]]
        out[r::ROLES, cols] ^= mask[r, known[r]]
    return out


def role_byte_candidates(frames, mask, known, role, j, good=None, erase_roles='unknown',
                         values=None):
    """Candidate 60-frame sequences for mask byte (role, j) of one group.

    frames  (60, 33) received frames (mode byte + 32 masked payload bytes)
    mask, known  (4, 11) (or (44,)) mask bytes ks[11r+j] and which of them are known
    good    (60,) received flags (default all good)
    erase_roles  'unknown': erase the frames of every OTHER role that still has an
            unknown mask byte; or an explicit iterable of roles to erase; () for none
    values  candidate byte values (default 0..255)

    Every known mask byte is removed; candidate v additionally removes values[v] at
    (role, j).  Unknown bytes of `role` itself (other than j) are left as received.
    Returns (candidates (V, 60, 33) uint8, good (V, 60) bool).
    """
    frames = np.asarray(frames, np.uint8)
    if frames.shape != (GROUP_FRAMES, FRAME_BYTES):
        raise ValueError('frames must be (60, 33)')
    mask, known = _as_mask(mask, known)
    values = np.arange(256, dtype=np.uint8) if values is None else np.asarray(values, np.uint8)
    flags = np.ones(GROUP_FRAMES, bool) if good is None else np.asarray(good, bool).copy()
    base_known = known.copy()
    base_known[role, j] = False
    base = unmask_group(frames, mask, base_known)
    if isinstance(erase_roles, str):
        if erase_roles != 'unknown':
            raise ValueError("erase_roles must be 'unknown' or an iterable of roles")
        erase_roles = [r for r in range(ROLES) if r != role and not known[r].all()]
    for r in erase_roles:
        flags[r::ROLES] = False
    cands = np.repeat(base[None], len(values), axis=0)
    cands[:, role::ROLES, 1 + KEYED[j]] ^= values[:, None]
    return cands, np.repeat(flags[None], len(values), axis=0)


def group_frames_from_du(du_row):
    """(60, 33) frames of one group from its three 716-byte data units (3, 716)."""
    from render_continuous import MODE_POSITIONS, PACKET_STARTS
    du_row = np.asarray(du_row, np.uint8)
    out = np.zeros((GROUP_FRAMES, FRAME_BYTES), np.uint8)
    for phase in range(3):
        for k, (begin, mode_byte) in enumerate(zip(PACKET_STARTS, MODE_POSITIONS)):
            out[phase*20 + k, 0] = du_row[phase, mode_byte]
            out[phase*20 + k, 1:] = du_row[phase, begin:begin + 32]
    return out


# --------------------------------------------------------------------------
# the decoder process
# --------------------------------------------------------------------------

class CandidateDecoder:
    """A persistent candidate-decoder process with one committed EVS state.

    rate             output sampling rate (8000, 16000, 32000 or 48000)
    jobs             parallel EVAL children (default: CPUs available to the process)
    first_good_bits  length of the stream's first good frame (io_ini_dec probe; 264)
    timeout          watchdog seconds per EVAL candidate (status 0x100|SIGALRM); 0 = none
    quiet            send the reference library's warnings to /dev/null
    """

    def __init__(self, rate=16000, binary=None, jobs=None, first_good_bits=FRAME_BITS,
                 timeout=120, quiet=True):
        self.binary = Path(binary) if binary else DEFAULT_BINARY
        if not self.binary.exists():
            raise FileNotFoundError('%s not built; run scripts/build_evs_candidate_decoder.py'
                                    % self.binary)
        argv = [str(self.binary), '--timeout', str(int(timeout))]
        argv += ['--jobs', str(int(jobs))] if jobs else []
        self._proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                      stderr=subprocess.DEVNULL if quiet else None)
        self.first_good_bits = first_good_bits
        self.reset(rate)

    # -- transport ----------------------------------------------------------
    def _send(self, cmd, payload=b''):
        if self._proc is None:
            raise DecoderError('decoder closed')
        try:
            self._proc.stdin.write(struct.pack('<II', cmd, len(payload)))
            self._proc.stdin.write(payload)
            self._proc.stdin.flush()
        except BrokenPipeError as e:
            raise DecoderError('decoder process exited') from e

    def _read(self, n):
        buf = bytearray(n)
        view, got = memoryview(buf), 0
        while got < n:
            k = self._proc.stdout.readinto(view[got:])
            if not k:
                raise DecoderError('decoder process exited')
            got += k
        return buf

    def _call(self, cmd, payload=b''):
        self._send(cmd, payload)
        status, length = struct.unpack('<II', self._read(8))
        body = self._read(length)
        if status:
            raise DecoderError(body.decode('utf-8', 'replace'))
        return body

    # -- commands -----------------------------------------------------------
    def reset(self, rate=None):
        """INIT: fresh decoder state at `rate` (drops the base state and all checkpoints)."""
        rate = int(rate or self.rate)
        body = self._call(CMD_INIT, struct.pack('<II', rate, self.first_good_bits))
        (version, self.rate, self.output_frame, self.dec_delay, diag_size, self.jobs,
         self.state_bytes) = struct.unpack('<7I', body[:28])
        if version != PROTOCOL_VERSION or diag_size != DIAG_DTYPE.itemsize:
            raise DecoderError('protocol mismatch: version %d, diag %d bytes' % (version, diag_size))
        return self

    def feed(self, frames, good=None):
        """Decode and COMMIT frames (n, 33).  Returns (pcm (n, L) int16, diag (n,))."""
        flat, ok, _ = _frames_and_flags(frames, good)
        body = self._call(CMD_FEED, struct.pack('<I', len(flat)) + encode_frames(flat, ok))
        n, L = struct.unpack('<II', body[:8])
        pcm = np.frombuffer(body, '<i2', n*L, 8).reshape(n, L)
        diag = np.frombuffer(body, DIAG_DTYPE, n, 8 + 2*n*L)
        return pcm, diag

    def eval(self, candidates, good=None, pcm=True):
        """Decode candidates (K, N, 33) from the current state without changing it.

        good: (K, N), (N,) or None.  pcm=False returns diagnostics only (faster I/O).
        """
        cands = np.asarray(candidates, np.uint8)
        if cands.ndim != 3 or cands.shape[2] != FRAME_BYTES:
            raise ValueError('candidates must be (K, N, 33)')
        K, N = cands.shape[:2]
        flat, ok, _ = _frames_and_flags(cands, good)
        payload = struct.pack('<III', K, N, 0 if pcm else 1) + encode_frames(flat, ok)
        body = self._call(CMD_EVAL, payload)
        k, n, L, prefix, diag_size = struct.unpack('<5I', body[:20])
        assert (k, n, diag_size) == (K, N, DIAG_DTYPE.itemsize)
        off = 20
        status = np.frombuffer(body, '<i4', K, off)
        off += 4*K
        out = None
        if L:
            out = np.frombuffer(body, '<i2', K*N*L, off).reshape(K, N, L)
            off += 2*K*N*L
        diag = np.frombuffer(body, DIAG_DTYPE, K*N, off).reshape(K, N)
        return EvalResult(out, diag, status, prefix)

    def checkpoint(self, name):
        """Snapshot the current base state under `name` (replaces an existing one)."""
        self._call(CMD_CHECKPOINT, name.encode())

    def restore(self, name):
        """Make a copy of checkpoint `name` the base state (the checkpoint stays)."""
        self._call(CMD_RESTORE, name.encode())

    def drop(self, name):
        """Forget checkpoint `name`."""
        self._call(CMD_DROP, name.encode())

    def info(self):
        """Dict with version, initialised, rate, jobs, frames_committed, checkpoints."""
        body = self._call(CMD_INFO)
        version, initialised, rate, jobs, committed, n = struct.unpack('<4IQI', body[:28])
        names = [bytes(body[28 + 64*i:28 + 64*(i+1)]).rstrip(b'\0').decode() for i in range(n)]
        return dict(version=version, initialised=bool(initialised), rate=rate, jobs=jobs,
                    frames_committed=committed, checkpoints=names)

    def close(self):
        if self._proc is None:
            return
        try:
            self._call(CMD_QUIT)
        except (DecoderError, OSError):
            pass
        for stream in (self._proc.stdin, self._proc.stdout):
            try:
                stream.close()
            except OSError:
                pass
        try:
            self._proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self._proc.kill()
            self._proc.wait()
        self._proc = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass


def binary_available(binary=None):
    """True if the candidate decoder binary exists and this OS can run it."""
    return os.name == 'posix' and Path(binary or DEFAULT_BINARY).exists()
