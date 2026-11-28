# Two-site reception before DRM error correction

Combining the Edogawa and Yokohama observations before channel decoding recovered two packets that both individual receivers lost. Each packet completed a 716-byte data unit that passed its own transmitted CRC. One of those units supplied the missing middle phase of counter **43945691**. The test used the published November 28, 12:32 UTC recordings of 6140 kHz. The selection and combining rule were fixed before inspecting the combined output. The recordings and several of their counters were already known. [Development protocol](protocol.md) · [Original IQ and native reception](../README.md) · [Two recovered wire records](fusion/recovered.msc.bin)

| Evaluation on 73 directly aligned row pairs | Pool the two individual decodes | Combine before error correction |
|---|---:|---:|
| Packets with correct header and CRC | 290 / 292 | 292 / 292 |
| Data units with four accepted packets and a valid unit CRC | 71 / 73 | 73 / 73 |

The individual decoders agreed wherever both returned a valid packet. The combined output reproduced all 290 previously accepted packets byte for byte. In the 73 evaluation pairs, shifting the Yokohama observation by one cell or one block in either direction gave zero accepted packets. In the separate calibration set, each whole-block shift produced one CRC-valid data unit at the wrong row. This demonstrates why locating the transmission needs independent evidence even when the CRC passes. [Results and timing controls](fusion/metrics.json)

| Native row, Edogawa / Yokohama | Newly received packet | Transmitted packet CRC / DU CRC | What establishes its location |
|---|---|---|---|
| 106 / 109 | Packet 0 | `3AEF` / `4DE3` | The received tag says phase 2. The default parser leaves the counter open. |
| 117 / 120 | Packet 0 | `EE87` / `085A` | The received tag says phase 1. Yokohama's intact adjacent rows and the next phase-zero counter place it at **43945691/1**. |

The three phases of 43945691 now supply 60 transmitted frame slots. This result adds zero independently verified clear EVS words. Its CRCs cover the bytes carried in the broadcast. [Original and recovered packet checks](fusion/proof.json) · [Counter and phase checks](coordinates/README.md)

## Reproduction

1. Rebuild the row map from the published native MSC files. A row qualifies only if a unique, identical, CRC-valid packet at the same ordinal occurs at both sites. The recovered packets occupy a different ordinal from these alignment witnesses. The map includes 135 witnessed pairs in total. The 73 evaluation pairs are a selected subset of the recording. [Alignment checker](alignment/README.md)
2. Replay the two lossless IQ files to save the equalized complex cells and their reliability values before Dream decodes them. Replaying either site's observations alone reproduces its original hard decisions in all 218 Edogawa and 220 Yokohama rows. [Observer patch and replay](observer/README.md)
3. Combine the paired cells using the recorded channel magnitudes and each block's signal-to-noise estimate, then use Dream's 16-QAM decoder. The compact verification also runs directly against the published wire bytes. [Combiner and verification](fusion/README.md)
