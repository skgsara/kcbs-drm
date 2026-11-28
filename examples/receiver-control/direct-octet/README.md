# Can two neighboring EVS words predict a withheld byte?

On a locally held-out two-minute 3205 kHz recording, the receiver predicted **one complete byte correctly in four attempts**. It abstained at 496 of 500 reserved slots. The comparison that used the mode's most frequent eligible training byte scored 0/4 on the same attempts. All three wrong guesses differed from the received byte by one bit. The four guesses came from three counters. These observations establish neither a reliable reconstruction rule nor a clear value for any masked byte. [Frozen rule](rule-protocol.md) · [Forecasts sealed before opening targets](https://github.com/skgsara/kcbs-drm/commit/fd93ae3) · [Per-position score](field/octet-score.json)

| Counter | Slot, position | Predicted p5 | Received p5 | Mode-only baseline |
| --- | --- | --- | --- | --- |
| 43872903 | 22, P3 | 1D | 19 | 0D |
| 43872934 | 13, P2 | 20 | 20 | 12 |
| 43872934 | 40, P1 | 28 | 2A | 9D |
| 43872962 | 16, P1 | 14 | 16 | 13 |

The target is zero-based octet 5 of the EVS payload, excluding the mode. It is transmitted in the clear. Each complete group has 20 reserved middle slots, five per position. The predictor sees three modes and the two outside slots' p5 bytes and guesses only if all three modes and both donor values agree. Twenty-five complete groups supplied 1,500 slots. Of 500 reserved centers, 75 passed the mode requirement and four also passed the donor requirement. There were no P4 predictions. Both the modes and the matching donor bytes were available to the predictor; the central target was available only to the scorer. Changing all 1,300 center targets on a separate 65-group recording, and re-creating its CRCs, preserved every feature and forecast. [Redaction control](redaction.json)

## What transferred from development

The target offset was selected after exploring all 21 directly readable payload offsets on two previously examined recordings. On the 1,102-group member recording the p5 rule scored 2,038/2,720 eligible targets. On a disjoint 81-group Edogawa recording it scored 35/77. Requiring an independently received target in two historical receiver pairs gave 47/77 and 30/43 exact, with 9 and 74 further forecasts lacking a peer label. These are development comparisons. Their selections and recordings can overlap. The prospective field result above is reported separately. [All inspected offsets](development.json) · [Independent receiver comparisons](peer.json)

## What happens when the whole packet is missing

Every reserved center shares its physical DRM packet with at least one of the two adjacent donor bytes. Losing that packet therefore removes an input to the primary rule. We tested a second rule using same-position donors four slots away. With the target packet withheld, only slot 28 (P1) could retain all five required inputs. On the prospective recording this gave 25 physically possible targets among 450 opportunities, and **zero forecasts**. In the historical 1,102-group test it had made 61 forecasts with 32 exact and 29 wrong. These controlled deletions assume a known group coordinate. On the historical paired recordings the additional check on naturally missing source packets also yielded zero forecasts with this rule. [Packet-deletion field score](field/packet-hole-score.json) · [Historical deletion control](packet-hole-dev.json) · [Naturally missing packets and donor geometry](gap_control.json)

## Four-position receiver result

The input was seconds [120,240) of the contributor's original 12 kHz I/Q recording, nominally November 27 at 12:17:02–12:19:02 UTC from its filename. The contributor had previously reported results for the longer recording. This interval was locally held out until the receiver and rules had been published. The single cold pass supplied 294 MSC rows. The original salvage assigned 537 packets; the previously frozen phase placement rule assigned 608, increasing full wire slots from 2,651 to 3,005. Both found 25 complete groups. All 70 extended counter IDs were absent from the 15,124-ID frozen local inventory. [IQ bounds](field/input.json) · [Receiver receipt](field/reception.json) · [Original row and group selections](field/group-seal.json)

The first pristine group, **43872873**, had 15 complete transmitted slots per position. Its 10,560 directly readable bits included 48 distinct bits supported by 12 matching codec checks. The clear values of the other 5,280 received bits remain unresolved. Ten conditional transition checks each selected one two-bit value at word bits 8–9, excluding the other three values for that slot under the codec assumption. For example, slot 4 admitted only `00` and slot 7 admitted only `01`. These are conditional predictions without independent clear labels in this comparison. No complete clear EVS word was supplied (0/60). The earliest incomplete control, **43872890**, improved from 20 to 56 complete transmitted slots. The report retains the observations, excluded alternatives and erasures for each slot in both arms. [Per-slot machine-readable evidence](field/group-fields.json.gz)

## Reproduction

Run from the repository root with Python and NumPy. The published MSC suffices to reproduce the comparisons. The input receipt gives the pinned executable and one-pass command for reproducing it from the IQ.

```sh
d=examples/receiver-control/direct-octet
f="$d/field"
a=examples/receiver-control/phase-anchors
w=$(mktemp -d)
python "$d/rule.py" train > "$w/model.json"
cmp "$w/model.json" "$d/model.json"
python "$d/redaction_control.py" --check "$d/redaction.json"
python "$d/rule.py" forecast "$f/native.msc.bin" > "$w/octet.json"
python "$d/rule.py" score "$f/native.msc.bin" "$w/octet.json" \
  fb22d03fdc70f433f1f1930d3035add52be8508f5603fa5556faae7a9f7f74ee > "$w/octet-score.json"
cmp "$w/octet-score.json" "$f/octet-score.json"
python "$d/packet_hole.py" predict --msc "$f/native.msc.bin" > "$w/hole.json"
python "$d/packet_hole.py" score --msc "$f/native.msc.bin" --predictions "$w/hole.json" \
  --sha256 3c7e28e14c64cbb08dca541c23373e5e68448c0e46704b91622be104fd9eb307 > "$w/hole-score.json"
cmp "$w/hole-score.json" "$f/packet-hole-score.json"
python "$a/phase_anchors.py" "$f/native.msc.bin" --out "$w/receiver" > "$w/placements.json"
python "$a/score_air.py" seal "$f/native.msc.bin" "$w/receiver" > "$w/group-seal.json"
python "$d/field_groups.py" "$w/receiver" "$w/group-seal.json" \
  83fdda471a9717e24613f51cee1691100b937cce6926fba56ea783283de18c6b > "$w/group-fields.json"
gzip -dc "$f/group-fields.json.gz" | cmp - "$w/group-fields.json"
```
