# Coordinates of the two combined data units

Run the verifier from the repository root with Python and NumPy. It reads the original station dumps, checks the published packet alignment and combined wire rows, and runs the ordinary transport parser on temporary copies of each station's chronology. Only the two specified rows change in those copies.

```sh
python examples/nov28/same-6140-1232/diversity/coordinates/verify.py
```

| Combined row, Edogawa / Yokohama (zero-based) | Received phase | Transmitted DU CRC | Result |
|---|---:|---|---|
| 106 / 109 | 2 | `4DE3` | Default parser leaves the counter unassigned at both stations. A separate check places this phase between consecutive phase-zero anchors 43945687 and 43945688. |
| 117 / 120 | 1 | `085A` | The default parser completes group **43945691** in Yokohama. Its intact original rows 119, 121 and 122 supply phase 0, phase 2 and the following counter's phase 0. |

In the first case, Yokohama supplied the phase and counter packets of the left anchor, and Edogawa supplied both packets of the right anchor. Original CRC-valid packets match across stations at both endpoints. The anchors are three native rows apart in each dump and the combined target has an explicit phase-2 tag in the second interior row. The first interior row has no valid phase tag at either station. The anchor check leaves that row unassigned.

This retrospective replay increases Yokohama's complete-group count from 65 to 66. Edogawa's count stays at 17. The original capture receipts retain their counts. The verifier's JSON output including the final line feed has SHA-256 `815271403aeab20833bfe129b1689633d8d54bf170e290e7df1e696431827f1a`. [Original row alignment](../alignment/row-pairs.json) · [Combined wire checks](../fusion/proof.json)
