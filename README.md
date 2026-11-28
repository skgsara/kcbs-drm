# November 28 paired shortwave recordings

`pilot-1657/` contains the original 3205 kHz I/Q from Yokohama and both 3250 kHz I/Q attempts from Edogawa. `3250-am.wav` is the conventional AM envelope audio from the successful reconnect.

`common-clock/` contains one 180-second Edogawa I/Q capture centered at 6122 kHz. The 6100 kHz carrier lies 22 kHz below center and the 6140 kHz channel lies 18 kHz above it. `6100-am.wav` is the envelope audio with one sample per four input pairs. Both listening WAVs use mono 12 kHz PCM. Programme identity across the radio frequencies remains unconfirmed.

Every FLAC contains the full original signed stereo PCM16 I/Q at 48 kHz. Each timing CSV has received packet timestamps and original sample offsets. The two `recordings.json` files document coverage, missing timestamps and SHA-256 digests. This command restores the recorder's canonical PCM WAV with the original file hash. Install the Python SoundFile package first.

```sh
python - 7l4iou-6122-iq48.flac original.wav <<'PY'
import sys, wave
import soundfile as sf
with sf.SoundFile(sys.argv[1]) as src, wave.open(sys.argv[2], 'wb') as dst:
    dst.setparams((2, 2, 48000, 0, 'NONE', 'not compressed'))
    for chunk in src.blocks(blocksize=48000, dtype='int16'):
        dst.writeframes(chunk.astype('<i2', copy=False).tobytes())
PY
```
