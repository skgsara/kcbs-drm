# Checking EVS frame order from broadcast IQ

Two EVS fields independently picked the published frame order on a previously unused minute of 6140 kHz IQ. Across 42 complete groups, only ascending cycles with positions 1, 2, 3, 4 agreed with both fields at every tested pair. The comparison covered 96 specified layouts. The receiver used the directly transmitted mode octet and payload octet 5. [Frozen test](protocol.md) · [Results and per-slot evidence](nov19-result.json)

## November 19 blind test

We fixed the scorer, IQ window, first-complete-group selection and zero-contradiction criterion before demodulating seconds 180–240 of the group's 17:31:39 recording. All 46 received counter IDs were absent from the earlier inventory. The first pass produced 132 CRC-valid data units, including 42 complete groups. After scoring, a second finite-file Dream build reproduced the 104,676-byte MSC dump and the accepted data units byte for byte. All 528 physical packets contributing to these data units passed CRC. [Frozen revision](https://github.com/skgsara/kcbs-drm/commit/36c76d98817b5b968b50242f231fc1b09ff864bd) · [MSC dump](nov19-msc.bin) · [Accepted data units](nov19-data-units.npz)

For each proposed order, we compared the HQ switch flag to the preceding core. Separately, we used a successor ACELP speech class to predict allowed values of its predecessor's two-bit class. Successor class 2 excludes predecessor class 0. Successor class 3 excludes 2 and 3, predicting a zero high bit. Both checks can be scored against bits withheld from the prediction and directly received in the same IQ.

| Evidence in the published order | Primary group 43288755 | All 42 groups, inside each group | Between consecutive complete groups |
|---|---:|---:|---:|
| Slot pairs per layout | 59 | 2,478 | 38 |
| HQ flags checked / predicted switches | 0 / 0 | 89 / 13 | 2 / 1 |
| ACELP class pairs / restrictive predictions | 34 / 14 | 894 / 370 | 16 / 5 |
| Predicted zero high bits / disagreements | 5 / 0 | 104 / 0 | 1 / 0 |
| Layouts surviving HQ alone | 96 | 1 | 12 |
| Layouts surviving ACELP alone | 2 | 1 | 24 |
| Layouts surviving both | 2 | 1 | 8 |

The primary group alone leaves both ascending 1,2,3,4 and ascending 2,1,3,4 possible. Each had zero contradictions. Across all 42 groups the closest alternative was ascending 1,2,4,3, with five HQ and 28 ACELP contradictions. Counting each group alone, five singled out the published layout and four admitted every layout. These results concern the 96 arrangements in the protocol. A group containing only TCX20 words supplies neither of these checks. [All alternatives can be rescored here](check.py)

Counter 43288755 supplied 15 words at each position. The directly received mode and 21 payload octets account for 2,640 bits per position. That leaves 1,320 unknown bits per position, **5,280 in total and zero complete clear words**. The five predicted high bits were already visible, at one slot each in positions 1–3 and at two slots in position 4. The receipt gives the exact bit offsets, alternatives and received values. [Primary evidence](nov19-result.json)

After the blind test, we applied two existing payload checks to these 42 groups. Eight words carried mode `F9`, which predicts a zero high bit in payload byte 0 under the stock HQ encoder. They occurred at all four positions, with counts 1, 1, 3 and 3. Fourteen words carried `FA`, which excludes the high-bit pair 11. The target bits have no independent score in this minute. For the late TCX20 payload, every one of the 275 TCX20 words had a received one where the proposed zero-fill branch requires a zero. This rules out that branch for all 275. [HQ class checker](../hq-class/observe.py) · [TCX20 zero-fill test](../tcx-zero-pair/README.md)

## Why the TCX20 extension stops short at 43865914

The member's 3205 kHz handoff is a separate development example. All 60 mode octets indicate super-wideband TCX20. For each of the 15 second-position words the handoff already supplies a 128-bit contiguous prefix supported by a text CRC. A bounded EVS reference reader located the intelligent gap filling (IGF) whitening field in each prefix. All 15 contained code `100`, which turns whitening off for both frequency tiles. Of its 45 bits, 42 were on directly transmitted lanes. The other three were at slot 25 and relied on the previously supplied prefix. Locating the fields used the prefixes. [Input prefixes](../tcx-zero-pair/43865914-p2-prefixes.json) · [Per-slot IGF results](igf-expected.json)

Numbering from the mode octet's high bit as zero, the complete IGF field ended between bits 88 and 103 exclusive. Even the arithmetic reader's lookahead before whitening ended by bit 113 exclusive. The first unresolved second-position payload byte starts at bit 128. This establishes exactly why checking IGF leaves all six late bytes open in this example.

The stock TCX20 sender also has a three-bit noise-fill field that depends on earlier frames. After a transmitted non-1 and exactly six or seven consecutive indices of 1, the next index can take any value except 2. In six reference encodes this condition occurred 24 times with zero contradictions. Reversing the streams produced one contradiction. On 43865914 only slot 54 can give a 1 at either of the two possible bit alignments. No six-frame run can occur entirely within the group, so this check supplies no new bits there. [State transitions and scorer](noise.py)

## Replay

From the repository root, the following commands reproduce the packet assembly, all 96 layout scores and the primary projection. Output directories for receiver runs must be new.

```sh
case_dir=examples/nov27/validation/frame-order
python scripts/salvage_msc_packets.py "$case_dir/nov19-msc.bin" --transport-only --out /tmp/nov19-order-transport
cmp /tmp/nov19-order-transport/data_units.npz "$case_dir/nov19-data-units.npz"
python "$case_dir/check.py" "$case_dir/nov19-data-units.npz" --boundaries --out /tmp/nov19-order-score.json
python scripts/project_evs_group.py "$case_dir/nov19-data-units.npz" --counter 43288755 --format tsv
```

With the member's original 912 kHz CS8 file and the finite-file Dream build, run the following to reproduce the RF stage. The recording filename and IQ window digest are in the protocol.

```sh
python scripts/demod_iq_window.py "$iq_file" /tmp/nov19-order-rf --sample-rate 912000 --start 180 --seconds 60 --offset-hz 0 --reception-profile wiener --mlc-iterations 1
cmp /tmp/nov19-order-rf/msc.bin "$case_dir/nov19-msc.bin"
```

For the separate TCX20 development controls, use the pinned November 4, 2021 TS 26.443 C source and GCC. The whitening comparison reads only the handoff prefixes. The noise checker with no arguments enumerates the allowed state transitions and all 16 high-nibble inputs. [Reference software](../tcx-zero-pair/README.md)

```sh
python "$case_dir/igf_control.py" build /path/to/c-code /tmp/nov19-igf-reader
python "$case_dir/igf_control.py" check /tmp/nov19-igf-reader /tmp/nov19-igf.json
cmp /tmp/nov19-igf.json "$case_dir/igf-expected.json"
python "$case_dir/noise.py"
```
