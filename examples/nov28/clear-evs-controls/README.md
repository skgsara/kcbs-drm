# Do the public field checks exclude known EVS words?

The nine selected official EVS streams contained **12,480 known 13.2 kb/s words**. In **1,098** of them, at least one of the six public receiver checks could rule out an alternative field value. All 1,098 actual values survived. In 75 more words the transition check admitted all four possible values. The remaining 11,307 words had no applicable check. These counts measure false rejection on the original words. [Selection protocol](protocol.md) · [Per-file counts and observed values](official-fields.json)

| Public check | Field being checked, MSB first | Primary cases | Six replication cases | Actual field values rejected |
|---|---|---:|---:|---:|
| WB GSC AUDIO | b40 must be zero | 133 | 0 | 0 |
| SWB GSC INACTIVE | b44–47 must be in 0–10 | 358 | 334 | 0 |
| SWB GSC AUDIO, ordinary bandwidth-extension choice | b40 predicted from the mode | 0 | 145 | 0 |
| SWB GSC INACTIVE/BWE, ordinary encoder | b40–43 predicted as 1100 | 358 | 334 | 0 |
| Noisy SWB GSC AUDIO with qualifying pitch | b223 predicted as zero | 0 | 145 | 0 |
| SWB ACELP TRANSITION, stock sender rule | Actual b8–9 pair in the allowed set | 69 restrictive, 44 unrestricted | 59 restrictive, 31 unrestricted | 0 |

Individual rows overlap. All 145 AUDIO mode predictions were for b40 equal to one. This sample therefore gives no estimate for the opposite branch. A subsequent trace through both stock encoders explains the 692 INACTIVE observations. The ordinary branch writes noise index 6 in three bits and a zero subframe flag, producing 1100. A controlled 1.4-second zero PCM suffix nevertheless produced 70 different words in 70 slots when the prior audio changed. [Source trace and silence test](stock-inactive/README.md) At a new transmitter or under another encoding configuration, the public receiver keeps the observed value even if that prediction disagrees. [GSC rules and their basis](../../../scripts/evs_gsc_fields.py) · [INACTIVE field limits](../../../scripts/evs_intra_word.py)

The official TS 26.442 fixed-point decoder produced **4,659,200 PCM samples**, exactly matching the nine independently published outputs byte for byte. That establishes the provenance and correct interpretation of these known words. The suite includes narrowband, wideband and super-wideband. The original coded data and expected audio remain available from 3GPP. [Decoder results](decoder.json) · [Official member names and hashes](reference-members.json) · [TS 26.444](https://www.etsi.org/deliver/etsi_ts/126400_126499/126444/19.00.01_60/ts_126444v190001p.pdf)

## Controlled changes to known words

Keeping the original mode, we flipped each of the 256 payload bits individually in each of the 12,480 official clear words. The six checks flagged **3,805 of 3,194,880** changed words. Only changes in payload octets 0, 4, 26 and 31 affected any field report. At octets 15, 18, 21, 24, 27 and 30, **all 599,040 changes left the reports identical**. A change in a field that selects a rule can affect its report even if the changed word still passes. This experiment counts known differences from the original encoding. Some changed words can also be valid EVS. [Every payload offset](substitutions.json) · [Reproduction script](substitutions.py)

In a separate count, we replaced one eligible field with every other possible value, holding the rest of the original word fixed. The table counts alternatives per check and word. Single-bit flips and these field replacements are overlapping experiments.

| Target field | Wrong values excluded | Wrong values still allowed |
|---|---:|---:|
| WB GSC AUDIO b40 | 133 | 0 |
| SWB GSC INACTIVE b44–47 | 3,460 | 6,920 |
| SWB GSC AUDIO b40 | 145 | 0 |
| SWB GSC INACTIVE/BWE b40–43 | 10,380 | 0 |
| Noisy SWB GSC AUDIO b223 | 145 | 0 |
| SWB ACELP TRANSITION b8–9 | 246 | 363 |

## Broadcast controls and remaining uncertainty

In the subsequent blind erasure test, copying the preceding word filled six late bytes exactly in 2 of 3,060 held-out floating-point words and 2 of 3,120 words in a separate speech encode. Neither cohort yielded a complete group by that method. An independent radio replay corrected five directly readable bits in a previously rejected packet and completed counter 43945704. Both stations agreed on all 12 wire packets. Its 60 clear EVS words remain unresolved. [Blind erasure benchmark](erasure-benchmark/README.md) · [Radio comparison](transport-mlc4/README.md)

The four-iteration receiver subsequently acquired 8 complete groups in a separate held-out 3205 kHz interval, including two the one-iteration pass missed. The selected primary, 43873081, was absent from the 15,021-counter comparison inventory. [Held-out input and field score](iq-mlc4/README.md)

The group's 11:05 UTC handoff supplied 1,545 previous position-one words over 11,700 chronological slots. A rule restricted the possible field values in 417 of those words. All 417 were compatible. The stream contained 333 SWB INACTIVE examples, and 84 of its 131 SWB transition words had a restrictive predicted pair. Every position-two, three and four slot was marked erased. [Known P1 results](handoff-fields.json) · [Member handoff source and first-slot coordinates](../four-frequency/known-1105/README.md)

In an earlier sample, 306 of 308 restrictive SWB transition cases at position two agreed with the text-derived labels. Both disagreements concern word bit 8 of counter 43877110 at slots 37 and 41. Their direct fields come from different physical packets. Both comparison labels depend on the high byte of the final UTF-16LE period in the same CRC-checked text record. Its CRC and the original packet bytes reproduce, and the cause remains unresolved. [Prior score and both disagreements](../swb-transition/README.md)

On a separate 120-second interval of archived 3205 kHz IQ, the frozen receiver found 22 complete groups. In the first, counter 43872973, all 60 frame slots arrived and 5,280 clear bit values remained unresolved. Across the interval, 523 of 531 mode-based forecasts could be compared with a directly transmitted nibble. All 523 matched, including 131 at position two. A constant prediction of `0xC` on the same eligible slots gives the same result. The interval was held out for local field testing, and the contributor had previously reported reception totals for most of the recording. [IQ, forecasts and all primary slots](iq/README.md)

The member's report of 208 joint values at offsets 15 and 18 of counter 43917329 describes a separate filter. The material available for this study gives no executable predicate, per-frame decision trace or reference clear position-two word for it. An expert could independently test that filter by running its exact predicates on these known words, preserving each original word's coding mode and state. [Member report and assumptions](../member-text-leads.md)

## Reproduction

In the following held-out IQ minute, a mode-only forecast of a whole directly carried byte matched 11 of 30 eligible slots. The previously predicted high nibble matched 30/30. [Sealed whole-byte predictions and field score](../packet-bit-repair/README.md)

The downloader requests just the selected members of the official ZIP and verifies each member digest. An already extracted copy of the official testvec tree works as well. Running the field checks requires Python and NumPy. To repeat the PCM comparison, extract the inner ANSI C source ZIP from the ETSI TS 26.442 attachment and build its stock decoder. Three serial local runs of the nine complete decode-and-compare cases took a median 6.79 seconds. Each run had the original input words and expected PCM. The timings cover only those operations. [Timing receipt](decoder-timing.json)

The source release used here has attachment SHA-256 `17a167277c41d4d5267f4d2d0e4e20f847cb092c577491c04056b1116d3086d5` and inner ZIP SHA-256 `c2621dbd02969e6d2cbe20c8c34068d83604f5bc7bccf691110b58d198987e9f`. The decoder receipt records the actual local executable digest, which can differ across builds. [Fixed-point reference source](https://www.etsi.org/deliver/etsi_ts/126400_126499/126442/19.00.00_60/ts_126442v190000p0.zip)

```sh
case_dir=examples/nov28/clear-evs-controls
python "$case_dir/fetch_reference_members.py" "$vectors"
python "$case_dir/score.py" --official "$vectors" > /tmp/evs-official-fields.json
cmp /tmp/evs-official-fields.json "$case_dir/official-fields.json"
python "$case_dir/substitutions.py" "$vectors" > /tmp/evs-substitutions.json
cmp /tmp/evs-substitutions.json "$case_dir/substitutions.json"
python "$case_dir/decode_reference.py" "$vectors" "$decoder"
python "$case_dir/score.py" --handoff "$handoff/replay/known-first-position.192.gz" > /tmp/evs-handoff-fields.json
cmp /tmp/evs-handoff-fields.json "$case_dir/handoff-fields.json"
```
