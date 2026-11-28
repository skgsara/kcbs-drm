#!/usr/bin/env python3
"""Mask-byte recovery by ACOUSTIC CONTINUITY of the exact decoded EVS output (method 'acoustic').

For every target mask byte (group, role r, byte j) all 256 values are tried with the exact
fork-snapshot EVS decoder (scripts/evs_candidates.py) from a checkpoint at the group start
(after warming up on the two preceding groups of the same run with their visible bytes; frames of
roles with unknown bytes are erased).  Each candidate's 32 kHz output is scored by how
continuously the 15 frames of role r join their neighbours: half-frame log-mel spectral flux at
the frame boundaries (low band < 8 kHz and SWB high band separately), log-mel distance to the
nearest exactly known frames (anchors: role-0 frames and the next group's first frame), energy
jumps, boundary click energy, continuity of the concealed span up to the next anchor, and cheap
decoder flags (bfi, BER, bit-position mismatch, clipping), each summed over the role's frames per
frame class (ACELP / TCX / HQ).  The features are standardised over the 256 candidates of the byte
and combined linearly (conditional logit) with weights fitted on DEV (T1) / syn-dev (TH).

JOINT search.  The bytes of one role are estimated in bitstream order (j = 0, 1, ...): byte j is
scored with the bytes before it fixed at their current best value ('fwd' stage), because a byte
affects the fields from bit 8 + 24 j onward and a wrong earlier byte garbles the frame.  Then up to
`refine` Gauss-Seidel passes re-score every byte with all other bytes of the role fixed ('ref'
stage); passes stop when no best value changes (identical contexts are cached, never re-decoded).
Roles are solved in order 0..3; frames of other roles that still have unknown bytes stay erased.

The script reads only <split>.<task>.inputs.npz.  It never reads truth files.

    python3 scripts/mask_method_acoustic.py --inputs work/benchmark/tasks/dev.T1.inputs.npz \
        --out work/methods/acoustic/dev.T1.pred.npz [--groups 80 --seed 101] [--exclude train.txt]
"""
import argparse
import json
import os
from pathlib import Path
import sys
import time

# Single-threaded BLAS: the per-candidate matrix products are tiny, and multi-threaded BLAS on a
# busy shared machine was measured ~700x slower for them (the decoder already runs in parallel).
for _v in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS'):
    os.environ[_v] = '1'

import numpy as np  # noqa: E402

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from evs_candidates import CandidateDecoder, role_byte_candidates, unmask_group  # noqa: E402

PREDICTION_FORMAT = 'kcbs-mask-predictions/1'
METHOD = 'acoustic-continuity'
RATE = 32000
FRAME = RATE // 50            # 640 output samples per EVS frame
BLOCK = FRAME // 2            # half-frame analysis blocks (10 ms)
NFFT = 512
NBANDS = 40
HI_HZ = 8000.0                # SWB high band starts here
WARMUP_GROUPS = 2
TAIL_FRAMES = 4               # first frames of the next group appended after frame 59
ROLES, MB = 4, 11
CLASSES = ('acelp', 'tcx', 'hq')

BASE_FEATURES = ('flux_in_lo', 'flux_in_hi', 'flux_mid_lo', 'flux_mid_hi', 'flux_out_lo', 'flux_out_hi',
                 'tail_lo', 'tail_hi', 'dprev_lo', 'dprev_hi', 'dnext_lo', 'dnext_hi',
                 'e_in', 'abs_e_in', 'e_out', 'abs_e_out', 'e_rel', 'abs_e_rel', 'click_in', 'click_out',
                 'bfi', 'ber', 'bitpos', 'clip', 'e_abs', 'tail_e_rel', 'hi_lo_shift')
FEATURE_NAMES = tuple(f'{c}:{f}' for c in CLASSES for f in BASE_FEATURES) + ('status_bad',)
NF = len(FEATURE_NAMES)
Z_CLIP = 6.0

# Model weights (conditional logit over standardised features).  None = load from --model.
FROZEN_MODEL = json.loads(r'''{"tasks":{"T1":
{"config":{"extra":false,"refine":3,"keep_other":false},"weights":{"fwd":[-0.089783,-0.230618,-0.142473,-0.032072,-0.215397,0.046974,-0.010045,-0.101503,-0.130844,0.05579,-0.207344,-0.090326,-0.152888,0.296092,-0.300868,-0.14825,0.03224,-0.042612,0.029026,-0.087522,-0.501072,-0.10101,-0.575206,-0.090782,-0.194901,0.020895,-0.166267,-0.068329,-0.137369,-0.370111,-0.372332,0.036474,-0.204433,-0.321037,0.028871,-0.312531,-0.013526,-0.166614,-0.384086,-0.194776,0.01969,-0.063659,0.138025,-0.482628,-0.0198,0.122054,-0.069982,-0.437436,-0.273626,-0.533807,-0.206341,0.347713,0.093239,-0.157431,-0.2325,-0.175259,-0.477599,-0.191418,-0.204909,-0.068354,-0.091099,0.001547,-0.077765,-0.037419,-0.282513,-0.108931,-0.22835,0.06262,0.019637,0.050278,0.084655,-0.239049,0.155931,-0.00827,0.0,-0.054039,-0.063127,-0.105264,0.073924,0.010964,0.312291,0.0],"ref":[-0.122445,-0.195866,-0.287186,-0.028145,-0.09358,0.152736,-0.123059,-0.120412,-0.153941,0.026707,-0.034411,-0.013901,0.027785,0.08132,-0.103472,-0.145389,0.16594,-0.095805,-0.038069,-0.067318,-0.717961,-0.093005,-0.78236,-0.036323,-0.239379,-0.145613,-0.138907,0.016242,-0.217842,-0.379179,-0.368944,0.188068,0.059786,-0.361172,-0.24821,-0.318762,0.154013,-0.154347,-0.33468,-0.072038,-0.042017,-0.097932,0.116414,-0.54619,0.034673,-0.122475,-0.154413,-0.555562,-0.276212,-0.479843,-0.172911,0.489049,-0.021499,-0.138359,-0.26652,0.081094,-0.300087,-0.406574,0.133602,0.102019,-0.139755,-0.236104,-0.253769,-0.09426,-0.182838,-0.334852,-0.231988,0.041975,-0.026738,-0.103567,-0.03588,-0.470575,0.023645,0.091055,0.0,-0.330799,-0.34043,0.163813,-0.124358,-0.087191,-0.008991,0.0],"default":[-0.089783,-0.230618,-0.142473,-0.032072,-0.215397,0.046974,-0.010045,-0.101503,-0.130844,0.05579,-0.207344,-0.090326,-0.152888,0.296092,-0.300868,-0.14825,0.03224,-0.042612,0.029026,-0.087522,-0.501072,-0.10101,-0.575206,-0.090782,-0.194901,0.020895,-0.166267,-0.068329,-0.137369,-0.370111,-0.372332,0.036474,-0.204433,-0.321037,0.028871,-0.312531,-0.013526,-0.166614,-0.384086,-0.194776,0.01969,-0.063659,0.138025,-0.482628,-0.0198,0.122054,-0.069982,-0.437436,-0.273626,-0.533807,-0.206341,0.347713,0.093239,-0.157431,-0.2325,-0.175259,-0.477599,-0.191418,-0.204909,-0.068354,-0.091099,0.001547,-0.077765,-0.037419,-0.282513,-0.108931,-0.22835,0.06262,0.019637,0.050278,0.084655,-0.239049,0.155931,-0.00827,0.0,-0.054039,-0.063127,-0.105264,0.073924,0.010964,0.312291,0.0]},"lam":10.0},"TH":
{"config":{"extra":false,"refine":1,"keep_other":false},"weights":{"fwd":[0.011915,-0.108373,-0.072537,-0.053864,-0.181717,-0.018691,-0.056042,-0.108325,-0.235054,-0.019773,-0.030297,-0.014281,-0.035833,0.033388,-0.027657,-0.007731,0.022329,-0.106963,0.012499,0.147666,-0.192374,-0.109412,-0.282185,-0.103113,0.056174,0.031397,-0.119596,-0.090571,-0.05346,-0.127887,-0.10014,-0.128742,0.040121,-0.107135,0.061326,-0.051902,-0.010413,-0.068141,-0.098757,-0.202333,-0.069863,0.280962,-0.140247,0.035648,0.023331,-0.021824,0.089299,-0.305755,-0.13673,-0.16753,-0.088829,0.29737,0.071004,-0.036519,0.070114,-0.147177,-0.181871,-0.119379,0.02251,-0.1654,-0.048022,0.013528,-0.002207,0.017787,0.079788,-0.190309,-0.033785,-0.086802,0.008334,0.085198,-0.02089,-0.021064,-0.136202,0.015851,0.0,-0.09042,-0.090859,-0.072773,0.147283,0.139924,-0.096469,0.0],"ref":[-0.150885,-0.061833,-0.065383,-0.07126,-0.245622,-0.140423,-0.123508,-0.196455,-0.213494,-0.231631,-0.004132,0.033036,-0.072352,0.157362,-0.03835,-0.114878,-0.004837,-0.071768,0.063031,0.065453,-0.245774,-0.09989,-0.304493,0.052996,-0.041319,-0.080203,-0.046418,-0.017228,0.010067,-0.205253,0.121413,0.096672,0.014986,0.03085,0.102013,-0.154234,-0.076353,-0.131295,-0.061123,0.025011,0.030113,0.06415,-0.09701,-0.023842,-0.124202,0.078387,-0.176683,-0.237323,-0.359933,-0.241005,0.008722,0.222669,0.038387,-0.061766,0.057949,-0.29617,-0.18953,-0.150004,0.026485,-0.068699,-0.146825,0.095068,-0.058337,0.097044,-0.023835,-0.049292,-0.151908,-0.010196,-0.083892,-0.100734,0.101404,-0.080285,0.046388,0.104463,0.0,-0.217954,-0.218199,-0.117061,-0.033939,0.057489,-0.006548,0.0],"default":[0.011915,-0.108373,-0.072537,-0.053864,-0.181717,-0.018691,-0.056042,-0.108325,-0.235054,-0.019773,-0.030297,-0.014281,-0.035833,0.033388,-0.027657,-0.007731,0.022329,-0.106963,0.012499,0.147666,-0.192374,-0.109412,-0.282185,-0.103113,0.056174,0.031397,-0.119596,-0.090571,-0.05346,-0.127887,-0.10014,-0.128742,0.040121,-0.107135,0.061326,-0.051902,-0.010413,-0.068141,-0.098757,-0.202333,-0.069863,0.280962,-0.140247,0.035648,0.023331,-0.021824,0.089299,-0.305755,-0.13673,-0.16753,-0.088829,0.29737,0.071004,-0.036519,0.070114,-0.147177,-0.181871,-0.119379,0.02251,-0.1654,-0.048022,0.013528,-0.002207,0.017787,0.079788,-0.190309,-0.033785,-0.086802,0.008334,0.085198,-0.02089,-0.021064,-0.136202,0.015851,0.0,-0.09042,-0.090859,-0.072773,0.147283,0.139924,-0.096469,0.0]},"lam":30.0},"T0":
{"config":{"extra":false,"refine":1,"keep_other":false},"weights":{"fwd":[-0.089783,-0.230618,-0.142473,-0.032072,-0.215397,0.046974,-0.010045,-0.101503,-0.130844,0.05579,-0.207344,-0.090326,-0.152888,0.296092,-0.300868,-0.14825,0.03224,-0.042612,0.029026,-0.087522,-0.501072,-0.10101,-0.575206,-0.090782,-0.194901,0.020895,-0.166267,-0.068329,-0.137369,-0.370111,-0.372332,0.036474,-0.204433,-0.321037,0.028871,-0.312531,-0.013526,-0.166614,-0.384086,-0.194776,0.01969,-0.063659,0.138025,-0.482628,-0.0198,0.122054,-0.069982,-0.437436,-0.273626,-0.533807,-0.206341,0.347713,0.093239,-0.157431,-0.2325,-0.175259,-0.477599,-0.191418,-0.204909,-0.068354,-0.091099,0.001547,-0.077765,-0.037419,-0.282513,-0.108931,-0.22835,0.06262,0.019637,0.050278,0.084655,-0.239049,0.155931,-0.00827,0.0,-0.054039,-0.063127,-0.105264,0.073924,0.010964,0.312291,0.0],"ref":[-0.122445,-0.195866,-0.287186,-0.028145,-0.09358,0.152736,-0.123059,-0.120412,-0.153941,0.026707,-0.034411,-0.013901,0.027785,0.08132,-0.103472,-0.145389,0.16594,-0.095805,-0.038069,-0.067318,-0.717961,-0.093005,-0.78236,-0.036323,-0.239379,-0.145613,-0.138907,0.016242,-0.217842,-0.379179,-0.368944,0.188068,0.059786,-0.361172,-0.24821,-0.318762,0.154013,-0.154347,-0.33468,-0.072038,-0.042017,-0.097932,0.116414,-0.54619,0.034673,-0.122475,-0.154413,-0.555562,-0.276212,-0.479843,-0.172911,0.489049,-0.021499,-0.138359,-0.26652,0.081094,-0.300087,-0.406574,0.133602,0.102019,-0.139755,-0.236104,-0.253769,-0.09426,-0.182838,-0.334852,-0.231988,0.041975,-0.026738,-0.103567,-0.03588,-0.470575,0.023645,0.091055,0.0,-0.330799,-0.34043,0.163813,-0.124358,-0.087191,-0.008991,0.0],"default":[-0.089783,-0.230618,-0.142473,-0.032072,-0.215397,0.046974,-0.010045,-0.101503,-0.130844,0.05579,-0.207344,-0.090326,-0.152888,0.296092,-0.300868,-0.14825,0.03224,-0.042612,0.029026,-0.087522,-0.501072,-0.10101,-0.575206,-0.090782,-0.194901,0.020895,-0.166267,-0.068329,-0.137369,-0.370111,-0.372332,0.036474,-0.204433,-0.321037,0.028871,-0.312531,-0.013526,-0.166614,-0.384086,-0.194776,0.01969,-0.063659,0.138025,-0.482628,-0.0198,0.122054,-0.069982,-0.437436,-0.273626,-0.533807,-0.206341,0.347713,0.093239,-0.157431,-0.2325,-0.175259,-0.477599,-0.191418,-0.204909,-0.068354,-0.091099,0.001547,-0.077765,-0.037419,-0.282513,-0.108931,-0.22835,0.06262,0.019637,0.050278,0.084655,-0.239049,0.155931,-0.00827,0.0,-0.054039,-0.063127,-0.105264,0.073924,0.010964,0.312291,0.0]},"lam":10.0},"default":
{"config":{"extra":false,"refine":3,"keep_other":false},"weights":{"fwd":[-0.089783,-0.230618,-0.142473,-0.032072,-0.215397,0.046974,-0.010045,-0.101503,-0.130844,0.05579,-0.207344,-0.090326,-0.152888,0.296092,-0.300868,-0.14825,0.03224,-0.042612,0.029026,-0.087522,-0.501072,-0.10101,-0.575206,-0.090782,-0.194901,0.020895,-0.166267,-0.068329,-0.137369,-0.370111,-0.372332,0.036474,-0.204433,-0.321037,0.028871,-0.312531,-0.013526,-0.166614,-0.384086,-0.194776,0.01969,-0.063659,0.138025,-0.482628,-0.0198,0.122054,-0.069982,-0.437436,-0.273626,-0.533807,-0.206341,0.347713,0.093239,-0.157431,-0.2325,-0.175259,-0.477599,-0.191418,-0.204909,-0.068354,-0.091099,0.001547,-0.077765,-0.037419,-0.282513,-0.108931,-0.22835,0.06262,0.019637,0.050278,0.084655,-0.239049,0.155931,-0.00827,0.0,-0.054039,-0.063127,-0.105264,0.073924,0.010964,0.312291,0.0],"ref":[-0.122445,-0.195866,-0.287186,-0.028145,-0.09358,0.152736,-0.123059,-0.120412,-0.153941,0.026707,-0.034411,-0.013901,0.027785,0.08132,-0.103472,-0.145389,0.16594,-0.095805,-0.038069,-0.067318,-0.717961,-0.093005,-0.78236,-0.036323,-0.239379,-0.145613,-0.138907,0.016242,-0.217842,-0.379179,-0.368944,0.188068,0.059786,-0.361172,-0.24821,-0.318762,0.154013,-0.154347,-0.33468,-0.072038,-0.042017,-0.097932,0.116414,-0.54619,0.034673,-0.122475,-0.154413,-0.555562,-0.276212,-0.479843,-0.172911,0.489049,-0.021499,-0.138359,-0.26652,0.081094,-0.300087,-0.406574,0.133602,0.102019,-0.139755,-0.236104,-0.253769,-0.09426,-0.182838,-0.334852,-0.231988,0.041975,-0.026738,-0.103567,-0.03588,-0.470575,0.023645,0.091055,0.0,-0.330799,-0.34043,0.163813,-0.124358,-0.087191,-0.008991,0.0],"default":[-0.089783,-0.230618,-0.142473,-0.032072,-0.215397,0.046974,-0.010045,-0.101503,-0.130844,0.05579,-0.207344,-0.090326,-0.152888,0.296092,-0.300868,-0.14825,0.03224,-0.042612,0.029026,-0.087522,-0.501072,-0.10101,-0.575206,-0.090782,-0.194901,0.020895,-0.166267,-0.068329,-0.137369,-0.370111,-0.372332,0.036474,-0.204433,-0.321037,0.028871,-0.312531,-0.013526,-0.166614,-0.384086,-0.194776,0.01969,-0.063659,0.138025,-0.482628,-0.0198,0.122054,-0.069982,-0.437436,-0.273626,-0.533807,-0.206341,0.347713,0.093239,-0.157431,-0.2325,-0.175259,-0.477599,-0.191418,-0.204909,-0.068354,-0.091099,0.001547,-0.077765,-0.037419,-0.282513,-0.108931,-0.22835,0.06262,0.019637,0.050278,0.084655,-0.239049,0.155931,-0.00827,0.0,-0.054039,-0.063127,-0.105264,0.073924,0.010964,0.312291,0.0]},"lam":10.0}}}''')


# --------------------------------------------------------------------------- spectral analysis

def _mel(f):
    return 2595.0*np.log10(1.0 + f/700.0)


def _mel_bank():
    freqs = np.arange(NFFT//2 + 1)*RATE/NFFT
    edges_mel = np.linspace(_mel(50.0), _mel(RATE/2.0), NBANDS + 2)
    edges = 700.0*(10**(edges_mel/2595.0) - 1.0)
    bank = np.zeros((len(freqs), NBANDS))
    for b in range(NBANDS):
        lo, mid, hi = edges[b], edges[b + 1], edges[b + 2]
        up = (freqs - lo)/max(mid - lo, 1e-9)
        down = (hi - freqs)/max(hi - mid, 1e-9)
        bank[:, b] = np.clip(np.minimum(up, down), 0, None)
        if bank[:, b].sum() == 0:          # very narrow low band: nearest bin
            bank[np.argmin(np.abs(freqs - mid)), b] = 1.0
    return bank, edges[1:-1]


BANK, CENTRES = _mel_bank()
HI = CENTRES >= HI_HZ
LO = ~HI
WINDOW = np.hanning(BLOCK + 1)[:-1]
# floor ~ white noise of 2 counts RMS in each band (keeps silence from dominating log distances)
BAND_FLOOR = 4.0*float((WINDOW**2).sum())*BANK.sum(axis=0)
TOTAL_FLOOR = 4.0*float((WINDOW**2).sum())*(NFFT//2 + 1)


def block_spectra(pcm):
    """Log-mel (K, B, NBANDS) and log energy (K, B) of half-frame blocks of (K, N, FRAME) PCM."""
    K, N, _ = pcm.shape
    x = pcm.reshape(K, 2*N, BLOCK).astype(np.float32)
    S = np.empty((K, 2*N, NBANDS), np.float32)
    E = np.empty((K, 2*N), np.float32)
    for k0 in range(0, K, 32):
        X = np.fft.rfft(x[k0:k0 + 32]*WINDOW, NFFT, axis=-1)
        P = (X.real**2 + X.imag**2).astype(np.float32)
        S[k0:k0 + 32] = np.log(P @ BANK.astype(np.float32) + BAND_FLOOR.astype(np.float32))
        E[k0:k0 + 32] = np.log(P.sum(axis=-1) + TOTAL_FLOOR)
    return S, E


def click_energy(pcm, starts):
    """log(second-difference energy within +-4 samples of each frame start) minus log(its energy
    over the surrounding frame) for (K, N*FRAME) signal; starts: frame indices (n,)."""
    K = pcm.shape[0]
    x = pcm.reshape(K, -1).astype(np.float32)
    d2 = np.zeros_like(x)
    d2[:, 1:-1] = x[:, 2:] - 2*x[:, 1:-1] + x[:, :-2]
    d2 = d2**2
    out = np.zeros((K, len(starts)), np.float32)
    n = x.shape[1]
    for i, t in enumerate(starts):
        s = t*FRAME
        if s - FRAME//2 < 1 or s + FRAME//2 > n - 1:
            continue
        local = d2[:, s - 4:s + 4].mean(axis=1)
        ctx = d2[:, s - FRAME//2:s + FRAME//2].mean(axis=1)
        out[:, i] = np.log(local + 1.0) - np.log(ctx + 1.0)
    return out


def frame_class(core):
    """0 ACELP, 1 TCX, 2 HQ for decoder core codes (0 ACELP, 1 TCX20, 2 TCX10, 3 HQ)."""
    core = np.asarray(core)
    return np.where(core == 3, 2, np.where((core == 1) | (core == 2), 1, 0))


def raw_analysis(res):
    """Per-candidate analysis of an EvalResult: log-mel / log-energy of half-frame blocks, click
    energy at every frame start, decoder flags per frame, majority frame classes."""
    pcm, diag = res.pcm, res.diag
    K, N, _ = pcm.shape
    S, E = block_spectra(pcm)
    clicks = click_energy(pcm, list(range(N + 1)))
    flags = np.stack([diag['bfi_out'] != 0, diag['ber_detect'] != 0, diag['next_bit_pos'] != diag['nbits'],
                      diag['clip_count'] > 0], axis=-1)
    cls_all = frame_class(diag['core'])
    cls = np.array([np.bincount(cls_all[:, t], minlength=3).argmax() for t in range(N)])
    return dict(S=S, E=E, clicks=clicks, flags=flags, cls=cls, status=np.asarray(res.status) != 0)


def candidate_features(raw, role, frame_ok, anchor_ok, n_group=60):
    """Feature matrix (K, NF) for the candidates of one target byte.

    raw        raw_analysis() of K candidates over N >= 60 frames (group frames 0..59 + tail)
    role       target role r (its frames are r, r+4, ..., r+56)
    frame_ok   (N,) frames that were sent as good (identical for all candidates)
    anchor_ok  (N,) frames that are exactly known (clean, not of the target role) and good
    """
    S, E = raw['S'].astype(np.float32), raw['E'].astype(np.float32)
    K, B, _ = S.shape
    N = B // 2
    rows = [t for t in range(role, n_group, ROLES) if frame_ok[t]]
    feats = np.zeros((K, NF), np.float32)
    if not rows:
        return feats, np.zeros(0, int)
    cls = raw['cls'][rows]
    anchors = np.flatnonzero(anchor_ok)
    per = np.zeros((K, len(rows), len(BASE_FEATURES)), np.float32)

    def flux(b, band):
        return np.abs(S[:, b, band] - S[:, b - 1, band]).mean(axis=-1)

    for i, t in enumerate(rows):
        b0, b1 = 2*t, 2*t + 1
        prev = anchors[anchors < t]
        nxt = anchors[anchors > t]
        a_prev = int(prev[-1]) if len(prev) else None
        a_next = int(nxt[0]) if len(nxt) else None
        f = per[:, i]
        if b0 >= 1:
            f[:, 0] = flux(b0, LO)
            f[:, 1] = flux(b0, HI)
            f[:, 12] = E[:, b0] - E[:, b0 - 1]
        f[:, 2] = flux(b1, LO)
        f[:, 3] = flux(b1, HI)
        if b1 + 1 < 2*N:
            f[:, 4] = flux(b1 + 1, LO)
            f[:, 5] = flux(b1 + 1, HI)
            f[:, 14] = E[:, b1 + 1] - E[:, b1]
        # concealed / following span up to and including the first block of the next anchor
        end = 2*a_next if a_next is not None else min(2*(t + ROLES), 2*N - 1)
        end = min(end, 2*N - 1)
        if end > b1 + 1:
            span = np.arange(b1 + 2, end + 1)
            f[:, 6] = np.abs(S[:, span][..., LO] - S[:, span - 1][..., LO]).mean(axis=-1).sum(axis=1)
            f[:, 7] = np.abs(S[:, span][..., HI] - S[:, span - 1][..., HI]).mean(axis=-1).sum(axis=1)
        cur = 0.5*(S[:, b0] + S[:, b1])
        ecur = 0.5*(E[:, b0] + E[:, b1])
        eanch = []
        if a_prev is not None:
            ref = 0.5*(S[:, 2*a_prev] + S[:, 2*a_prev + 1])
            f[:, 8] = np.abs(cur[:, LO] - ref[:, LO]).mean(axis=-1)
            f[:, 9] = np.abs(cur[:, HI] - ref[:, HI]).mean(axis=-1)
            eanch.append(0.5*(E[:, 2*a_prev] + E[:, 2*a_prev + 1]))
            hl_ref = ref[:, HI].mean(axis=-1) - ref[:, LO].mean(axis=-1)
            f[:, 26] = np.abs((cur[:, HI].mean(axis=-1) - cur[:, LO].mean(axis=-1)) - hl_ref)
        if a_next is not None:
            ref = 0.5*(S[:, 2*a_next] + S[:, 2*a_next + 1])
            f[:, 10] = np.abs(cur[:, LO] - ref[:, LO]).mean(axis=-1)
            f[:, 11] = np.abs(cur[:, HI] - ref[:, HI]).mean(axis=-1)
            eanch.append(0.5*(E[:, 2*a_next] + E[:, 2*a_next + 1]))
            if end > b1 + 2:
                f[:, 25] = E[:, b1 + 2:end].mean(axis=1) - eanch[-1]
        if eanch:
            f[:, 16] = ecur - np.mean(eanch, axis=0)
        f[:, 13] = np.abs(f[:, 12])
        f[:, 15] = np.abs(f[:, 14])
        f[:, 17] = np.abs(f[:, 16])
        f[:, 18] = raw['clicks'][:, t]
        f[:, 19] = raw['clicks'][:, t + 1]
        f[:, 20:24] = raw['flags'][:, t]
        f[:, 24] = ecur
    nb = len(BASE_FEATURES)
    for c in range(3):
        sel = cls == c
        if sel.any():
            feats[:, c*nb:(c + 1)*nb] = per[:, sel].sum(axis=1)
    feats[:, -1] = raw['status']
    return feats, cls


def standardise(feats):
    """Per-byte z-scores over the candidates (constant features -> 0), clipped."""
    f = np.asarray(feats, np.float64)
    mu = f.mean(axis=0, keepdims=True)
    sd = f.std(axis=0, keepdims=True)
    z = np.where(sd > 1e-6, (f - mu)/np.maximum(sd, 1e-6), 0.0)
    return np.clip(z, -Z_CLIP, Z_CLIP)


def model_logp(feats, model, key=None):
    """256-way log-probabilities from features with a fitted linear model."""
    z = standardise(feats)
    w = np.asarray(model['weights'][key] if key and key in model['weights'] else model['weights']['default'],
                   np.float64)
    s = z @ w
    s = s - s.max()
    return s - np.log(np.exp(s).sum())


# --------------------------------------------------------------------------- data handling

class Inputs:
    def __init__(self, path):
        with np.load(path, allow_pickle=False) as d:
            self.d = {k: d[k] for k in d.files}
        d = self.d
        self.split, self.task = str(d['split']), str(d['task'])
        self.frames, self.present = d['frames'], d['present'].astype(bool)
        self.known, self.target = d['known'].astype(np.int16), d['target'].astype(bool)
        self.run_id, self.group_id = d['run_id'], d['group_id']
        self.G = len(self.group_id)

    def mask_known(self, g, override=None):
        """(mask (4, 11) uint8, known (4, 11) bool) of group g; override {(r, j): value} adds bytes."""
        k = self.known[g].reshape(ROLES, MB)
        mask = np.where(k >= 0, k, 0).astype(np.uint8)
        known = k >= 0
        for (r, j), v in (override or {}).items():
            mask[r, j] = v
            known[r, j] = True
        return mask, known

    def same_run(self, a, b):
        return 0 <= a < self.G and 0 <= b < self.G and self.run_id[a] == self.run_id[b]

    def clean_frames(self, g, override=None, max_unknown=0):
        """Frames of group g with known bytes removed, good flags (roles with more than
        `max_unknown` unknown bytes erased) and which frames are exact anchors."""
        mask, known = self.mask_known(g, override)
        frames = unmask_group(self.frames[g], mask, known)
        good = self.present[g].copy()
        exact = np.zeros(60, bool)
        for r in range(ROLES):
            n_unknown = int((~known[r]).sum())
            if n_unknown > max_unknown:
                good[r::ROLES] = False
            if n_unknown == 0:
                exact[r::ROLES] = True
        return frames, good, exact & good


def warm_up(dec, data, g, overrides, groups=WARMUP_GROUPS, max_unknown=0):
    dec.reset()
    for h in range(g - groups, g):
        if data.same_run(h, g):
            frames, good, _ = data.clean_frames(h, overrides.get(h), max_unknown)
            dec.feed(frames, good)


def tail_frames(data, g, overrides, max_unknown=0):
    if data.same_run(g, g + 1):
        frames, good, exact = data.clean_frames(g + 1, overrides.get(g + 1), max_unknown)
        return frames[:TAIL_FRAMES], good[:TAIL_FRAMES], exact[:TAIL_FRAMES]
    return (np.zeros((TAIL_FRAMES, 33), np.uint8), np.zeros(TAIL_FRAMES, bool), np.zeros(TAIL_FRAMES, bool))


def eval_byte(dec, data, g, role, j, override, tail, max_unknown=0, want_raw=False, anchor_known=None):
    """Features (256, NF) and frame classes for target (g, role, j) given fixed bytes `override`.
    Frames of other roles are decoded when all their bytes are known or fixed, else erased.
    Anchors are frames of roles fully known in `anchor_known` (default: known or fixed)."""
    mask, known = data.mask_known(g, override)
    known_t = known.copy()
    known_t[role, j] = False
    # erase other roles with more than max_unknown unknown bytes
    erase = [r for r in range(ROLES) if r != role and int((~known_t[r]).sum()) > max_unknown]
    cands, good = role_byte_candidates(data.frames[g], mask, known_t, role, j, good=data.present[g],
                                       erase_roles=erase)
    tf, tg, te = tail
    cands = np.concatenate([cands, np.repeat(tf[None], 256, axis=0)], axis=1)
    good = np.concatenate([good, np.repeat(tg[None], 256, axis=0)], axis=1)
    frame_ok = good[0]
    anchor = np.zeros(len(frame_ok), bool)
    akn = known_t if anchor_known is None else np.asarray(anchor_known, bool).reshape(ROLES, MB)
    for r in range(ROLES):
        if r != role and akn[r].all() and known_t[r].all():
            anchor[r:60:ROLES] = True
    anchor[60:] = te
    anchor &= frame_ok
    res = dec.eval(cands, good, pcm=True)
    raw = raw_analysis(res)
    feats, cls = candidate_features(raw, role, frame_ok, anchor)
    if want_raw:
        raw.update(frame_ok=frame_ok, anchor=anchor)
        return feats, cls, raw
    return feats, cls


# --------------------------------------------------------------------------- driver

def select_groups(data, n=None, seed=0):
    tg = np.flatnonzero(data.target.any(axis=1))
    if n is not None and n < len(tg):
        rng = np.random.default_rng(seed)
        tg = np.sort(rng.choice(tg, n, replace=False))
    return tg


def save_raw(path, raw, fix):
    """Development dump of one byte's per-candidate analysis."""
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez(path, S=raw['S'].astype(np.float16), E=raw['E'].astype(np.float16),
             clicks=raw['clicks'].astype(np.float16), flags=raw['flags'].astype(np.int8), cls=raw['cls'],
             status=raw['status'], frame_ok=raw['frame_ok'], anchor=raw['anchor'],
             fix=np.array([[r, j, v] for (r, j), v in sorted(fix.items())], np.int16).reshape(-1, 3))


DEFAULT_CONFIG = dict(extra=True, refine=1, keep_other=False, beam=1)


def solve_group(dec, data, g, model, cfg, collect=None, raw_dir=None):
    """Sequential (bitstream-order) estimation of every unknown byte of each target role, then
    `refine` Gauss-Seidel passes that re-score each byte with all other bytes of the role fixed at
    their current best value.  Returns {(r, j): logp} for the group's target cells."""
    targets = [(m // MB, m % MB) for m in np.flatnonzero(data.target[g])]
    _, known_in = data.mask_known(g)
    roles = sorted(set(r for r, _ in targets))
    warm_up(dec, data, g, {})
    dec.checkpoint('start')
    tail = tail_frames(data, g, {})
    fixed, logp, cache = {}, {}, {}

    def score(r, j, stage, p):
        same = {c: v for c, v in fixed.items() if c[0] == r and c != (r, j)}
        other = {c: v for c, v in fixed.items() if c[0] != r} if cfg['keep_other'] else {}
        fix = {**other, **same}
        key = (r, j, tuple(sorted(fix.items())))
        if key in cache:                  # same context as before: identical candidates, skip decoding
            feats, cls = cache[key]
        else:
            dec.restore('start')
            if raw_dir is None:
                feats, cls = eval_byte(dec, data, g, r, j, fix, tail, anchor_known=known_in)
            else:
                feats, cls, raw = eval_byte(dec, data, g, r, j, fix, tail, anchor_known=known_in, want_raw=True)
                save_raw(Path(raw_dir)/f'{data.group_id[g]}_r{r}j{j}_{stage}{p}.npz', raw, fix)
            cache[key] = feats, cls
        if collect is not None:
            collect.append(dict(g=int(g), role=r, j=j, stage=stage, pass_=p, feats=feats.astype(np.float32),
                                cls=np.bincount(cls, minlength=3), nfix=len(same)))
        lp = model_logp(feats, model, key=stage) if model is not None else np.zeros(256)
        logp[(r, j)] = lp
        changed = fixed.get((r, j)) != int(np.argmax(lp))
        fixed[(r, j)] = int(np.argmax(lp))
        return changed

    for r in roles:
        if cfg['extra']:
            unknown = [j for j in range(MB) if not known_in[r, j]]
        else:
            unknown = sorted(j for rr, j in targets if rr == r)
        for j in unknown:
            score(r, j, 'fwd', 0)
        for p in range(cfg['refine']):
            # Gauss-Seidel pass; stops early once a full pass changes no best value (a further
            # pass would decode exactly the same candidates again)
            changed = [score(r, j, 'ref', p) for j in unknown]
            if p > 0 and not any(changed):
                break
    return {c: logp[c] for c in targets}


def run(data, groups, model, cfg, jobs=2, log=None, collect=None, raw_dir=None):
    """Predictions {(g, r, j): logp(256)}."""
    out = {}
    with CandidateDecoder(rate=RATE, jobs=jobs) as dec:
        t0 = time.time()
        for n, g in enumerate(groups):
            for (r, j), lp in solve_group(dec, data, g, model, cfg, collect, raw_dir).items():
                out[(int(g), r, j)] = lp
            if log and (n % 5 == 0 or n == len(groups) - 1):
                log(f'{n + 1}/{len(groups)} groups, {time.time() - t0:.0f} s')
    return out


def save_predictions(path, data, preds):
    keys = sorted(preds)
    np.savez_compressed(path, format=PREDICTION_FORMAT, method=METHOD, split=data.split, task=data.task,
                        group=np.array([data.group_id[g] for g, _, _ in keys]),
                        role=np.array([r for _, r, _ in keys], np.int8),
                        j=np.array([j for _, _, j in keys], np.int8),
                        logp=np.array([preds[k] for k in keys], np.float64))


def load_model(path, task):
    """Model for `task`: a JSON file (one model, or {'tasks': {task: model}}) or the frozen models."""
    doc = json.loads(Path(path).read_text()) if path else FROZEN_MODEL
    if doc is None:
        raise SystemExit('no frozen model in this script; pass --model')
    if 'tasks' in doc:
        tasks = doc['tasks']
        doc = tasks.get(task, tasks.get('default'))
        if doc is None:
            raise SystemExit(f'no model for task {task}')
    return doc


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--inputs', required=True, type=Path)
    ap.add_argument('--out', type=Path)
    ap.add_argument('--groups', type=int, help='score a seeded random subset of N target groups')
    ap.add_argument('--seed', type=int, default=0)
    ap.add_argument('--jobs', type=int, default=2)
    ap.add_argument('--model', type=Path, help='model JSON (default: the frozen model in this script)')
    ap.add_argument('--config', help='JSON overriding the model config (development)')
    ap.add_argument('--exclude', type=Path, help='text file of group ids not to score (e.g. training groups)')
    ap.add_argument('--collect', type=Path, help='also write raw features (development)')
    ap.add_argument('--no-model', action='store_true', help='collect features only (uniform predictions)')
    ap.add_argument('--raw-dir', type=Path, help='also dump per-candidate spectra (development)')
    ap.add_argument('--control', choices=['wrong-key'],
                    help="wrong-key: every group's visible key bytes are replaced by those of the target group "
                         "half the list away (the method then scores against garbage; expect chance)")
    a = ap.parse_args()
    data = Inputs(a.inputs)
    if a.control == 'wrong-key':
        tg = np.flatnonzero(data.target.any(axis=1))
        donor = np.roll(tg, len(tg)//2)
        known = data.known.copy()
        known[tg] = data.known[donor]
        data.known = known
    model = None if a.no_model else load_model(a.model, data.task)
    cfg = dict(DEFAULT_CONFIG)
    cfg.update((model or {}).get('config', {}))
    if a.config:
        cfg.update(json.loads(a.config))
    if a.exclude:
        skip = set(Path(a.exclude).read_text().split())
        data.target[np.array([str(x) in skip for x in data.group_id])] = False
    groups = select_groups(data, a.groups, a.seed)
    collect = [] if a.collect else None
    print(f'{data.split}.{data.task}: {len(groups)} groups, config {cfg}', flush=True)
    t0 = time.time()
    preds = run(data, groups, model, cfg, a.jobs, log=lambda s: print(s, flush=True), collect=collect,
                raw_dir=a.raw_dir)
    print(f'done in {time.time() - t0:.0f} s', flush=True)
    if a.out:
        a.out.parent.mkdir(parents=True, exist_ok=True)
        save_predictions(a.out, data, preds)
    if collect is not None:
        a.collect.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(a.collect, feats=np.stack([c['feats'] for c in collect]),
                            g=np.array([c['g'] for c in collect]), role=np.array([c['role'] for c in collect]),
                            j=np.array([c['j'] for c in collect]), stage=np.array([c['stage'] for c in collect]),
                            pass_=np.array([c['pass_'] for c in collect]),
                            cls=np.stack([c['cls'] for c in collect]), nfix=np.array([c['nfix'] for c in collect]),
                            group_id=np.array([data.group_id[c['g']] for c in collect]),
                            feature_names=np.array(FEATURE_NAMES))


if __name__ == '__main__':
    main()
