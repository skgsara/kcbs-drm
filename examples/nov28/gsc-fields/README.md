# Three EVS fields that can be checked against broadcast IQ

On November 28 at 00:28 UTC, three minutes of 6140 kHz IQ from 7L4IOU in Edogawa, Tokyo, yielded **115 CRC-valid data units and 32 complete groups**. All 54 assigned counter IDs were absent from the earlier inventory. Counter **43909460** was the earliest complete group in both physical and numerical order. Its 60 transmitted slots all had mode `F8` (super-wideband HQ). The receiver returned **zero complete clear EVS words**. Each position supplied 2,640 directly transmitted bits and left 1,320 unresolved. Within the group, 59/59 directly received HQ history flags agreed with the adjacent mode. [Frozen protocol](protocol.md) · [Whole reception](receipt.json) · [Lossless IQ](7l4iou-6140-20261128T0028Z-iq48.flac)

## Blind field results

The normal group projector now reports these checks with `--field-checks`. Each applicable field records its half-open word bit interval, prediction, and observed value or erasure. One word can supply two distinct checks. Any disagreement remains visible together with the received value. The counts below use complete groups and include all four positions.

| Check | Earlier 23:44 development sample | New 00:28 recording |
|---|---:|---:|
| Ordinary SWB GSC AUDIO noisy-speech bit (b40) | 274/274 | 0 eligible |
| SWB GSC INACTIVE/BWE empirical four-bit value (b40–43) | 0 eligible | 8/8 |
| Noisy AUDIO/TBE with valid positive pitch, padding b223 = 0 | 274/274 | 0 eligible |

All eight predictions of `1100` came from **counter 43909511**, slots 32–39, in one CRC-valid data unit. Each position contributed two observations. The padding check has no accuracy estimate on this recording. In the development recording, the 274 eligible words were the same for the noisy-speech and padding checks. [Blind scores](field-result.json) · [Eight observed nibbles and packet coordinates](inactive-witnesses.json) · [Development scores](development-2344.json)

The padding target is the low bit of directly carried payload byte **26**. In this particular stock-encoder branch the pulse-vector block has 51 bits. Arithmetic renormalization uses 32 bits, nine bits are written from the other end, and termination uses eight or nine. The remaining one or two bits are zero. The last is always word bit 223. In 2,000 stock-serializer trials the adjacent bit 222 was one in 1,011 cases. In a whole-waveform control, flipping only b223 in 5,287 eligible synthetic words changed no PCM sample or decoder error flag. Stock serialization detected every change. [Width calculation and stock reproducer](padding/README.md) · [Paired waveform results](sender-flips.json)

The primary group raised a different question. For an uninterrupted `F8` run with unchanged extension and no reset, the stock HQ encoder signals a transient on detecting an attack and for one further word. The class bits for three successive words therefore exclude `010`. Across 12,563 triples from unprotected stock encodes, every other triple occurred. Within 58 runs of at least 60 consecutive `F8` words, all four combinations of the class bit (b8) and energy selector (b9) occurred. This temporal rule leaves both possibilities open at every individual b8 of the received primary. [Sender counts](f8-sender.json) · [Native writer checks](f8-native.json)

## Is there a second standard audio stream?

The separate 00:02 development capture gives an independent check at the DRM service layer. All 446 CRC-valid FAC blocks advertised service `A00002` with zero standard audio services and one data service. All 145 CRC-valid SDC blocks assigned the multiplex to stream 0. All 1,444 valid standard packet headers carried packet ID 0. For this recording, standard DRM signalling identifies the custom data service as the place to look for EVS. [Service descriptors, accepted packets and source hashes](service-info-0002.json) · [00:02 recording](../../nov27/validation/swb-gsc/README.md)

## Replay

Use a fresh output directory and a finite-input Dream binary. The FLAC decodes to all 8,640,000 original IQ sample pairs. The recorder noted one timestamp interval 27.492 microseconds away from nominal. A second Dream build reproduced the original MSC, data units, complete groups, field scores and both primary projections byte for byte. [Replay receipt](replay-receipt.json)

```sh
case_dir=examples/nov28/gsc-fields
sh "$case_dir/replay.sh" "$case_dir/7l4iou-6140-20261128T0028Z-iq48.flac" /path/to/dream /tmp/kcbs-nov28-0028
cmp /tmp/kcbs-nov28-0028/transport/data_units.npz "$case_dir/data_units.npz"
cmp /tmp/kcbs-nov28-0028/field-result.json "$case_dir/field-result.json"
python scripts/project_evs_group.py "$case_dir/data_units.npz" --counter 43909511 --field-checks
```
