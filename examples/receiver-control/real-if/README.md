# Mono real-IF receiver controls

On the first 90 seconds of the November 27 HDSDR capture, two ways of converting the same mono signal to I/Q recovered identical bytes at **816 assigned packet coordinates and 201 complete data-unit coordinates**. On the authored DRM test service, conversion to mono IF and back reproduced the entire original stereo receiver dump. All **2,113 supplied EVS words** matched the sender at their original slots.

| Check | Historical HDSDR | Authored test service |
|---|---:|---:|
| Input | First 4,320,000 mono samples, 90 s | 3,340,800 stereo sample pairs, 69.6 s |
| Comparator | Independent analytic-signal conversion of the same RF | Original stereo I/Q and the pristine sender data |
| Complete data units | 201, of which 189 form 63 complete three-phase groups | 100 of the 120 scored phases |
| Packet comparison | 816/816 identical assigned 179-byte bodies | 424/424 assigned bodies match the sender |
| Additional result | 8 physical packets differed across 2 of 218 native rows. All 8 failed their CRC on both paths. | 287 of 2,400 words were missing or partial. |

**Historical source.** The HDSDR header records November 27, 2026 at 07:55:48.790 and a tuning frequency of 6,134,000 Hz. The upper lobe at +6,000 Hz carries the 6140 kHz signal. HDSDR's header contains no time-zone flag. The original counter-based estimate places capture start around 07:55:55–07:55:59 UTC. The earlier report gives 1,178 complete data units for the full recording. The 201-unit comparison here covers only the fixed first 90 seconds. Both paths use the same Dream receiver, packet checks and original RF. [Public mono WAV](https://github.com/skgsara/kcbs-drm/releases/download/samples-2026-11-28/8min-6140drm-mono.wav) · [Historical report](../../../docs/november-2026.md) · [Historical receipt](historical.json)

**Synthetic source.** The public fixture carries known sender words on service EF0201, labelled *DRM IQ TEST*. The test makes a mono PCM16 waveform from its original I/Q with `round(0.5 × Re{(I+jQ) exp(+j2πn/8)})` at 48 kHz, with zero samples clipped. It compares the entire stereo and mono receiver dumps, then checks each supplied word in the declared 40-group interval against the original stock encoder stream. This fixture includes deliberate packet damage. [Original I/Q](../challenge-iq48.flac) · [Sender data](../fixture/sender.json) · [Synthetic receipt](synthetic.json)

## Replay

Run from the repository root with Python 3.10+, NumPy, SciPy, SoundFile and a finite-input Dream with the MSC dump hook. Pass a fresh local output directory for each run. No EVS decoder is required to check the emitted words. [Dream build instructions](../../../build/README.md)

```sh
curl -fL -o /tmp/hdsdr-6140.wav \
  https://github.com/skgsara/kcbs-drm/releases/download/samples-2026-11-28/8min-6140drm-mono.wav
python examples/receiver-control/real-if/replay.py historical /tmp/hdsdr-6140.wav \
  --dream build/dream-src/dream --out /tmp/real-if-historical
python examples/receiver-control/real-if/replay.py synthetic examples/receiver-control/challenge-iq48.flac \
  --dream build/dream-src/dream --out /tmp/real-if-synthetic
```

The helper checks the original file SHA-256 before reading samples. Both runs use one Wiener pass with one multilevel decoding iteration. The historical reference takes the Hilbert analytic signal, shifts it by −6 kHz and downsamples 4:1 with a Kaiser filter before feeding the ordinary stereo I/Q path. The product path takes the original mono samples directly through `demod_iq_window.py --real-if-hz 6000`. The reports identify the Dream executable used for each run and write the local result as `receipt.json`. The historical receipt also hashes the sorted accepted units, each serialized as a four-byte big-endian counter, one phase byte and the 716-byte unit. Different builds can change failed-packet decisions. [Replay script](replay.py)
