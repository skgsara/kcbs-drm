# Can a unit body survive a damaged packet checksum?

Across four original receiver dumps, **128 rows had three correctly headed packets passing CRC and one packet failing CRC**. The enclosing data-unit CRC failed on every unchanged body. There were zero candidates for independent comparison. The 12:32 pair supplied 26 and 9 such rows, and the 21:26 pair supplied 27 and 66. [Input digests and counts](development.json)

The test concatenates the four 179-byte packet bodies in received order and checks the 716-byte unit, including its transmitted CRC. It changes no received bits. For a passing unit, it records the failed packet ordinal and whether its received header and FCS are consistent with damage to the header alone, the FCS alone or both. It compares candidates to an independent receiver only when a different, unique CRC-valid packet establishes the row pairing. The original packet remains CRC-failed. [Detector and controls](check.py)

On a synthetic unit, all 32 single header-bit changes and all 64 single FCS-bit changes preserved the sender's complete unit body. All 5,728 single-bit changes within the logical unit failed the unit CRC. Both checks use the same polynomial. A synthetic multibit error invisible to that polynomial, together with a damaged packet FCS, passed the unchanged-unit check despite disagreeing with the sender. Thus a compatible failure pattern can support a candidate. Exact source bytes, when available, provide the stronger check.

```sh
python examples/receiver-control/du-body/check.py > /tmp/du-body-development.json
cmp /tmp/du-body-development.json examples/receiver-control/du-body/development.json
```

## Whole groups on the authored IQ fixture

All **40 groups of 60 EVS words** matched the separately saved sender when the replay included 12 unchanged unit bodies with a one-bit packet checksum discrepancy. The groups came from three consecutive native rows carrying phases 0, 1 and 2, with the counter read from phase 0. Each row needed four canonical packet headers and a passing DU CRC. A conditional row also needed three packets passing their own CRC, with exactly one bit differing between the fourth packet's received and recomputed checksum. The ledger preserves each failed packet's ordinal, native row and both checksum values. [Results](authored.json) · [Replay](authored.py)

| Receiver or selection | Exact groups out of 40 | Exact words out of 2,400 |
|---|---:|---:|
| Strict native triples with all packet CRCs passing | 28 | 1,680 |
| Stock receiver, including words from partial groups | 28 | 2,113 |
| Native triples including the checksum-compatible rows | 40 | 2,400 |

The 12 additional complete counters span 16909068–16909079. Their 720 words include 433 that the stock receiver already supplied, so the increase over stock is **287 words**. The earlier phase-anchor study supplied 2,289 exact words by assigning additional CRC-valid packets. This control adds 111 words over that result. The fixture deliberately altered only stored checksums. The independent clear sender establishes exactness here. An undetected body error can also accompany a one-bit checksum discrepancy, as the synthetic counterexample above shows. [Damage schedule](../transmitter-receipt.json) · [Phase-anchor comparison](../phase-anchors/README.md) · [Sender provenance](../fixture/sender.json)

```sh
python examples/receiver-control/du-body/authored.py > /tmp/du-body-authored.json
cmp /tmp/du-body-authored.json examples/receiver-control/du-body/authored.json
```

The default input is the archived native MSC from the authored-IQ run. To check a fresh demodulation, pass `--native /path/to/demod/msc.bin`. The replay verifies its uncompressed SHA-256 before selecting groups. [Raw IQ receiver command](../README.md)
