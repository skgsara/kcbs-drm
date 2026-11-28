# Restoring the original stereo IQ WAV

The two channels contain interleaved I and Q at 48,000 sample pairs per second. From this directory, replace the station name as needed and write the result to a regular file so FFmpeg can finalize the RIFF header.

```sh
station=edogawa
ffmpeg -nostdin -v error -i "$station-6140khz-iq48.flac" -map 0:a:0 \
    -c:a pcm_s16le -map_metadata -1 -map_chapters -1 -fflags +bitexact \
    -flags:a +bitexact "$station-restored.wav"
sha256sum "$station-restored.wav"
```

Compare the result with the station's `wav_sha256` in `verification.json`. The `.timing.csv` and `.capture.json` files preserve each recorder's original sidecars. A blank timestamp keeps its original position in the sample timeline.
