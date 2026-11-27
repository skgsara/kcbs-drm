# EVS field checks on counter 43005013

Counter **43005013** had all 60 received word slots. The frozen receiver
predicted the HQ switch flag correctly in all 53 eligible slots, including
one transition from ACELP. The flag is transmitted in the clear. This
group contained no TCX20 words or eligible single-word fields. Its 5,280
masked bits remain unscored, with zero complete clear words at every
position. We selected the median complete counter from the published
transport inventory and pushed the receiver and selection rule to
`main` before opening its application fields.
[Frozen protocol](protocol.md) · [Per-position target results](target-result.json)

| Second look across all 109 complete groups in the recording | Result |
| --- | --- |
| Directly received HQ flag | 409/409 matched, including 8 predictions of 1 |
| Directly received SWB GSC INACTIVE pitch-band index | All 1,180 values were in the allowed range 0–10 |
| TCX20 first payload bit under the reference encoder model | 1,953 conditional predictions across 39 groups, seven zeros and 1,946 ones |

The full-recording count includes the selected group. TCX20 predictions
in this count have no independent on-air bit score. They are left as
unknowns in the output word. Neither GSC field check touches the masked
suffix at payload offsets 15, 18, 21, 24, 27 and 30.
[Counts for each complete counter](recording-coverage.csv)

## When the TCX20 prediction disagrees with the signal evidence

For TCX20 the stock encoder writes a bit about the preceding core at
word bit 8, the high bit of payload byte 0. In the November 27
`43865914` development group, all 15 second-position words followed
transform-coded words. All 15 text-supported prefix bytes had the
predicted bit value 1. The published November 27 06:17 stream also
yielded 248/248 matches in eligible first-position TCX20 words with
text-supported payloads, all predicting 1.

Two other November 27 groups show the limit of this interpretation.
At `43865386` one within-group prediction disagreed with the previously
exported text-supported first-position bit. At `43865918` all 14
eligible first-position predictions disagreed. In each case the
preceding mode was TCX20, the reference rule predicts 1, and the export
has 0. All three DUs were present at both counters. The text supporting
the two groups repeats the same 112-byte record with CRC `B81A`. The
cause is unresolved. These cases preclude treating the reference rule as
a verified masked bit on this service. The comparison file also lists
the two group-initial slots the receiver skips.
[Historical counterexamples and source digests](historical-disagreements.json)

The disputed first-payload MSB maps to text-body offsets 48, 64 and 80 in
the corresponding copy at each target. Flipping that shared bit in all
three places, while holding the rest of the observed record fixed,
changes its calculated CRC from `B81A` to `4691`. Four distinct
transmissions carried the same 112-byte decoded record. Only one record
intersects each target, so the repeated text strengthens the CRC check
without supplying an independent clear EVS word.

## Test against original encoder output

A fresh 2,400-word stock encoder run after the freeze supplied 1,012 HQ
flag and 190 TCX20 payload-bit predictions. All matched the original
word. The TCX20 cases included 3 zeros and 187 ones. Replacing each
tested target bit by its opposite gave zero matches. All 498 applicable
SWB GSC INACTIVE fields passed, and setting the four-bit index to 11
triggered rejection in every case. This input yielded no WB GSC AUDIO
or non-switching SWB HQ harmonic-class cases with mode 0xF9.
[Encoder results and source digests](encoder-control.json)

The field definitions follow the floating-point EVS reference encoder
and decoder, particularly `enc_prm.c` for TCX20 history,
`decision_matrix_enc.c` for HQ switching, `hq_lr_enc.c` for the SWB HQ
class, and `gs_dec.c` for the two GSC fields.
[3GPP TS 26.443 reference software from ETSI](https://www.etsi.org/deliver/etsi_ts/126400_126499/126443/19.00.00_60/ts_126443v190000p0.zip)

## Reproduce the results

The included archive contains the three CRC-checked DUs selected from
a fresh demodulation of the original IQ. Its full MSC output matched
the SHA-256 from the original transport inventory. From the repository
root, replay the selected group and the encoder control as follows.

```sh
case_dir=examples/nov15/validation/field-check-43005013
python scripts/project_evs_group.py "$case_dir/data_units.npz" --counter 43005013 --field-checks > projection-with-fields.json
sha256sum projection-with-fields.json
python examples/nov27/validation/check_core_history_control.py --intra-word
```

Compare the projection digest with `projection_with_fields_sha256` in
the target results. Each original partial word retains its unknown-byte
markers. The two extra JSON sections identify the predicted bit, any
available comparison value, the allowed field values, and abstentions.
