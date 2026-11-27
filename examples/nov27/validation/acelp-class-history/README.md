# A following ACELP frame can check the preceding speech class

An IQ-only receiver withheld the two directly transmitted speech-class bits of an earlier frame and used its successor to predict which values were possible. Four predictions restricted the earlier class in a fresh 3205 kHz recording. All four agreed with the withheld bits. Three predicted the high bit exactly. All three high bits were zero. The two-bit field lies in directly received payload octet 5, so these checks add zero masked bits to a word. [Frozen protocol](protocol.md) · [Results and slot coordinates](fresh-results.json)

## The fresh reception

7L4IOU in Edogawa supplied 180 seconds of 48 kHz complex IQ beginning at 22:27 UTC on November 27. The transport receiver recovered 200 CRC-valid data units and 52 complete counters. The first complete counter, **43903388**, supplied all 60 slots and had zero eligible pairs. The direct projection has 10,560 bits across the four positions, with 5,280 masked bits unresolved and all 60 words erased. The first counter remains the primary result.

The 16-second IQ excerpt below reproduces the primary counter. Two finite-file Dream builds recovered all three data units byte for byte. The receipt includes the capture and clip hashes, the demodulation commands and the CRCs of the twelve packets. [Download the 12 kHz IQ clip](7l4iou-3205-43903388-iq12.wav) · [RF capture and replay receipt](iq-receipt.json)

The same clip also contains the first restrictive case, counter 43903395. Its three data units match the full recording in both builds. From the repository root, after replaying the two commands in the IQ receipt, run `python examples/nov27/validation/acelp-class-history/check.py replay/du/data_units.npz --counter 43903395` to inspect the prediction and held-back value at slot 41.

Of 57 eligible adjacent pairs across all 52 counters, the successor excluded at least one earlier class in four pairs. The following rows list every such case. Slots are zero-based and positions are one-based. [CRC-checked data units](edogawa-data-units.npz)

| Counter | Earlier slot | Position | Successor class | Earlier values excluded | Withheld earlier class |
|---|---:|---:|---:|---|---:|
| 43903395 | 41 | 2 | 2 | 0 | 3 |
| 43903516 | 2 | 3 | 3 | 2, 3 | 0 |
| 43903516 | 5 | 2 | 3 | 2, 3 | 0 |
| 43903527 | 22 | 3 | 3 | 2, 3 | 0 |

From this directory, run the frozen checker on the supplied recording's data units. Omit the counter to replay the full 52-group count.

```sh
python check.py edogawa-data-units.npz --counter 43903388
python check.py edogawa-data-units.npz
```

## What the class means

In ordinary 13.2 kb/s EVS ACELP, eligible GENERIC and TRANSITION frames explicitly signal a two-bit class. Code 0 means unvoiced, code 1 can represent either transition direction, code 2 means voiced, and code 3 means onset. The stock encoder uses the previous classifier state when assigning the current class. For two immediately successive words with an explicit class, that state machine excludes the ordered pairs (0,2), (2,3) and (3,3). A successor of 3 therefore predicts that the high bit of the earlier class is zero. A successor of 2 excludes one of four earlier values. A successor of 0 or 1 leaves the earlier field unconstrained.

The predictor reads only the earlier mode octet, successor mode octet and successor payload octet 5. Its arguments exclude the earlier payload. It abstains on a missing word, an ineligible coding type or a variable-length field whose location cannot be read from the mode alone. Each 60-slot group has at most 59 adjacent pairs. The standard reference files are `lib_enc/sig_clas.c` (classification), `lib_enc/FEC_enc.c` (two-bit coding), `lib_enc/evs_enc.c` (state update) and `lib_com/rom_com.c` (mode table). [Frozen predictor and scoring code](check.py)

Run `python native.py --encoder /path/to/EVS_cod` in this directory for a stock-sender control. It encodes the same 48-second input under NB, WB and SWB caps and applies the frozen checker. Of 714, 307 and 306 eligible pairs respectively, 111, 7 and 7 gave restrictive predictions. All agreed with the emitted class. [Synthetic sender control](native.py)

## Checks on the development recordings

| Recording | Complete groups | Eligible pairs | Pairs that excluded a value | Earlier high bits predicted | Contradictions |
|---|---:|---:|---:|---:|---:|
| November 15, 3205 kHz | 109 | 1,021 | 304 | 156 | 0 |
| November 27, earlier Edogawa recording | 74 | 83 | 28 | 9 | 0 |
| November 27, 17:44 supplement | 295 | 1,069 | 295 | 162 | 0 |
| November 27, 17:56 supplement | 644 | 10,488 | 2,958 | 1,461 | 0 |

The 12,661 pairs included all 13 allowed class combinations. Reading the same two classes in reverse order violated the rule in 1,879 pairs. This retrospective control supports the assumed direction of time for the checked words. It also demonstrates how the rule can detect some frame-order errors. [Counts by earlier position and class pair](development-results.json)

Different coding types provide different kinds of evidence. An HQ successor can report prior high-band pulse presence only in eligible narrowband or wideband words. All 12,358 HQ words in these four recordings signalled super-wideband. A synthetic TCX20 example separately demonstrates that even two complete adjacent words leave a bit in payload octet 30 ambiguous. [HQ source control and on-air census](../hq-history/README.md) · [TCX20 neighbor comparison](../native-tcx-neighbors.json)
