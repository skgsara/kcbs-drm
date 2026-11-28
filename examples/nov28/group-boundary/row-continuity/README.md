# Can a missing cycle move frames to the wrong counter?

At counter **43945659**, Edogawa and Yokohama received all 12 physical packets identically. Edogawa read the phase-zero counter at native row 20 and its successor at row 23. Yokohama read the same counters at rows 23 and 26. That places all 60 slots between the same two counter observations at both sites. [Two-receiver IQ and packet comparison](../../same-6140-1232/README.md) · [Per-phase comparison](paired-loss.json)

We removed exactly three consecutive native MSC rows from a copy of the Yokohama file. Each trial starts from the same original rows. We passed the surviving rows unchanged through the original group parser and compared each slot with its counterpart at Edogawa using the mode and 21 directly transmitted payload octets.

| Yokohama rows omitted (zero-based) | Next counter observed | Matching slots in phases 0 / 1 / 2 | Matching slots out of 60 |
|---|---:|---:|---:|
| None | 43945660 | 20 / 20 / 20 | 60 |
| 24–26, immediately after phase 0 | 43945661 | 20 / 0 / 0 | 20 |
| 25–27, immediately after phase 1 | 43945661 | 20 / 20 / 0 | 40 |
| 26–28, immediately after phase 2 | 43945661 | 20 / 20 / 20 | 60 |

All four trials presented the parser with phases 0, 1, 2, twelve valid packet CRCs, and three valid data-unit CRCs. The jump to 43945661 detects a break in the expected counter sequence in every edited trial. The same jump occurs with zero, 20 or 40 misplaced slots. The independent receipt distinguishes those three possibilities. These omissions were introduced after reception. [Control code](paired_loss.py)

## Checks on the archived receiver output

Among 622 intact three-row observations in the inventoried files, 548 had a directly readable phase-zero counter in the immediately following row. All 548 advanced by one modulo 2³². They cover **417 distinct starting counters** and 417 distinct sets of checked wire bytes. Twenty-six of those sets occur in two different radio recordings. Some other files contain the same reception processed in different ways. In 68 observations the next row lacked the required evidence, and six had reached the end of the file. An unavailable next counter leaves the single-receiver check open. [Input files and digests](inputs.json) · [Results](inventory.json)

At 11:58 UTC, primary counter **43871935** occupies rows 8–10 and the receiver reads 43871936 at row 11. Across that recording, 57 of 60 intact groups had the immediate successor observation. Two others reached the expected counter six callbacks later. Counter 43872031 ended the file. These checks assess slot coordinates. The receiver still supplied zero complete clear EVS words for the primary. [Published primary score](../../../receiver-control/known-field-checks/field-1158/field.md) · [Original MSC](../../../receiver-control/known-field-checks/field-1158/receiver/msc.bin)

Run from the repository root to check the inventory against its pinned inputs and reproduce the paired omission control.

```sh
d=examples/nov28/group-boundary/row-continuity
python "$d/inventory.py"
python "$d/paired_loss.py" > /tmp/kcbs-paired-loss.json
cmp "$d/paired-loss.json" /tmp/kcbs-paired-loss.json
```
