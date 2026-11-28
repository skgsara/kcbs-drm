# Two frequencies complete one damaged data unit

On June 16 at counter **32088106**, both 3205 kHz and 6140 kHz carried the same four-packet phase-zero data unit. Packet 1 passed its transmitted checksum only on 3205. Packet 2 passed only on 6140. Packets 0 and 3 passed on both and agreed byte for byte. Combining the checked packets produced a 716-byte unit whose transmitted CRC was `76CA`.

| Received phase-zero packet, numbered from zero | 3205 kHz | 6140 kHz |
|---|---|---|
| 0 | CRC passed | CRC passed |
| 1 | CRC passed | CRC failed |
| 2 | CRC failed | CRC passed |
| 3 | CRC passed | CRC passed |

The 6140 kHz excerpt also includes both following phases and the next phase-zero counter, 32088107. The three complete data units at 32088106 have transmitted CRCs `76CA`, `CDFE` and `ED04`. That accounts for all 60 transported EVS slots. No clear audio bits are inferred by this test.

## How much the second frequency added

The source files are Martyn's June 16 per-frequency MSC dumps. The receiver assigned 102 complete groups on both frequencies. The counts below use the full files and the same physical packet and data-unit checks throughout. [Original receiver data](https://github.com/martynw/KCBSDRM/tree/0b3e75fcb642d17d79c72f8f628cb4424273c06c/reference) · [Original collection notes](https://github.com/martynw/KCBSDRM/blob/0b3e75fcb642d17d79c72f8f628cb4424273c06c/CROSSTX_FINDINGS_2026-07-07.md)

| Source of the groups | Complete groups |
|---|---:|
| 3205 kHz alone | 360 |
| 6140 kHz alone | 154 |
| Union of groups already complete on either frequency | 412 |
| After combining complete data units | 414 |
| After combining received packets by counter, phase and position | 415 |

At 32087806, the 6140 kHz reception supplied phase 0, while 3205 supplied phases 1 and 2. At 32088021, 3205 supplied phase 0, 6140 supplied phase 1, and both had phase 2. The third gain, 32088106, required individual packets from both frequencies within phase 0. An earlier project note reported 408 and 410. It gave no input hashes or counter range, so its original denominator remains unverified.

All 1,711 packet coordinates available on both frequencies agreed over all 182 bytes, including their headers and transmitted CRCs. [Full-file totals and hashes](audit.json) · [Original row coordinates, packet checksums and recovered data-unit hashes](receipt.json)

In the November 27 06:17 dual-Airspy example, every complete unit in the combined output was already complete on at least one frequency. The June counter illustrates how complementary packet loss changes that result. [November recording and per-frequency totals](../../nov28/four-frequency/README.md)

## Replay from the received bytes

Each file below is a contiguous slice of its original length-prefixed MSC dump. The 3205 kHz file contains original row 1707. The 6140 kHz file contains rows 1616 through 1619 inclusive. Rows and packet positions are numbered from zero. [3205 kHz excerpt](june-3205.msc.bin) · [6140 kHz excerpt](june-6140.msc.bin)

From the repository root, use new output directories for these commands.

```sh
study=examples/jun16/transport
python scripts/salvage_msc_packets.py "$study/june-3205.msc.bin" --transport-only --out replay-3205
python scripts/salvage_msc_packets.py "$study/june-6140.msc.bin" --transport-only --out replay-6140
python scripts/salvage_msc_packets.py "$study/june-3205.msc.bin" "$study/june-6140.msc.bin" --transport-only --out replay-combined
python scripts/project_evs_group.py replay-combined/data_units.npz --counter 32088106
```

The excerpts individually yield zero complete groups. The combined run yields one. The complete groups in the table above require the full original dumps.

## Which EVS bytes were heard on both frequencies?

The receiver can retain the CRC-valid packets of an incomplete data unit and report which individual EVS word octets they cover. For counter 32088106, the five original MSC rows give the following counts. Each number counts distinct pairs of slot and directly transmitted word-octet index. The 6140 kHz boundary anchor belongs to the next counter.

| Reception or comparison | P1 | P2 | P3 | P4 | Total octets |
|---|---:|---:|---:|---:|---:|
| 3205 kHz excerpt | 85 | 88 | 82 | 66 | 321 |
| 6140 kHz excerpt | 309 | 292 | 292 | 308 | 1,201 |
| Available on both frequencies, identical | 64 | 50 | 44 | 44 | 202 |
| Available on at least one frequency | 330 | 330 | 330 | 330 | 1,320 |

Of the 10,560 directly carried bits, **1,616** could be compared across the two excerpts. The other 8,944 appeared on only one frequency in these files. At slot 10 (phase 0, cycle 2, P3), 3205 kHz supplied 16 of the 22 visible octets and 6140 supplied the other six. This is the only slot whose visible projection required both inputs. The 11 masked octets in each word have no clear-value comparison here. [Original packet receipts](receipt.json) · [Replay and per-position regression tests](../../../scripts/test_project_evs_group.py)

To inspect the first reception separately, run the following from the repository root with a new output directory.

```sh
study=examples/jun16/transport
python scripts/salvage_msc_packets.py "$study/june-3205.msc.bin" --transport-only --save-packets --out partial-3205
python scripts/project_evs_group.py --packets partial-3205/packets.npz --counter 32088106 --field-checks
```

In the packet report a hexadecimal byte comes from a flagged packet at a direct word position. `??` marks a received masked location and `--` marks a location without a received packet. A receipt of `received_packets` means that some or all of the word's locations were received in a phase lacking a complete data-unit check. It is possible to receive all 33 locations of one word inside an incomplete phase. `physically_complete_slots` counts such words, while `missing_du_slots` counts every slot in a phase without a complete data unit. A fully received word can still contain masked octets.
