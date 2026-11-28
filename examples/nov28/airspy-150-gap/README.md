# A complete unseen counter from four seconds of IQ

Counter **43288730** was fixed by number before four previously unread seconds of the November 19 Airspy recording were retrieved. It was absent from the 14,742-counter inventory. Three consecutive data units at that counter passed all 12 packet CRCs and all three DU CRCs. The four seconds alone reproduced the same 60 transmitted frame slots byte for byte. The receiver supplied **zero complete clear EVS words**. [Protocol](protocol.md) · [Freeze commit](https://github.com/skgsara/kcbs-drm/commit/283590f30c14615566933881f0e7946335d024bf) · [Exact retrieval and checksum](range.json)

## Which samples supplied the target

The source was the recording labelled 6140 kHz, with 912,000 signed complex sample pairs per second. All three runs used the same 30-second input grid, the same receiver settings and cold acquisition. The new samples were seconds 150–154 of the source file. Replacements with zero took place **before** frequency conversion and filtering. No neighbouring counter could replace the chosen target. [Input definitions and historical inventory hashes](plan.json)

| IQ supplied | Complete groups received | Target's zero-based native record indices |
| --- | ---: | --- |
| Full original input, seconds 130–160 | 20 | 51, 52, 53 |
| Same input with seconds 150–154 zeroed | 17 | Target absent |
| Only seconds 150–154, with both flanks zeroed | 1 | 2, 3, 4 |

Each of the three target records in the first and third runs matched across all 728 transmitted bytes. The run with the gap zeroed still recovered nearby counter 43288732. That result illustrates why we tested one specific counter and kept the blanked control. [Per-run native CRCs, group counts and target hashes](target-result.json) · [Received target data](target-data-units.npz)

## What can be verified about the audio

In each of the four frame positions, all 15 transmitted slots arrived. Each position supplied 2,640 directly readable bits and 1,320 bits whose clear values remain unresolved. The unchanged EVS reporter produced byte-identical results from the full and isolated inputs. Source isolation establishes where the bits came from. Both inputs use the same radio recording and therefore supply one observation of the transmission. [Evidence for all 60 slots](target-evidence.json)

The received mode bytes comprise 34 super-wideband generic, 16 voiced and 10 transition ACELP frames. In nine transition frames the existing codec rule predicts one of four possible values for word bits 8–9. The predictions, grouped by position below, are conditional on the stock encoder rule. None of the 18 bit coordinates has an independent clear label. A previous text-labelled frame at 43877110 disagreed with this rule. [Historical counterexample](../bit-evidence/README.md#comparing-individual-bits-at-counter-43877110)

| Position | Slots predicted `00` | Slots predicted `01` | All four values allowed |
| --- | --- | --- | --- |
| 1 | 56 | 8, 32 | — |
| 2 | 29, 53 | 17, 57 | 45 |
| 3 | — | 2 | — |
| 4 | 39 | — | — |

The three alternatives excluded by a `00` prediction are `01`, `10` and `11`. For a `01` prediction the other alternatives are `00`, `10` and `11`. The table uses zero-based slot numbers. All four positions retained 15 full-word erasures.

## Historical evidence for the four second-position predictions

The published November 27 data contain 231 second-position frames for which this rule selected a single two-bit value and a text-supported label was available. The other 79 labelled frames admitted multiple values. The prediction `00` matched 141 of 142 labels across 119 counters, 101 text-record occurrences and 58 distinct body fragments. The prediction `01` matched all 89 labels across 74 counters, 64 occurrences and 42 fragments. The two sets share 34 body fragments. Altogether the 231 frames draw on 66 distinct fragments. A single bulletin can span several fragments. The public support script counts distinct bodies only when the lower bound from length and header-neutral CRC equals the upper bound from distinct full-record digests. We also checked these counts against the body bytes in the three original record ledgers. [Published label rows](../swb-transition/p2/fixture.csv) · [Record checksums](../swb-transition/p2/witnesses.json)

| P2 slot at 43288730 | Received mode and final octet (hex) | Predicted word bits 8–9 | Historical matches with the same mode and trailing-zero count | Historical matches with both octets identical |
| ---: | --- | --- | ---: | ---: |
| 17 | `61 6C` | `01` | 81/81 | 8/8 |
| 29 | `60 B6` | `00` | 132/133 | 6/6 |
| 53 | `60 3A` | `00` | 132/133 | No labelled frame |
| 57 | `61 4C` | `01` | 81/81 | 4/4 |

The two rows with 132/133 refer to the same 133 historical frames. Their exception was counter 43877110, slot 41. Like slots 29 and 53, it had mode `60` and one trailing zero, but the text-supported label was `10`. The historical frequencies leave all four target labels open. To reproduce the historical counts, run `python examples/nov28/airspy-150-gap/p2_support.py`. [Support script](p2_support.py) · [Disputed record and replay](../swb-transition/p2/43877110-source.json)

## Reproduce the result

The compact [isolated IQ file](isolated-iq48.flac) contains the losslessly stored 48 kHz stereo PCM input to Dream after conversion. It includes the zero flanks. A fresh replay of this file with the pinned receiver produced the exact 11,712-byte native stream from the isolated run. The [IQ and dump hashes](iq-replay.json) cover this distribution copy.

With the repository's offline Dream receiver built, run from the repository root. The projection command alone works from the supplied NPZ with Python and NumPy.

```sh
case_dir=examples/nov28/airspy-150-gap
out=work/airspy-150-gap-replay
python scripts/demod_iq_window.py "$case_dir/isolated-iq48.flac" "$out" --seconds 30 --reception-profile wiener --mlc-iterations 1
cmp "$out/msc.bin" "$case_dir/isolated-msc.bin"
python scripts/project_evs_group.py "$case_dir/target-data-units.npz" --counter 43288730 --evidence
```

The original receiver outputs from all three runs are also available for comparison. [Full interval](full-msc.bin) · [Gap zeroed](blanked-msc.bin) · [Four seconds isolated](isolated-msc.bin)
