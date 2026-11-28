"""Extract 6100 kHz AM from one complex 48 kHz PCM recording centered at 6122 kHz.

Usage: python demod.py ORIGINAL.wav RECEIVER.json OUTPUT_DIRECTORY
       python demod.py --self-test
Dependencies: NumPy, SciPy; directly reads recorder's WAV timing.csv sidecar.
"""
import argparse,csv,json
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

import numpy as np
from scipy import signal
from scipy.io import wavfile

RATE=48_000
CARRIER=-22_000
LOW,HIGH=-1_200,3_800
RF_TAPS,AUDIO_TAPS=801,1601
AUDIO_FIR=signal.firwin(AUDIO_TAPS,[90,3600],fs=RATE,pass_zero=False,window=('kaiser',9))
def digest(p):
    h=sha256()
    with open(p,'rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()
def db(power):
    return round(10*np.log10(max(float(power),1e-25)),2)
def clock(ns):
    return datetime.fromtimestamp(ns/1e9,timezone.utc).isoformat()
def rf_taps(carrier):
    # Complex bandpass on the ORIGINAL sample grid. Both stopband transition edges are inside Nyquist.
    low,high=carrier+LOW,carrier+HIGH
    if not -RATE/2<low-400<high+400<RATE/2:raise ValueError('filter would cross the Nyquist edge')
    proto=signal.firwin(RF_TAPS,(high-low)/2,fs=RATE,window=('kaiser',9))
    return proto*np.exp(2j*np.pi*(low+high)/2/RATE*(np.arange(RF_TAPS)-RF_TAPS//2))
def envelope(x,carrier,cuts):
    """Centered odd-length FIR convolution, followed by pointwise magnitude and centered audio FIR."""
    h=rf_taps(carrier)
    out=np.empty((len(x)+3)//4,float)
    for a,b in zip(cuts,cuts[1:]):
        env=abs(signal.oaconvolve(x[a:b],h,mode='same'))
        half=AUDIO_TAPS//2
        audio=signal.oaconvolve(np.pad(env,half,mode='edge'),AUDIO_FIR,mode='valid')
        first=a+(-a)%4
        out[first//4:(b+3)//4]=audio[first-a::4]
    return out
def self_test():
    k=np.arange(RATE*2);t=k/RATE
    carrier=-21989
    ref=np.sin(2*np.pi*677*t)
    tx=(1+.3*ref)*np.exp(2j*np.pi*carrier*t)
    # Strong input near the *opposite* source edge has no physically available lower-sideband role.
    other=8*np.exp(2j*np.pi*23_100*t)
    take=slice(1000,-1000);plain=envelope(tx,carrier,[0,len(tx)])[take]
    test=envelope(tx+other,carrier,[0,len(tx)])[take]
    r=float(np.corrcoef(ref[::4][take],test)[0,1])
    ratio=float(np.linalg.norm(test-plain)/np.linalg.norm(plain))
    assert r>.99999 and ratio<1e-3
    return dict(zero_lag_r=round(r,8),opposite_edge_addition_relative_rms=round(ratio,9))
def read_clock(wav,receipt,n):
    timing=wav.with_name(receipt['packet_timing_file'])
    with timing.open() as f:rows=list(csv.DictReader(f))
    pos=0;anchors=[]
    for row in rows:
        if int(row['sample_offset'])!=pos:raise ValueError('noncontiguous packet ledger')
        if row['receiver_unix_ns']:anchors.append((pos,int(row['receiver_unix_ns'])))
        pos+=int(row['sample_pairs'])
    if pos!=n or len(anchors)<2:raise ValueError('missing timing or IQ')
    jumps=[]
    for (p,t),(q,u) in zip(anchors,anchors[1:]):
        residual=u-t-round((q-p)*1e9/RATE)
        if abs(residual)>1e9/RATE:jumps.append(dict(at_input_sample=q,residual_ns=residual))
    p,t=anchors[0];start=t-round(p*1e9/RATE)
    q,u=anchors[-1];end=u+round((n-q)*1e9/RATE)
    return [0,*[j['at_input_sample'] for j in jumps],n], dict(timing_file=timing.name,timing_sha256=digest(timing),
            receiver_first_utc=clock(start),receiver_end_exclusive_utc=clock(end),receiver_first_unix_ns=start,
            receiver_end_exclusive_unix_ns=end,first_anchor_sample=p,last_anchor_sample=q,anchor_count=len(anchors),jumps=jumps)
def measure(x,carrier,psds,f,bs):
    rows=[]
    for b,p in enumerate(psds):
        v=x[b*bs:(b+1)*bs];n=len(v)
        if n<2*RATE:continue
        k=np.arange(n)
        z=v*np.exp(-2j*np.pi*carrier/RATE*k)
        chunks=z[:n//1024*1024].reshape(-1,1024)
        spec=20*np.log10(np.maximum(abs(np.fft.fft(chunks*np.hanning(1024),axis=1)),1e-12))
        bins=np.arange(6,21) # matched physical sidebands only 281–938 Hz from the carrier
        us=spec[:,bins]-spec[:,bins].mean(axis=0)
        ls=spec[:,-bins]-spec[:,-bins].mean(axis=0)
        den=np.linalg.norm(us)*np.linalg.norm(ls)
        delta=f-carrier
        reference=np.median(p[(delta>=5000)&(delta<=7000)])
        selected=np.abs(f-CARRIER)<=150
        ci=np.flatnonzero(selected)[np.argmax(p[selected])]
        rows.append(dict(start_s=b*bs/RATE,peak_hz_relative_to_nominal=round(float(f[ci]-CARRIER),3),
            carrier_peak_to_local_50_250_hz_median_db=db(p[ci]/np.median(p[(abs(delta)>50)&(abs(delta)<250)])),
            lower_300_1000_to_upper_5000_7000_db=db(np.median(p[(delta>-1000)&(delta<-300)])/reference),
            upper_300_1000_to_upper_5000_7000_db=db(np.median(p[(delta>300)&(delta<1000)])/reference),
            upper_1200_3500_to_upper_5000_7000_db=db(np.median(p[(delta>1200)&(delta<3500)])/reference),
            mirrored_band_log_spectrum_time_r=round(float((us*ls).sum()/den),4),
            circular_shift_two_s_r=round(float((us*np.roll(ls,round(2*RATE/1024),axis=0)).sum()/den),4)))
    return rows
def run(wav,receipt_path,destination):
    receipt=json.loads(receipt_path.read_text())
    rate,pcm=wavfile.read(wav)
    if rate!=RATE or receipt['frequency_hz']!=6122000 or receipt['sample_rate_hz']!=RATE or pcm.dtype!=np.int16 or pcm.shape!=(receipt['sample_pairs'],2):
        raise ValueError('unexpected IQ recording geometry')
    if sha256(pcm.astype('<i2',copy=False)).hexdigest()!=receipt['iq_pcm_sha256']:raise ValueError('raw PCM digest mismatch')
    x=(pcm[:,0].astype('f4')+1j*pcm[:,1].astype('f4'))/32768
    cuts,clock_info=read_clock(wav,receipt,len(pcm))
    bs=RATE*10
    psds=[]
    for a in range(0,len(x),bs):
        v=x[a:a+bs]
        if len(v)<32768:continue
        f,p=signal.welch(v,RATE,nperseg=32768,noverlap=16384,detrend=False,return_onesided=False)
        psds.append(p)
    if not psds:raise ValueError('too little IQ to estimate carrier')
    p=np.mean(psds,axis=0)
    idx=np.flatnonzero(abs(f-CARRIER)<=150)
    i=idx[np.argmax(p[idx])]
    contrast=db(p[i]/np.median(p[(abs(f-f[i])>50)&(abs(f-f[i])<250)]))
    carrier=float(f[i]) if contrast>=10 else CARRIER
    audio=envelope(x,carrier,cuts)
    gain=.85/max(1e-12,np.max(abs(audio)))
    destination.mkdir(exist_ok=True,parents=True)
    out=destination/'6100-envelope-12k.wav';wavfile.write(out,RATE//4,np.rint(audio*gain*32767).astype('<i2'))
    return dict(source=wav.name,source_sha256=digest(wav),pcm_sha256=receipt['iq_pcm_sha256'],protocol_center_hz=6122000,
        iq_rate_hz=RATE,iq_sample_pairs=len(x),audio_file=out.name,audio_sha256=digest(out),audio_rate_hz=RATE//4,
        audio_samples=len(audio),audio_sample_map='output index k corresponds to input IQ index 4*k; no accumulated FIR delay',
        time=clock_info,raw_receiver_receipt_sha256=digest(receipt_path),gain=round(gain,6),
        carrier_estimate_hz_relative_to_nominal=round(float(f[i]-CARRIER),5),carrier_peak_db_over_local_median=contrast,
        used_rf_offset_hz=carrier,rf_half_gain_cutoffs_relative_to_center=[carrier+LOW,carrier+HIGH],
        rf_fir=f'{RF_TAPS} symmetric prototype Kaiser beta 9, complex-modulated on input sample grid; centered convolution, magnitude',
        audio_fir=f'{AUDIO_TAPS} taps centered Kaiser beta 9, half-gain 90..3600 Hz, 4:1 decimation from sample zero',
        boundary_processing='filter each contiguous clock span separately; RF uses zero extension, audio envelope edge-held; within 25 ms of each edge FIR support incomplete',
        upper_only_above_hz=1200,full_input_nyquist_hz=[-24000,24000],limit='actual front-end response and programme identity unknown',
        synthetic_check=self_test(),ten_second_rf=measure(x,carrier,psds,f,bs))
if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--self-test',action='store_true')
    parser.add_argument('paths',nargs='*',type=Path);args=parser.parse_args()
    if args.self_test:print(json.dumps(self_test()));raise SystemExit
    if len(args.paths)!=3:parser.error('expected WAV, recorder receipt and output directory')
    result=run(*args.paths)
    (args.paths[2]/'receipt.json').write_text(json.dumps(result,indent=2)+'\n')
