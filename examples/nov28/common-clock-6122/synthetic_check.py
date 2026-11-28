"""Run one offline synthetic dual-channel geometry control; the output directory must be fresh."""
import argparse
from contextlib import redirect_stdout
import gzip
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import numpy as np
import soundfile as sf
from scipy.signal import firwin, oaconvolve

def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()

def run(repo, scripts, dream, out):
    case = repo / 'examples/receiver-control'
    source = case / 'challenge-iq48.flac'
    assert sha(source) == 'ae12fed7ed9aab2c583b6ad1aefdbd32cecc52b20adebd16a4939c9aa48931c6'
    assert sha(dream) == '1e398433affbe71e3bdbc30171e9c770ddd3a622c0fe1577b3f3837c3fa07a26'
    assert sha(scripts/'extract_iq_channel.py') == 'd32d8b1f043fcd62b6ef58dc170d2cbc5a737fe366ee6179929438d95ff64f16'
    assert sha(scripts/'demod_iq_window.py') == 'fb3cc1cee294e995ee80220f55c8bd8931f53fece482c2b92f92754892eba662'
    out.mkdir(parents=True,exist_ok=False)
    samples,rate=sf.read(source,dtype='float64')
    assert rate==48000
    # All oscillator frequencies are integer Hz; exact one-second phase reset.
    t=np.arange(len(samples)) % rate / rate
    lo=lambda freq:np.exp(2j*np.pi*freq*t)
    message=.32*np.cos(2*np.pi*500*t)+.23*np.cos(2*np.pi*1200*t)
    digital=.65*(samples[:,0]+1j*samples[:,1])*lo(18000)
    mixed=digital+.1*(1+message)*lo(-22000)
    wide=out/'dual.wav'
    wide_iq=np.column_stack((mixed.real,mixed.imag))
    peak=float(np.max(np.abs(wide_iq)))
    assert peak < 1
    sf.write(wide,wide_iq,rate,subtype='PCM_16')
    del digital,mixed,wide_iq,samples
    narrow=out/'drm.wav'
    subprocess.run([sys.executable,scripts/'extract_iq_channel.py',wide,narrow,'--offset-hz','18000'],
                   check=True,stdout=(out/'extract.json').open('w'))
    env={**os.environ,'KCBS_DREAM':str(dream),'PYTHONDONTWRITEBYTECODE':'1'}
    subprocess.run([sys.executable,scripts/'demod_iq_window.py',narrow,out/'demod','--seconds','600',
                    '--mlc-iterations','1','--reception-profile','wiener'],check=True,env=env,stdout=(out/'demod.log').open('w'))
    sys.path[:0]=[str(case),str(repo/'scripts')]
    from drm_row_alignment import read_msc,valid_packets,witnessed_pairs
    from generate import damaged_rows
    from trace_transport import split_rows
    from salvage_msc_packets import salvage
    from receive import unpack_fixture
    from verify import read_g192
    from speech_presence_test import write_g192
    native=read_msc(out/'demod/msc.bin')
    orig=gzip.decompress((case/'fixture/sender-msc.bin.gz').read_bytes())
    transmitted=split_rows(damaged_rows(orig)[0])
    pairs,_=witnessed_pairs(split_rows(orig),native)
    seen_good=wrong_good=whole_rows=intact_rows=0
    for i,j in pairs:
        a=transmitted[i];b=native[j]
        whole_rows+=a==b
        g1,g2=valid_packets(a),valid_packets(b)
        intact_rows+=len(g1)==4 and g1==g2
        seen_good+=len(g1.keys() & g2.keys())
        wrong_good+=sum(g1[q]!=g2[q] for q in g1.keys() & g2.keys())
    with (out/'salvage.log').open('w') as log, redirect_stdout(log):
        salvage([out/'demod/msc.bin'],out/'receiver',transport_only=True,save_packets=True)
    words,observed,records,transport,_=unpack_fixture(out/'receiver/packets.npz',16909060,40)
    stream=out/'receiver.192';write_g192(stream,words,observed.all(axis=1))
    a=read_g192(gzip.decompress((case/'fixture/sender.192.gz').read_bytes()))
    b=read_g192(stream.read_bytes())
    assert len(a)==len(b)==2400
    # recover both AM sidebands on this synthetic channel, each tone fits above -24 kHz
    stored,_=sf.read(wide); base=(stored[:,0]+1j*stored[:,1])*lo(22000)
    low=oaconvolve(base,firwin(801,1500,fs=rate,window=('kaiser',9)),mode='same')
    trim=slice(rate//10,-rate//10)
    env_abs=np.abs(low[trim]);ref=message[trim]
    corr=float(np.corrcoef(env_abs,ref)[0,1])
    baseline=json.loads((case/'result/receiver.json').read_bytes())['source_and_receiver_sha256']
    return dict(source=source.name,source_sha256=sha(source),sample_rate=rate,pairs=len(t),
                modulator={'iq':'I+jQ','drm_hz':18000,'drm_gain':.65,'am_hz':-22000,
                  'am_carrier':.1,'tone_hz':[500,1200],'modulation_indices':[.32,.23]},component_peak=peak,
                wide_sha256=sha(wide),
                extracted_float32_iq_sha256=hashlib.sha256(sf.read(narrow, dtype='float32')[0].astype('<f4', copy=False).tobytes()).hexdigest(),
                extractor_sha256=sha(scripts/'extract_iq_channel.py'),
                demod_sha256=sha(scripts/'demod_iq_window.py'),dream_sha256=sha(dream),
                native_sha256=sha(out/'demod/msc.bin'),published_native_sha256=baseline['msc'],
                native_rows=len(native),origin_rows=len(transmitted),origin_rows_witnessed=len(pairs),
                exact_transmitted_rows=whole_rows,exact_good_complete_dus=intact_rows,
                origin_good_packets=sum(len(valid_packets(row)) for row in transmitted),
                origin_good_native_received=seen_good,origin_good_native_disagreed=wrong_good,
                assigned=transport,words=len(b),correct_supplied=sum(x==y for x,y in zip(a,b) if y is not None),
                wrong_supplied=sum(x!=y for x,y in zip(a,b) if y is not None),erased=sum(x is None for x in b),
                g192_sha256=sha(stream),published_g192_sha256=baseline['receiver_g192'],text_records=len(records),
                am=dict(envelope_correlation=corr,trim_seconds_each_end=.1,lowpass_hz=1500,
                        recorded_envelope_mean=float(env_abs.mean())))

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for k in ('repo','scripts','dream','out'):p.add_argument(k,type=Path)
    a=p.parse_args()
    result=run(*(getattr(a,k).resolve() for k in ('repo','scripts','dream','out')))
    (a.out/'result.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))
