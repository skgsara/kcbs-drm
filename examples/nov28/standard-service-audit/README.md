# What the five IQ recordings declare about KCBS-2

On November 28 at 12:28 UTC, Yokohama received 35 valid Service Description Channel (SDC) blocks from 3205 kHz while every one of its 1,152 payload packets failed CRC. Edogawa independently received the same service and packet-stream description from 6140 kHz during the overlapping two minutes. The controls allow us to identify the service even on a recording from which the receiver recovered no checked payload. [Frozen IQ inputs and receiver settings](protocol.md) · [Complete control-channel results](receipt.json)

| IQ recording | Seconds | Fast Access Channel blocks passing CRC | SDC blocks passing CRC | Physical packets passing CRC | Time advertised in the UTC field |
| --- | ---: | ---: | ---: | ---: | --- |
| Nov 28, 12:28 UTC, Yokohama 3205 kHz | 120 | 295/298 | 35/100 | 0/1,152 | 21:28 |
| Nov 28, 12:28 UTC, Edogawa 6140 kHz | 120 | 292/296 | 86/100 | 769/1,172 | 21:27 |
| Nov 28, 12:32 UTC, Yokohama 6140 kHz | 90 | 222/222 | 74/76 | 859/880 | 21:32 |
| Nov 28, 12:32 UTC, Edogawa 6140 kHz | 90 | 219/221 | 64/76 | 464/872 | 21:32 |
| Nov 27, nominal 12:21 UTC, 3205 kHz | 60 | 146/146 | 48/51 | 381/576 | 21:20 |

Every one of the 1,174 passing FAC blocks declared service `A00002`, short ID 0, with one data service, zero standard audio services, both conditional-access flags clear, and a zero reconfiguration index. All 307 passing SDC blocks associated the current stream 0 allocation (0 bytes in part A, 728 bytes in part B) with the same packet-mode application, packet ID 0, 179 data bytes per packet and the service label 조선중앙제2라지오방송. None contained a type-9 audio descriptor. These declarations account for the complete logical-frame payload in the sampled configuration. They describe the DRM transport. The clear values of masked EVS payload bits inside the application remain unresolved. [Raw FAC and SDC comparisons between sites](block-comparison.json) · [ETSI ES 201 980 V4.3.1, §§6.3–6.4](https://www.etsi.org/deliver/etsi_es/201900_201999/201980/04.03.01_60/es_201980v040301p.pdf)

## Packet boundaries

Counting all 4,652 physical packet observations before any header filter gave 2,473 CRC passes. Every passing packet used ID 0 with padding disabled. On the original one-iteration 12:32 replays, a separate probe before stream demultiplexing had already shown that the first 728 bytes of all 438 physical decoder output blocks exactly matched their corresponding service rows. Two residual bits per block followed those bytes. [Packet inventory and synthetic controls](packets.md) · [Earlier measurement before demultiplexing](../same-6140-1232/diversity/observer/README.md)

Both 12:32 receivers independently read 17 groups that included the first data unit of the next counter. Selection used packet and data-unit CRCs, phase order and consecutive counters. All 272 packet comparisons between sites agreed, covering 224 distinct packet coordinates because some four-row windows overlap. At all 51 data-unit boundaries in those groups, the three-bit continuity index went from 3 to 0. Within units it incremented at all 153 checked transitions. The DRM standard specifies an increment modulo eight per packet ID. Dream checks that increment and then resets the assembly state when the first-packet flag is set. This boundary behavior therefore allows Dream to assemble the next complete unit. [Counter and row witnesses](continuity.json) · [Dream packet assembly](https://github.com/mmjee/dream-patched/blob/895658c567d2fd47d6006065e75abf0c3157783f/src/datadecoding/DataDecoder.cpp) · [ETSI ES 201 980 V4.3.1, §6.6.1](https://www.etsi.org/deliver/etsi_es/201900_201999/201980/04.03.01_60/es_201980v040301p.pdf#page=83)

## Which clock to use for alignment

Each recording contained one CRC-valid time announcement. During the 12:32–12:34 UTC reception, both receivers obtained the same complete SDC codeword carrying type-8 entity `06877de560`. It specifies November 28 at 21:32 in the field the standard defines as UTC, with no optional local-time offset. Its time is about nine hours ahead of the receiving stations' timestamps. For aligning these recordings to an external programme, use station IQ timestamps and matching packet counters. The 12:28 receivers read their announcements at different points in their files. The November 27 recording has only a filename-derived start time. None of these callback logs locates an announcement to an exact RF sample. [Paired 12:32 recordings and timestamp files](../same-6140-1232/README.md) · [ETSI definition of type 8, §6.4.3.9](https://www.etsi.org/deliver/etsi_es/201900_201999/201980/04.03.01_60/es_201980v040301p.pdf#page=65)

## Reproduction

The service-level analysis is retrospective. Input selection was published before opening these five signalling traces. All five replays reached EOF and reproduced their prior native MSC digests. Repeating the five runs with a second local executable (SHA-256 `e3c953c12524d5102daabf2c70df8efa87c9c1fa06263f7a2cf24779afae0678`) reproduced every signalling and MSC file and all three derived JSON results byte for byte. The replay receipt records the executable's own digest. From this directory, provide the finite-input Dream executable with the signalling observer patch and an unused output directory. [Input, tool and output hashes](protocol.json) · [Observer build instructions](../yokohama-1300/README.md)

```sh
python replay.py /path/to/signalling-observer /tmp/kcbs-five-replays
python compare_blocks.py > /tmp/kcbs-codewords.json
cmp block-comparison.json /tmp/kcbs-codewords.json
python packet_census.py /tmp/kcbs-five-replays/*.msc.bin > /tmp/kcbs-packets.json
cmp packet-census.json /tmp/kcbs-packets.json
python continuity.py --edogawa /tmp/kcbs-five-replays/1232-edogawa.msc.bin \
  --yokohama /tmp/kcbs-five-replays/1232-yokohama.msc.bin > /tmp/kcbs-continuity.json
cmp continuity.json /tmp/kcbs-continuity.json
```
