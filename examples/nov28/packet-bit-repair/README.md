# A held-out prediction for one complete EVS byte

On a locally held-out minute of 3205 kHz IQ, the frozen rule predicted **11 of 30 eligible bytes exactly**. All 30 had the predicted high nibble `C`. The low nibble took nine distinct values. A receiver can use the high-nibble evidence in this mode and keep the complete byte unresolved. [Prespecified receiver and input](protocol.md) · [Forecasts sealed before scoring](https://github.com/skgsara/kcbs-drm/commit/28792ee) · [Every forecast and observed byte](field/byte-score.json)

The rule used only the current mode octet. On mode `74` (super-wideband GSC INACTIVE with bandwidth extension), it predicted `C1` for the fifth payload byte, zero-based offset 4, excluding the mode byte. On other modes it abstained. This byte is carried directly, which lets us check the full target against its original physical packet after the predictions are sealed. In a separate 6140 kHz development recording `C1` had been the most common value, with 20 matches among 44 eligible slots. The fixed comparison predicted `C0`. Under the previously verified ordinary encoder branch, the high-nibble check admits `C0` through `CF` and excludes the other 240 byte values. Picking `C1` from those 16 is an empirical guess. [Development histogram](development.json) · [Previously verified encoder high-nibble field](../clear-evs-controls/stock-inactive/README.md)

| Position in cycle | Eligible slots | Exact `C1` | Wrong `C1` |
| --- | ---: | ---: | ---: |
| 1 | 8 | 2 | 6 |
| 2 | 9 | 4 | 5 |
| 3 | 8 | 2 | 6 |
| 4 | 5 | 3 | 2 |
| **Total** | **30** | **11** | **19** |

Ten complete groups supplied 600 slots. The rule abstained on 570. The 30 eligible slots belonged to seven counters and 14 of them belonged to one counter, so these slots do not represent 30 independent programme samples. The baseline matched 7/30 whole bytes. Both predictions matched 211/240 individual bits, including all 120 high-nibble bits. Even choosing the single most frequent eligible byte after observing this field interval would give only 11/30. Counter `43873132` illustrates the limitation within a single group: its eligible slots 24, 25, 26, 31 and 32 carried `C2 C1 C1 C4 C4`. The rule establishes no clear value at any masked octet. [Counter and slot evidence](field/byte-score.json)

The first complete native group was `43873129`, starting at MSC row 26. None of its 60 slots had mode `74`. Its ordinary IQ-only field score records **10,560 directly carried bits, 5,280 carried bits with unknown clear values and zero complete clear words**. All 24 assigned counters were absent from the 15,050-ID local comparison inventory. The contributor had reported aggregate reception from the longer source file. There is no external station or clear-word export for this minute. The first partial control was `43873125`, with 1,432 bits missing at the transport layer. [Full primary score](field/primary-score.json) · [Partial control](field/partial.json) · [Archive and historical overlap](field/group-evaluation.json)

In the separate 21:26 UTC two-station recording, the Yokohama receiver got 11 complete groups and the Edogawa receiver got 64. They shared seven complete counters. None of Yokohama's 660 slots had mode `74`. The independent-station comparison therefore supplies zero eligible complete-byte observations. [Sealed forecast and peer comparison](peer-2126/peer-bytes.json)

## What the two CRCs can establish

The diagnostic tried a single-bit change in rows with exactly one failed packet CRC. It restored the exact original sender bytes in all 5,824 synthetic single-bit tests. A three-bit payload error could also produce a unique proposed correction that passed both CRCs and left **four wrong bits**. Both checks use the same polynomial. For changes within one packet's data, moving that error pattern into the enclosing unit preserves polynomial divisibility. Passing both CRCs cannot independently confirm this type of change. [Paired synthetic cases](controls.json)

On the 12:32 development recording, the two proposed wires both disagreed with the independently received wires at Yokohama. The changes increased their distances from 9 to 10 bits and from 5 to 6 bits. At 21:26 the diagnostic made one proposal. Two unchanged packets identified the peer row, but the corresponding peer packet failed CRC. In the held-out minute there was also one proposal, at row 70. It yielded zero additional assigned packets or complete groups. The published primary uses the original receiver output for all three studies. [12:32 independent comparison](dev-peer.json) · [21:26 comparison](peer-2126/peer.json) · [Held-out transport comparison](field/group-evaluation.json)

## Replay

The input is a lossless copy of IQ seconds [420,480) from the November 27 contributor WAV. Its source clock is filename-derived. The demodulator and output checks are given in the reception receipt. With the pinned Dream executable in `KCBS_DREAM`, run these commands from the repository root, using fresh output paths. The three final comparisons require the published MSC files and Python dependencies only. The counter and group scores can also be rerun with `score_field.py` on the native and proposed MSC. [IQ source and hashes](field-input.json) · [Receiver command and native hash](field/reception.json)

```sh
audit=examples/nov28/packet-bit-repair
python scripts/demod_iq_window.py "$audit/field-3205-iq12.flac" /tmp/kcbs-byte-rf \
  --start 0 --seconds 60 --reception-profile wiener --mlc-iterations 1
cmp /tmp/kcbs-byte-rf/msc.bin "$audit/field/native.msc.bin"
python "$audit/byte_rule.py" train > /tmp/kcbs-byte-fit.json
cmp /tmp/kcbs-byte-fit.json "$audit/development.json"
python "$audit/byte_rule.py" predict "$audit/field/native.msc.bin" > /tmp/kcbs-byte-predictions.json
cmp /tmp/kcbs-byte-predictions.json "$audit/field/byte-forecasts.json"
python "$audit/byte_rule.py" score "$audit/field/native.msc.bin" /tmp/kcbs-byte-predictions.json \
  --seal 65d6a6e00d13bc0f499e2477442cb1162438595ed5db4a692f816437eac38e0d > /tmp/kcbs-byte-score.json
cmp /tmp/kcbs-byte-score.json "$audit/field/byte-score.json"
```
