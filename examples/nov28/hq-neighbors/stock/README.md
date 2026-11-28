# Stock sender controls

The public 36-second tonal input has 1,800 consecutive 20 ms frames. At 13.2 kb/s SWB, the stock TS 26.443 sender produced 19 qualifying mode triples. The fixture includes the three original 33-byte words and the encoder's attack and carryover state for every triple. The instrumented and unmodified encoders emitted byte-identical streams. [Fixtures](witnesses.json) · [Full-stream replay result](result.json)

| Preceding, middle, following mode | Middle bit 8 is zero | Middle bit 8 is one |
|---|---:|---:|
| F9 F8 F9 | 10 | 0 |
| F9 F8 F8 | 8 | 1 |

At slot 425, the three words begin `F9 49`, `F8 83`, `F8 80`. The middle frame detected a fresh attack. The next frame's transient flag was set from the previous frame's carryover. At slot 16 the same mode sequence had a normal middle word. These two cases show why a final F8 leaves the middle bit ambiguous.

In the November 2021 floating-point 3GPP EVS source, `lib_enc/hq_core_enc.c` calls the transient detector and `lib_enc/detect_transient.c` updates its state. The classifier and bit writer are in `lib_enc/hq_classifier_enc.c` and `lib_enc/hq_lr_enc.c`. All 57 frame occurrences used the same extension, 640 input samples per frame, and the unswitched SWB branch. An extension change can reset the detector.

To check the recorded events from the repository root, use the first command below. To recreate the stream with an installed reference encoder, use the second.

```sh
study=examples/nov28/hq-neighbors/stock
python "$study/proof.py"
python "$study/proof.py" --encoder /path/to/EVS_cod --checkout .
```

To rerun the instrumentation, supply a Linux GCC toolchain, the stock encoder and the November 2021 reference C source. The probe compiles in a temporary directory.

```sh
python "$study/native_replay.py" . /path/to/EVS_cod /path/to/c-code --out regenerated-witnesses.json
python "$study/proof.py" --witnesses regenerated-witnesses.json
```
