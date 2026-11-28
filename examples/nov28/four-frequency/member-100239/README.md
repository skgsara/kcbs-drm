# November 28 five-minute 6100 AM and 6140 DRM recording

The group supplied `6100-12k.cf32` and `6140-12k.cf32`. Each contains 3,600,000 complex samples, or 300 seconds at the reported 12 kHz. The files contain no timing headers. The group places sample zero at 10:02:39 Beijing (02:02:39 UTC) and reports programme alignment for the first 126 seconds. The remaining 174 seconds have no reported passing programme comparison.

## Independent programme-timing test

The directly transmitted EVS mode byte describes how the encoder represented a short interval of sound. We used an earlier confirmed simulcast to estimate the relative energy in nine AM frequency bands for each mode. This gave us a prediction to compare with the new AM recording using only its audio and the mode bytes received on 6140. The model used 4,440 mode observations from November 27. On a separate 90-second interval of that earlier recording, its correlation was 0.460. The largest displaced-control correlation there was 0.118. [Frozen method](mode-protocol.md) · [Calibration and wrong-date controls](mode-calibration.json)

In the new pair, seconds 12–51 on the DRM timeline selected an offset of −5.26 seconds. The first frame of counter 43914151 defines the DRM timeline origin. A feature at DRM second 76 thus predicts the corresponding feature at AM file second 70.74. We held that offset fixed for all three later comparisons. The timing controls use large displacements of 200 ms bins, so the precision of the fitted lag at individual frame boundaries is unknown.

| Window in the 6100 AM file | Usable 200 ms bins | Correlation | Highest displaced control | Result |
| --- | ---: | ---: | ---: | --- |
| 70.74–108.74 s | 184/190 | 0.288 | 0.125 | Passed, including both halves |
| 132.74–195.74 s | 180/315 | 0.161 | 0.182 | Insufficient coverage and timing evidence |
| 219.74–281.74 s | 270/310 | 0.016 | 0.090 | Timing check failed |

The first window provides independent evidence of shared programme timing **inside** the interval reported by the group. We knew the group's 126-second claim when choosing the windows and fixed the protocol before scoring their files. The two later windows leave programme alignment unconfirmed. A precise switch time, the identity of the item being broadcast and the clear values of masked EVS bytes remain unresolved. The file offset includes alignment of the receiver timelines. [Per-window scores, denominators and controls](mode-holdout.json)

## What the RF recordings establish

The 6140 receiver identified service `A00002`, labelled 조선중앙제2라지오방송. Across five minutes, 747 of 747 FAC blocks and 249 of 250 SDC blocks passed CRC. A second replay using the public receiver and a lossless float WAV wrapper reproduced all 742 assigned data units byte for byte. The full run obtained 247 consecutive complete groups, plus phase zero of counter 43914398. The first complete group, 43914151, contains all 60 transported slots and 10,560 directly transmitted bits. Its IQ-only projection gives zero complete clear EVS words. [Capture hashes and measurements](reception.json)

The interval tests reset the DRM receiver at the first sample of each interval. All 734 data units recovered by the two shorter runs matched their counterparts in the full run. The full run retained eight additional data units around the split.

| Samples tested, time from file start | DRM data units passing CRC and assigned to a counter | Complete groups | AM carrier was the strongest FFT bin | Six-second AM windows passing the audio quality check |
| --- | ---: | ---: | ---: | ---: |
| 0–126 s | 307 | 102 (43914151–43914252) | 126/126 seconds | 16/21 |
| 126–300 s | 427 | 142 (43914256–43914397) | 174/174 seconds | 18/29 |

The 6100 carrier stayed within 100 Hz of nominal center and its median offset was −54 Hz in both intervals. The AM quality test measures carrier strength, modulation and audio-band occupancy. The DRM CRCs check received packets. Programme identity requires evidence that links the content of the two signals.

The 742 data units include 3,710 first-position slots. None of the 248 assigned counters occurs in the previously supplied text-supported first-position archives we checked. The uploaded pair had no first-position frame export or window-by-window alignment log. The first-position audio comparison therefore yields no independent lag or programme score for this pair. The earlier `58 18` candidate belongs to a different counter, 43869343. [Earlier programme comparison](../known-1105/README.md)

## Reproduce with the two originals

Run from the repository root with the originals in that directory. Use a fresh output directory and the finite-input Dream build. [Build instructions](../../../../build/README.md)

```sh
mkdir -p work/member-100239
out=work/member-100239
python examples/nov28/four-frequency/member-100239/receive_am.py 6100-12k.cf32 "$out/6100.wav" > "$out/am.json"
python - <<'PY'
from hashlib import sha256
from pathlib import Path
import numpy as np
import soundfile as sf

raw = Path("6140-12k.cf32").read_bytes()
assert sha256(raw).hexdigest() == "0972ce82793b2559d6c21299f555b4db0776f7b8e349da3e6dabf1426537a7a0"
iq = np.frombuffer(raw, dtype="<f4").reshape(3600000, 2)
sf.write("work/member-100239/6140-iq.wav", iq, 12000, subtype="FLOAT")
PY
for window in 'whole 0 300' 'first 0 126' 'later 126 174'; do
    set -- $window
    python scripts/demod_iq_window.py "$out/6140-iq.wav" "$out/$1" --start "$2" --seconds "$3" --reception-profile wiener --mlc-iterations 1
    python scripts/salvage_msc_packets.py "$out/$1/msc.bin" --transport-only --save-packets --out "$out/$1/transport"
done
python scripts/project_evs_group.py --packets "$out/whole/transport/packets.npz" --counter 43914151 --field-checks
python examples/nov28/four-frequency/member-100239/mode_timing.py score "$out/whole/transport/packets.npz" "$out/6100.wav"
```

The 6100 WAV is 12 kHz mono PCM. Envelope detection and zero-phase filtering retain sample zero and all 3,600,000 samples. The DRM replay uses the original I and Q values in the same order. The supplied hashes allow comparison across receiver builds.

The score command uses the published spectral templates. To regenerate them, supply the November 27 11:05 handoff's packet archive and 3250 AM track, plus the separate November 19 6100 AM control WAV. The calibration receipt records the three input hashes. [November 19 control recording details](../nov19-6100.json)

```sh
python examples/nov28/four-frequency/member-100239/mode_timing.py calibrate \
    "$handoff/receiver/packets.npz" "$handoff/audio/3250-AM-12k-mono.wav" "$nov19_control_wav" \
    --first-counter 43869284 --templates-out "$out/rebuilt-templates.npy"
```
