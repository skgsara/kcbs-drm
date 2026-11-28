# Can a unit body survive a damaged packet checksum?

Across four original receiver dumps, **128 rows had three correctly headed packets passing CRC and one packet failing CRC**. The enclosing data-unit CRC failed on every unchanged body. There were zero candidates for independent comparison. The 12:32 pair supplied 26 and 9 such rows, and the 21:26 pair supplied 27 and 66. [Input digests and counts](development.json)

The test concatenates the four 179-byte packet bodies in received order and checks the 716-byte unit, including its transmitted CRC. It changes no received bits. For a passing unit, it records the failed packet ordinal and whether its received header and FCS are consistent with damage to the header alone, the FCS alone or both. It compares candidates to an independent receiver only when a different, unique CRC-valid packet establishes the row pairing. The original packet remains CRC-failed. [Detector and controls](check.py)

On a synthetic unit, all 32 single header-bit changes and all 64 single FCS-bit changes preserved the sender's complete unit body. All 5,728 single-bit changes within the logical unit failed the unit CRC. Both checks use the same polynomial. A synthetic multibit error invisible to that polynomial, together with a damaged packet FCS, passed the unchanged-unit check despite disagreeing with the sender. Thus a compatible failure pattern can support a candidate. Exact source bytes, when available, provide the stronger check.

```sh
python examples/receiver-control/du-body/check.py > /tmp/du-body-development.json
cmp /tmp/du-body-development.json examples/receiver-control/du-body/development.json
```
