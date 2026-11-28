# SWB GSC attack bit in archived first-position words

Two November 25 first-position words have attack bit 1 under the established 13.2 kb/s SWB INACTIVE GSC interpretation. They occur at counter **43679845, slot 4** and **43679859, slot 44**. Both have mode octet `76`. These observations rule out a constant-zero attack bit for this labelled archive.

| Corpus | Eligible P1 words | Counters represented | Attack 0 | Attack 1 | Following four bits = 1100 |
|---|---:|---:|---:|---:|---:|
| March 16 fixed idle text | 2,945 | 240 | 2,945 | 0 | 2,945 |
| November 25–26 ordinary text | 3,771 | 737 | 3,769 | 2 | 3,771 |

From this directory, Python 3.10+ and NumPy suffice to reproduce the counts from the public checkout.

```sh
python check_attack.py > /tmp/gsc-attack.json
diff -u expected.json /tmp/gsc-attack.json
```

**Field assumptions.** Bit 0 is the mode octet's most significant bit. Each counter has three DU phases and five four-word cycles per phase. This check uses P1 in each cycle. Its mode must signal index 14 (SWB INACTIVE) with the BWE selector set. Under ordinary EVS Primary 13.2 kb/s Mode 1, b39 is the low bit of zero-based payload octet 3, which uses the contributor’s verified text column 1. The high nibble of payload octet 4 directly supplies b40–43. Its observed value `1100` encodes noise index 6 and the two-subframe selector. The stock encoder sets the attack bit before the final coder-type decision. A retained music classification can affect attack detection before a later frame classification changes. See `lib_enc/pre_proc.c`, `lib_enc/speech_music_classif.c`, `lib_enc/gs_enc.c` and `lib_dec/gs_dec.c` in the reference codec. [3GPP TS 26.443](https://www.3gpp.org/dynareport/26443.htm)

**Label assumptions.** March uses the 702 contributed CRC-good groups that reproduce the fixed idle message and checksum. For November, each retained counter has all eleven established P1 columns in the CRC-covered header or body of one ordinary record. Its header, body and transmitted checksum recur at a different physical start. To reproduce the original 2,153-counter cohort, the script also requires a rank-16 CRC response to changes in text columns 8 and 9, holding the other columns fixed, with neither column in the transmitted checksum at that counter. This calculation uses text positions only. The word check reads the mode and payload octets 3 and 4. [Public capture and label descriptions](../../../../../contrib/kcbsdrm/README.md)

For the two attack-1 observations, column 1 occurs at protected record offsets 33, 49 and 65. The transmitted checksums are `73E3` and `91F4`, respectively. With the other labels fixed, each checksum detects every nonzero single-column change. The evidence file lists the transmitted-slot coordinates, text record digests and both copies' locations. The inference from text column to EVS bit depends on the established P1 mapping. [Expected output](expected.json)
