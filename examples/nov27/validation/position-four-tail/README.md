# Is payload octet 30 clear in position four?

In two days of broadcasts, the received fourth-position octet behaved like the corresponding clear first-position octet when several nearby codec fields matched. The effect depended strongly on codec mode. This tests a proposed exception to the KCBS-2 payload layout. An individual fourth-position clear value remains unverified by this comparison.

## Comparison across November 25 and 26

For each target slot, find a first-position word received on the other date with exactly the same mode and payload octets 28, 29 and 31. If multiple words qualify, select one by a fixed hash of the target coordinates. Compare octet 30 only after this selection. The first-position comparison byte has a previously published mask column supported inside a CRC-checked text record's header or body. The fourth-position target is the original received octet. A control moves the target octet between words of the same date, position and mode. Multiple matches can come from the same counter, programme or comparison word. [Archive verification script](archive_control.py) · [Counts, input hashes and resampling by counter block](archive-summary.json)

| Target | Exact matches to the other date's supported first-position byte |
|---|---:|
| Position 1, previously text-supported value | 307 / 1,189 |
| Position 1, received value | 8 / 1,189 |
| Position 2, received value | 5 / 1,761 |
| Position 3, received value | 11 / 1,700 |
| Position 4, received value | **438 / 1,665** |
| Position 4, shifted control | 58 / 1,665 |

Of the 438 fourth-position matches, **402** came from mode `76` (SWB GSC INACTIVE). Requiring equality of all 22 directly received word octets produced zero cross-date comparisons for position four. The three-neighbour match measures a tendency across frames. It cannot certify equality of the underlying full words.

## Two valid values with identical codec history

Two 13.2 kb/s stock EVS encodes produced identical complete words for their first 67 slots. At slot 67, position four, they differed only at word bits 253 and 255. Payload octet 30 was `1B` in one encode and `1E` in the other. Thus even knowing the entire previous encoded stream and every other bit of this TCX20 word would leave those alternatives open. Run the following command from the repository root with the stock floating-point EVS encoder. [Original words and stream hashes](native-pair.json)

```sh
python examples/nov27/validation/check_native_word_pair.py --case tcx-p4-history --encoder /path/to/EVS_cod
```

## Training a forecast from IQ alone

For a separate prospective test we trained on the received fourth-position octet in three March IQ WAVs and the November 27 22:58 UTC IQ recording. The four files supplied 899 complete groups. Six duplicate groups in the two overlapping March windows counted once. A full replay from each IQ input reproduced all five demodulator outputs and the pooled group and data-unit archives byte for byte. The test used two fixed rules. The primary rule required a match on the mode and three neighbouring bytes. The secondary rule required a match on the mode and final payload byte. [Frozen protocol](protocol.md) · [Four source recordings and hashes](training-receipt.json) · [Predictor and scorer](received_tail.py)

Use a fresh output directory and the repository's patched offline Dream. The following commands run from the repository root. [Receiver build](../../../../build/README.md)

```sh
study=examples/nov27/validation/position-four-tail
work=replay-p4
for wav in recordings/*.wav; do
    name=$(basename "$wav" .wav)
    python scripts/demod_iq_window.py "$wav" "$work/train/$name" --seconds 600 --reception-profile wiener --mlc-iterations 1
    case "$wav" in
      *19_53_42Z*) python scripts/demod_iq_window.py "$wav" "$work/train/$name-end" --start 590 --seconds 600 --reception-profile wiener --mlc-iterations 1 ;;
    esac
done
python scripts/demod_iq_window.py examples/nov27/validation/rf-iterations/7l4iou-6140-20261127T2258Z-iq48.flac "$work/train/nov27" --seconds 180 --reception-profile wiener --mlc-iterations 1
python scripts/salvage_msc_packets.py "$work"/train/*/msc.bin --transport-only --out "$work/training-du"
for context in full last; do
    python "$study/received_tail.py" train "$work/table-$context.json" "$work/training-du/data_units.npz" --context "$context"
done
```

To reproduce the November 25–26 comparison separately, run `python examples/nov27/validation/position-four-tail/archive_control.py`.

In a development check, we left out the entire 22:58 recording and trained on March alone. Of 525 fourth-position slots, the primary model predicted ten received octets and got one right. The secondary model attempted 487 and got nine right, versus five for mode alone on those slots. Neither result justifies promoting the guesses to clear bytes in the receiver.
