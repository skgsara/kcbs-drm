# A received EVS mode can predict one bit of payload octet 0

The received mode `F9` predicted that the high bit of payload octet 0 would be zero. That bit agreed with **175 first-position words in the November 25–26 holdout and 17 second-position words in separate November 27 recordings** where the text evidence covered the corresponding byte in a record header or body. The other seven bits remain open. The predictor saw only the mode. [Frozen test protocol](protocol.md)

## Which values can this field reject?

At 13.2 kb/s in super-wideband low-rate HQ, the standard reference encoder writes class 00 (normal), 01 (transient) or 10 (harmonic). A switch from ACELP inserts one frame-length flag before the class, changing where its bits fall. The physical word begins with the mode octet, followed by the 32 payload octets. Bit numbers start at zero, most significant bit first.

| Received mode | Location of the class | Values still possible in payload octet 0 |
|---|---|---|
| `F9` | Bits 7 and 8. The mode sets bit 7 to one. | `00`–`7F` (128 values). Bit 8 must be zero. |
| `FA`, `FB` | Bits 8 and 9, both in the payload. | `00`–`BF` (192 values). Only the pair 11 is excluded. |
| `F8` | Bits 7 and 8. The mode sets bit 7 to zero. | All 256 values. Both values of bit 8 produce a class the encoder can emit. |

The class writer is in `lib_enc/hq_lr_enc.c` and the classifier in `lib_enc/hq_classifier_enc.c` of TS 26.443. This is a constraint on what the reference **sender emits**. A decoder can parse the unused code 11. The check makes no prediction for TCX20, ACELP or GSC words and none for payload offsets 15, 18, 21, 24, 27 or 30. [ETSI reference implementation](https://www.etsi.org/deliver/etsi_ts/126400_126499/126443/19.00.00_60/ts_126443v190000p0.zip)

## Test against previously published labels

Seven November 25–26 receiver dumps contain 67,960 first-position slots in complete CRC-valid data units. Of 371 conditional predictions, 264 had a first-position comparison supported by independently rechecked ordinary text CRCs. The checker recorded the predictions and their digest before opening the six label archives. Multiple words from one counter can share the same text evidence. The dumps begin after RF demodulation. Their source IQ is unavailable in the contribution.

| Received mode | P1 comparisons with ordinary-text support | Distinct counters | Observed high bits of payload octet 0 |
|---|---:|---:|---|
| `F9` | 188 | 92 | 11 words had 00 and 177 had 01 |
| `FA` | 76 | 69 | 75 words had 00 and one had 10 |
| `FB` | 0 | 0 | No absolute comparison |

The test covered 160 distinct counters across the two observed modes, with one counter in both rows. In the separate November 27 development recordings, 20 `F9` and 32 `FA` first-position words also agreed with the rule. These are comparisons to previously text-supported values. No second receiver supplied the original EVS words. [November 27 development coordinates](development-observations.csv)

The ordinary-record review accepts verified padding and fill as part of its structural check. A separate audit asked whether the label column used by each tested audio byte occurred in the received record **header or body** and could change its CRC. It did for 175 of the 188 `F9` words and 72 of the 76 `FA` words, covering 153 counters. Changing either of the two high bits in that column, or both together, broke at least one original record CRC for each of those 247 words. The remaining 17 comparisons had only padding/fill coverage for that column. [Column sensitivity and control results](column-crc-summary.json)

From this directory, replay the archive comparison against the files shipped with the repository. The summary includes each input digest and the counts of eligible but unscored words. [Archive results](archived-summary.json)

```sh
python archived.py predict /tmp/hq-predictions.json
python archived.py score /tmp/hq-predictions.json 455d5d07feddb747fe6bff4e522e07170505134a601476a265bfc8baede5802c /tmp/hq-archive-results.json --summary /tmp/hq-summary.json
python column_crc_audit.py /tmp/hq-archive-results.json /tmp/hq-coverage.json
```

An additional control used the unmodified EVS encoder on three synthetic signals. It produced 116 `F9` and 62 `FA` words in 5,100 total, all satisfying the restrictions. Run `python native.py --encoder /path/to/EVS_cod` to reproduce the input and stream digests. [Native control results](native-expected.json)

## Second-position comparisons

Two November 27 archives supplied previously established second-position prefix values and ordinary text records that covered the corresponding column in their header or body. All 17 `F9` words had bit 8 clear. All 32 `FA` words had high bits 00. The 49 eligible slots spanned 45 counters and 42 different records. The required packet bytes passed CRC in all 49 cases, including one slot received within an incomplete DU. No music matching was used. [Per-slot checks and record CRCs](p2-labels.csv)

In the group's 17:44 supplement, counter **43865272**, slot **53**, is a second-position `F9` example. Its previously supplied prefix gives bit 8 equal to zero. The corresponding label column occurs at byte 27 of the text record beginning at counter 43865271, phase 2. That record reproduces the transmitted CRC `61CA`. Counter 43865914 has 15 second-position TCX20 words, so this HQ rule makes no prediction there.

The 17:44 supplement had five eligible P2 modes and three comparable prefixes. The 13:17 recording had 109 eligible modes and 46 comparable prefixes. One eligible word each in the 17:56 and 13:58 recordings lacked a supported comparison, and 12:09 had no eligible modes. In a separate `6140you` check, both `FA` values were 00. Only one had matching text header/body coverage, so those two observations are reported separately.

From this directory, run `python check_supplement.py /path/to/kcbs2-3205-1744-1756-receiver-supplement-20261127.zip` to reproduce the three 17:44 cases from the group's handoff. The other 46 rows require the separate 13:17 archive for replay. [Supplement verifier](check_supplement.py)

## Applicability to IQ

The 22:27 UTC Edogawa recording was previously used to check an ACELP speech-class field. Its 52 complete groups supplied 39 conditional HQ cases. The original first complete counter, 43903388, had none. This recording provides no text-supported absolute score for the 39 cases. [All slot coordinates](edogawa-2227.json) · [Reception and checked data units](../acelp-class-history/README.md)

| Earlier Edogawa recording | P1 | P2 | P3 | P4 |
|---|---:|---:|---:|---:|
| `F9`, one conditional bit | 7 | 6 | 8 | 11 |
| `FA`, one excluded pair | 2 | 1 | 1 | 3 |

Run `python observe.py ../acelp-class-history/edogawa-data-units.npz` in this directory. The observation code CRC-checks each DU and uses only mode octets for its predictions. Its per-word output identifies the alternatives still permitted for each high-bit pair. The full-word decoder continues to record erasures.

To reproduce a single case from IQ, demodulate the previously published 16-second Edogawa excerpt using the commands in its receipt, then run `python observe.py /path/to/replay/du/data_units.npz --counter 43903395`. Both checked Dream builds produce mode `FA` at slot 43, position four. Its high two bits may be 00, 01 or 10. [IQ excerpt](../acelp-class-history/7l4iou-3205-43903388-iq12.wav) · [Replay commands](../acelp-class-history/iq-receipt.json)

Two separately preselected windows identified service `A00002` but yielded zero complete data units. In the archived final 120 seconds from JL1EDU, 277 of 297 FAC blocks passed CRC. In a new, uninterrupted 180-second 7L4IOU recording beginning at 22:41:07 UTC, 424 of 444 FAC blocks passed CRC. No MSC packet passed CRC in either window. Both have zero eligible words and no primary counter. This leaves the new live recording without an absolute score or a complete word. [IQ hashes and per-receiver results](reception.json)
