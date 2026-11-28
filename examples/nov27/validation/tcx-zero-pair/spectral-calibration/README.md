# Check the TCX spectral comparison on known first-position words

For counter `43865914`, the member’s spectral checker reproduces the arithmetic-coded spectrum of all 15 text-supported first-position words. It also reproduces the spectrum of all 15 after their payload-octet-30 low bits are inverted. All 15 altered words give different 16 kHz PCM in their own output slots. The same comparison accepts one word after the octet-24 change and nine after the octet-27 change.

| Fixed input for all 15 first positions | Target trace records | Exact spectral slices | Target PCM slots changed |
| --- | ---: | ---: | ---: |
| Original | 15 | 15 | 0 |
| Invert payload octet 24 low bit | 15 | 1 | 15 |
| Invert payload octet 27 low bit | 15 | 9 | 15 |
| Invert payload octet 30 low bit | 15 | 15 | 15 |

Offsets exclude the mode octet. The bit changed in payload octet 30 is physical bit 255, counting from zero at the mode’s most significant bit. All 15 compared spectral slices include bit 255 in every trial.

## Reproduce

With Python 3.10 or later, run this command from this directory. Supply the decoder built with the 17:44/17:56 receiver supplement’s `source/native/tcx_check.c`. It emits one `T,` diagnostic for each completed spectral comparison.

```sh
python3 -I check.py --decoder /path/to/EVS_tcx_trace > result.json
```

Each of the four runs starts from decoder reset. The script compares the per-cycle spectral mismatch counts and the number of changed PCM slots with the expected results. Exit status 0 means they match, 1 indicates different observations, and 2 indicates an input or execution error. If you have the supplement and floating-point TS 26.443 source but need its observer executable, run the supplement’s build command from the extracted supplement directory.

```sh
python3 source/native/build_tcx.py /path/to/c-code /tmp/EVS_tcx_trace
```

The observer sends the quantized coefficients, residuals, harmonic mapping and bit budget from the decoder to the reference spectral arithmetic encoder. It compares each serialized bit in the spectral slice with the corresponding input bit. A trace gives that comparison and its bounds. The separate native status replay records bad-frame and bit-error flags at additional decoder checkpoints. [Expected per-cycle results and hashes](expected.json) · [Independent status replay for six complete groups](../43865914-spectral-controls.json)

## Input and scope

The packed fixture preserves all 3,660 consecutive slots from counter `43865854`, phase 0, through the end of counter `43865914`. It holds 705 complete, previously text-supported first-position words and reconstructs the other 2,955 slots as explicit erasures. The first target slot is 3,600. The four runs have byte-identical input before that slot. Only the 15 selected first-position words can change.

The fixture comes from the `1756` directory of the November 27 receiver supplement. Each 499-byte record in `first-position.bin` contains one four-byte big-endian counter and fifteen 33-byte words in phase/cycle order. Missing counter records represent 60 erasures. The verifier pins both the packed file and the reconstructed chronological G.192 slice. The expected metadata give the original supplement ZIP and source timeline digests. [Packed input](first-position.bin) · [Fixture provenance](expected.json)

The measurement shows which changes this particular spectral comparison distinguishes. To calibrate a different implementation, retain the same chronological inputs and report its per-frame decisions, compared region and handling of missing traces. An independent genuine-sender test observed 279 exact SWB TCX20 spectral slices on the full synthetic timeline and the same 279 across four single-position replays. [Synthetic control counts and stream digests](synthetic-check.json)
