# Independent receiver check on November 27 at 21:26 UTC

Use the full simultaneous 180-second recordings of 3205 kHz. JL1EDU Yokohama supplies the primary native MSC dump. 7L4IOU Edogawa supplies the witness. The two files below are byte-for-byte copies of the original default receiver outputs.

| File | Bytes | Native MSC SHA-256 | Source IQ WAV SHA-256 |
| --- | ---: | --- | --- |
| `primary.msc.bin` | 317688 | `b1c5bcb0d4c8bbf22841e75c1dea491a93f7ead03a402d04c82698a84ec9b9f9` | `ec2e54504d26f9e1cc98abef11c52be7263ff2a1cf8457efe3ca38451c5007e3` |
| `witness.msc.bin` | 325008 | `c36d4f0763a02d87b28d4afb033140fae970666bcc73c8dfb50df1e1a107e7fc` | `d96c3f22638c45ef1ef966a022f03afb29032b0fbb70d9e116783b415d40c8d0` |

Each receiver manifest records 8,640,000 IQ pairs at 48 kHz, starting at sample zero with zero channel offset. The archived receiver command used `demod_iq_window.py INPUT default --seconds 180 --signalling`. The manifests identify Dream binary SHA-256 `3f24768b2a3075ad8cd4be6ada18dadaf695f69ffbb90b6fd38a175459471a82`. The command left interpolation and iteration settings at their defaults, and the manifests omit their numerical values. The earlier impulse-filter study used these recordings and found 31 matching DUs in common across its multi-profile baseline. It tested filtering, so this is a retrospective recording control for a separately frozen packet-correction rule. [Prior RF study](../../../nov27/validation/rf-iterations/README.md)

1. Run the frozen `../repair.py` once on the primary file. Preserve every proposal and abstention. Seal the SHA-256 of the full proposal report and proposed MSC, then open the witness for comparison.
2. Align the two original dumps using unchanged, CRC-valid packet bytes. Score a proposed wire only if the native witness row is independently located and the witness received the same packet ordinal with a valid header and CRC. Compare all 182 bytes. Report exact matches, disagreements and unavailable witnesses separately. A witness receives no credit for an inferred repair.
3. Keep this recording separate from controls on other dates or receivers. Run the complete primary file in the stated direction once, including an empty outcome if there are no proposals or no usable witnesses.

From this directory, replace `OUT` with a new writable output directory before running the primary pass.

```sh
mkdir OUT
python ../repair.py primary.msc.bin OUT/proposed.msc.bin OUT/predictions.json
sha256sum OUT/predictions.json OUT/proposed.msc.bin
```
