# Packet IDs in five native receiver dumps

Of 4,652 aligned 182-byte wires, 2,473 passed the CRC on their header and all 179 data bytes. All 2,473 carried packet ID 0 and PPI 0. Every length-prefixed callback row contained 728 bytes. The CRC test ran before reading the header, including for the 12:28 Yokohama input where all 1,152 wires failed. A wire captured at both receivers counts once in each station's row below. [Full frequencies, transitions, file hashes and controls](packet-census.json)

| Capture and receiver | Rows | Wires checked | CRC passes | Header 80 | 01 | 02 | 43 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Nov 28 12:28 Yokohama, 3205 kHz | 288 | 1,152 | 0 | 0 | 0 | 0 | 0 |
| Nov 28 12:28 Edogawa, 6140 kHz | 293 | 1,172 | 769 | 189 | 185 | 196 | 199 |
| Nov 28 12:32 Yokohama, 6140 kHz | 220 | 880 | 859 | 209 | 212 | 219 | 219 |
| Nov 28 12:32 Edogawa, 6140 kHz | 218 | 872 | 464 | 107 | 114 | 124 | 119 |
| Nov 27 3205 kHz, selected 60 seconds | 144 | 576 | 381 | 87 | 96 | 95 | 103 |
| **Total** | **1,163** | **4,652** | **2,473** | **592** | **607** | **634** | **640** |

In wire order the header contains first and last flags, two packet-ID bits, one padding flag and three continuity bits. The standard calls for the continuity index to increment modulo eight for each packet ID. Here every immediately adjacent pair of CRC-good wires spanning a native row boundary showed 3→0 (550 pairs). This is an observation in receiver callback order. Missing radio frames can introduce gaps. Continuity was recorded after CRC acceptance. The simultaneous 12:32 receivers shared 457 distinct byte-identical 182-byte wires. [ETSI ES 201 980 V4.3.1 §6.6.1](https://www.etsi.org/deliver/etsi_es/201900_201999/201980/04.03.01_60/es_201980v040301p.pdf#page=83)

**Scope.** These files come from Dream's selected data-stream callback after MSC stream demultiplexing and before its packet assembly. A type-0 allocation with a single stream containing all 728 bytes and a matching current type-5 descriptor account for the full logical-frame payload under that configuration. Testing the equality directly for a multiplex with several streams would require capturing the native MSC decoder output before the demultiplexer, independently extracting every stream's part A and part B ranges, and comparing the outputs against that same frame. This packet inventory alone cannot exclude traffic in other streams or inside the application data. [Receiver dump hook](../../../patches/dream/DataDecoder.cpp) · [Signalling analysis](protocol.md)

A CRC can pass on erroneous data. For any future nonzero PID, retain the row and ordinal, header fields, padding count, transmitted CRC and full-wire digest. A matching complete wire on a second receiver, or recurring independently supported traffic consistent with the stream's service declarations, would give stronger evidence. Empty packets can use an unused ID when fewer than four substreams are used. PID 3 is reserved for FEC on a stream using the additional error protection signalled by SDC type 14. Even a genuine nonzero PID has several possible purposes. [ETSI ES 201 980 V4.3.1 §§6.4.3.15, 6.6.1.2, 6.6.5.2](https://www.etsi.org/deliver/etsi_es/201900_201999/201980/04.03.01_60/es_201980v040301p.pdf)

From this directory, run the following with Python and NumPy. The first command writes the public IQ replay's five native files to a new directory. The census verifies their SHA-256 values against the prespecified manifest, accepts the files in any order, and retains non-728-byte lengths in its denominator of input rows. The `--controls` command requires no receiver or recording. Its three synthetic rows include all four IDs, padded useful data, a valid empty packet and three malformed padding layouts with good CRCs. Flipping a single payload bit invalidates exactly one wire.

```sh
python replay.py /path/to/signalling-observer /tmp/service-replay
python packet_census.py /tmp/service-replay/*.msc.bin > /tmp/packet-census.json
cmp packet-census.json /tmp/packet-census.json
python packet_census.py --controls
```

## Continuity across independently identified consecutive data units

The 12:32 recordings allow a stronger check on the row-boundary observation. Each receiver separately supplied sequences of four consecutive native rows. Each of the sixteen wire CRCs and each of the four 716-byte DU CRCs had to pass. The DU phases had to be 0, 1, 2 and 0, with the final phase-zero counter one higher than the first. Selection used no packet ID, first/last flag, padding flag or continuity value.

Edogawa had 17 such counters and Yokohama had 64. They shared 17. All 272 full-wire comparisons agreed, covering 224 distinct packet coordinates because consecutive sequences can share their fourth and first rows. On each receiver, the nine internal transitions in the first three rows of each sequence gave 51 each of 0→1, 1→2 and 2→3. At the three row boundaries per sequence, all **51** transitions were 3→0 on PID 0. The same 51 boundaries were received at both sites. This places the observed restart between consecutively identified DUs, including the transition to the next counter. [All counters, native row indices, full-wire disagreements and four-row hashes](continuity.json)

```sh
python continuity.py --edogawa /tmp/service-replay/1232-edogawa.msc.bin \
  --yokohama /tmp/service-replay/1232-yokohama.msc.bin > /tmp/continuity.json
cmp continuity.json /tmp/continuity.json
```
