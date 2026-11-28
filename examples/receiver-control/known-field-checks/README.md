# How well do the 48 EVS bit predictions transfer?

At broadcast counter **43288750**, the receiver predicted 44 ones for the TCX previous-core bit and two `01` transition pairs. Together they cover 48 bit coordinates. The tests below check the same two rules on words whose original values are available. All 48 coordinates at the broadcast counter still lack clear labels. [Broadcast slots and assumptions](../sign-iq/field/even-fields.json.gz) · [Frozen calibration protocol](protocol.md)

| Known sender and reception condition | TCX predictions matching the sender | Always predicting one on the same slots | Restrictive transition sets containing the actual pair | Sets identifying the entire pair |
|---|---:|---:|---:|---:|
| Authored DRM IQ after stock packet reception | 252/252 | 244/252 | 39/39 | 3 |
| Official clean SWB DTX streams | 778/778 | 772/778 | 128/128 | 45 |
| Official f06 copies | 687/687 | 681/687 | 119/119 | 43 |
| Official b10 copies | 663/663 | 657/663 | 114/114 | 39 |

The authored transmission provides a check through actual RF modulation, demodulation, packet loss and a separately saved stock-encoder reference. Three of the 39 restrictive transition cases identified both bits, and another ten fixed one bit. At one slot, the previous frame was incomplete but its mode survived in a CRC-good packet. That mode supported the correct TCX prediction. Withholding the mode made the rule abstain. [Authored reception and replay](authored-fixture.md)

The three official conditions cover copies of the same 83.2 seconds of source audio. The six clean TCX zeroes that distinguish the rule from the constant-one baseline occupy the same six source slots in both impaired copies. A post-score check found that the clean transition rule selected `01` uniquely in 20 slots and matched all 20. The corresponding counts were 20 and 17 in the two impaired copies, all at slots already present in the clean control. Earlier broadcast labels disagree with the stock transition rule in some slots. These results support keeping the 48 predictions conditional. [Official vectors and scores](official-dtx.md) · [Previously reported on-air exceptions](../../nov28/swb-transition/README.md)

## Separate broadcast test on a directly carried field

The 11:58:16 UTC capture yielded 60 complete native groups, of which **43871935** was the first. All 89 assigned counters were absent from the frozen local inventory. The contributor had published an aggregate for this recording. The receiver observed 10,560 direct bits at the first group and reported **0/60 complete clear words**. Seven HQ flags could be predicted across physically consecutive group boundaries. Their observed values were all zero, so a fixed-zero prediction also matched 7/7. Shifting the predecessor back by one extra group matched three of four comparable flags. The field test and forecasts were sealed before reading the directly carried target bit for scoring. [Original radio sample, per-position results and replay](field-1158/field.md)
