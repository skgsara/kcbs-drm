# Prospective KCBS-2 IQ, November 28–29 UTC

The original `iq48` recordings from the acquisition registered in
`examples/nov28/prospective-acquisition/` on branch `claude/focused-faraday-4nhtp3`
(registration commit `a889a32`, committed before recording began). Each
recording comes from a public UberSDR receiver. Yokohama is `jl1edu`; Edogawa
is `7l4iou`.

A recording tuned to 6122 kHz holds two channels on one sample clock: the
6140 kHz DRM channel at +18 kHz and the 6100 kHz AM carrier at −22 kHz.

Each recording folder holds:

- `part-NN.flac`: playable 300-second parts of the original signed 16-bit
  stereo I/Q at 48 kHz.
- `parts.json`: per-part SHA-256 and sample ranges.
- `receipt.json`: the recorder's receipt, including the PCM SHA-256 of the
  whole recording.
- `timing.csv.gz`: received packet sample offsets and receiver timestamps.

`session-*/log.jsonl` records every carrier probe, assignment and segment.

To rebuild and verify the recorder's original WAV (requires the Python
SoundFile package):

```sh
python restore.py session-M/<recording> original.wav
```
