# How long do two stock EVS decodes differ?

One encoded bit at payload offset 24 changed the decoded PCM in 28 of the next 34 frames at 16 kHz, even though those 34 encoded words were byte-identical. At 32 kHz the same streams gave different output in 33 of those 34 frames. All 205 preceding encoded words and decoded frames were identical. The inputs are two pairs of original 4.8-second synthetic SWB GSC AUDIO encodes, each produced from reset at 13.2 kb/s. [Published sender controls and hashes](../../nov27/validation/swb-gsc/sender-pairs.json)

| Changed payload offset at slot 205 | Changed encoded slots | First different PCM frame | Identical trailing words | Trailing frames with different PCM at 16 kHz | At 32 kHz |
|---|---|---:|---:|---:|---:|
| p24, wire bit 203 | 205 | 205 | 34 | 28 | 33 |
| p27, wire bit 225 | 205–207 | 205 | 32 | 17 | 31 |

The p27 inputs also differ at slots 206 and 207. The later differences reflect the combined decoder history from all three words. Decoding the identical trailing words from a fresh process on both sides gave sample-identical PCM in every comparison. Each output frame is the next 20 ms of signed 16-bit PCM emitted with delay compensation disabled. Slot and sample indices are zero-based. A frame counts as different when at least one sample differs. A later PCM difference can therefore occur without a new difference in that frame’s encoded bits. [Exact sample counts, changed frame ranges and PCM hashes](expected.json)

## Reproduce

Run with Python 3.10+, NumPy and the stock floating-point TS 26.443 executables. The script regenerates the four synthetic inputs, checks their source PCM, G.192 and mono EVS storage hashes against the original sender receipt, then runs the decoder separately for each full stream and each identical suffix. It takes no recordings or candidate words. To build the tools from the reference source, put the extracted C distribution at `work/ref/evs/src/c-code` and run `python scripts/build_evs_gcc_independent.py --out work/evs_gcc_independent` from the repository root. [Reference source and version](../../nov27/validation/tcx-zero-pair/README.md) · [GCC build script](../../../scripts/build_evs_gcc_independent.py)

```sh
case_dir=examples/nov28/evs-state-control
python "$case_dir/check.py" > /tmp/evs-state-control.json
cmp /tmp/evs-state-control.json "$case_dir/expected.json"
```

Use `--encoder /path/to/EVS_cod --decoder /path/to/EVS_dec` to select a different installation. The expected PCM hashes reproduced on two local reference builds with decoder SHA-256 `e07384175dad995379fb738a79e949cd2d25b002f65ad0fa6bda6b8f7a1f0184` and `93e19f7ceead1fa18c1c3ccbd480177a56163dd7a53b3db13e5d4a9042c011fd`.
