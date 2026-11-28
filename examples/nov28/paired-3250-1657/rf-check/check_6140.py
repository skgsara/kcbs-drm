"""Apply the frozen 3205 analysis unchanged to the center of an already extracted 6140-kHz channel."""
from pathlib import Path
from argparse import ArgumentParser
from hashlib import sha256
import json
import numpy as np
import soundfile as sf
from check import FS, HERE, channel, stats

p=ArgumentParser(description=__doc__)
p.add_argument("input",type=Path);p.add_argument("output",type=Path);args=p.parse_args()
raw,rate=sf.read(args.input,dtype="float32",always_2d=True)
if sf.info(args.input).subtype!="FLOAT" or raw.shape!=(180*FS,2) or rate!=FS or not np.isfinite(raw).all():
    raise ValueError("expected the finite two-channel floating-point 180s field product at 12 ksps")
x=raw[:,0]+1j*raw[:,1]
r=stats(channel(x,rate,0))
result=dict(source=args.input.name,source_sha256=sha256(args.input.read_bytes()).hexdigest(),hz=6140000,
            rate=rate,source_subtype="float32 stereo I/Q",sample_pairs=len(x),center_offset_hz=0,
            source_samples_sha256=sha256(raw.astype('<f4',copy=False).tobytes()).hexdigest(),
            analysis_protocol_sha256=sha256((HERE/'protocol.txt').read_bytes()).hexdigest(),
            analysis_script_sha256=sha256((HERE/'check.py').read_bytes()).hexdigest(),
            scope="Distinct common-clock pilot; use only the center of the 12-kHz extracted original channel. "
                  "Keep the 3205 fit/test intervals, off-lags, thresholds, and independent historical receiver control.",
            measured=r)
args.output.write_text(json.dumps(result,separators=(',',':'))+'\n')
print(result['source_sha256'],r['positive_blocks'],r['num_blocks'],r['median_test_by_lag'],r['maximum_test_by_lag'],r['power_db_complex_fullscale'])
