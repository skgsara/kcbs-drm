"""Post-seal Mode-B CP indication; see protocol.txt. No demodulator."""
from argparse import ArgumentParser
from hashlib import sha256
import json, math
from pathlib import Path
import numpy as np
import soundfile as sf
from scipy.signal import firwin, upfirdn

FS, TU, TG, SYM = 12000, 256, 64, 320
OFFSETS = (-16000, -8000, 0, 8000, 16000)
HERE = Path(__file__).resolve().parent


def read(p, count):
    raw, fs = sf.read(str(p), dtype="int16", always_2d=True)
    if raw.shape != (fs * count, 2):
        raise ValueError("unexpected duration or channel geometry")
    x = (raw[:,0].astype(np.float32) + 1j * raw[:,1].astype(np.float32)) / 32768
    return x, fs, dict(file=p.name,sha256=sha256(p.read_bytes()).hexdigest(),
                       pcm_sha256=sha256(raw.astype('<i2',copy=False).tobytes()).hexdigest(),
                       sample_pairs=len(x),sample_rate=fs)


def channel(x, fs, hz):
    q, remainder = divmod(fs, FS)
    if remainder or not q or abs(hz) + 4400 > fs/2:
        raise ValueError("invalid sampled channel")
    if hz:
        period = fs // math.gcd(fs, abs(hz))
        osc = np.exp(-2j*np.pi*hz*np.arange(period)/fs).astype(np.complex64)
        x = x * np.resize(osc, len(x))
    taps = firwin(32*q+1, 4400, fs=fs, window=('kaiser',7)).astype(np.float32)
    # Align FIR group delay to sample zero. Both filters represent 16 output-sample delay.
    return upfirdn(taps, x, down=q)[16:16+len(x)//q]


def contrast(half, lag):
    length = ((len(half)-lag)//SYM)*SYM
    a,b = half[:length],half[lag:lag+length]
    power = (np.mean(np.abs(a)**2,dtype='float64')+np.mean(np.abs(b)**2,dtype='float64'))/2
    if power == 0:
        return np.zeros(SYM,complex)
    v = (b*a.conj()).reshape(-1,SYM).mean(axis=0,dtype=np.complex128)/power
    guard = np.convolve(np.r_[v,v[:TG-1]], np.ones(TG)/TG, 'valid')
    rest = (v.sum()-guard*TG)/TU
    return guard-rest


def stats(x):
    rows=[]
    for start in range(0,len(x),10*FS):
        blk=x[start:start+10*FS];fit,test=blk[:4*FS],blk[4*FS:]
        s=[]
        for lag in (TU-7,TU,TU+7):
            tr=contrast(fit,lag);p=int(abs(tr).argmax());z=tr[p]
            val=contrast(test,lag)[p]
            signed=float(np.real(val*np.conj(z))/abs(z)) if z else 0.
            s.append(dict(lag=lag,fit_phase=p,fit_peak=round(float(abs(z)),6),test=round(signed,6)))
        scores=[item["test"] for item in s]
        rows.append(dict(start_s=start//FS,passing=scores[1]>0.1 and scores[1]>max(scores[0],scores[2])+0.05,
                         measurements=s))
    tests = np.array([[r["measurements"][j]["test"] for j in range(3)] for r in rows])
    pass_starts=[r["start_s"] for r in rows if r["passing"]]
    return dict(power_db_complex_fullscale=round(float(10*np.log10(np.mean(np.abs(x)**2,dtype='float64'))),3),
                num_blocks=len(rows),positive_blocks=len(pass_starts),positive_start_s=pass_starts,
                indication=len(pass_starts)>=3,median_test_by_lag=np.median(tests,axis=0).round(6).tolist(),
                maximum_test_by_lag=tests.max(axis=0).round(6).tolist(),blocks=rows)


def run(a,b):
    ref,fs,ref_meta=read(b,120)
    results={'published_positive':dict(source=ref_meta,offsets_hz={'0':stats(channel(ref,fs,0))})}
    # Independent white complex control, same length, sampling rate and passbands as field.
    rng=np.random.default_rng(20261128)
    size=150*48000
    noise=(rng.standard_normal(size,dtype=np.float32)+1j*rng.standard_normal(size,dtype=np.float32))/np.sqrt(np.float32(2))
    results["noise"] = dict(source=dict(seed=20261128,complex_pairs=size),offsets_hz={str(hz):stats(channel(noise,48000,hz)) for hz in OFFSETS})
    del noise
    x,fs,meta=read(a,150)
    results["pilot"]=dict(source=meta,offsets_hz={str(hz):stats(channel(x,fs,hz)) for hz in OFFSETS})
    return dict(protocol_sha256=sha256((HERE/'protocol.txt').read_bytes()).hexdigest(),
                script_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),lag_order=[249,256,263],
                sampled_centers_hz=[3205000+v for v in OFFSETS],analysis_rate=FS,
                fitted_complete_symbols_per_block=149,heldout_complete_symbols_per_block=224,
                gates=dict(nominal_min=0.1,required_margin_over_both_offlags=0.05,required_passing_blocks=3),
                measured=results)

if __name__=='__main__':
    p=ArgumentParser(description=__doc__);p.add_argument('pilot',type=Path);p.add_argument('positive',type=Path);p.add_argument('output',type=Path)
    args=p.parse_args();args.output.write_text(json.dumps(run(args.pilot,args.positive),separators=(',',':'))+'\n')
