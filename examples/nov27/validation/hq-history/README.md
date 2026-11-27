# Two previous-band pulse flags in EVS HQ

At 13.2 kb/s, a nontransient narrowband or wideband low-rate HQ word sends two bits about the most recent narrowband or wideband HQ word. The first bit is one if the previous **second-highest** coded band contained any quantized pulses. The second bit says the same for the **highest** band. A transient NB/WB HQ word updates this memory. Super-wideband HQ neither reads nor updates it.

| Reference encoder control | HQ words | History reports | Reports referring to the immediately preceding 20 ms word |
|---|---:|---:|---:|
| Wideband | 1,101 | 978 | 938 |
| Super-wideband | 1,136 | 0 | 0 |

The native encoder and decoder agreed on the exact two band pulse counts in every HQ word. In the wideband control, all 978 reports agreed with the previous eligible pulse counts. Forty reports spanned intervening words. The transmitted pairs were 00 in 16 reports, 10 in 163 and 11 in 799. [Expected counts and stream hashes](expected.json)

## Check the sender and receiver

From the repository root on Linux, supply the original floating-point TS 26.443 C source dated November 4, 2021. The command uses Python 3, NumPy and GCC. It generates the repository’s [48-second synthetic signal](../check_p2_codec_bits.py), encodes it at both bandwidths, and decodes both complete streams. An observer in a temporary build reads the writer's physical bit positions, the values received in the decoder and the two pulse counts after TCQ. The command checks the full G.192 and PCM hashes against stock outputs.

```sh
python examples/nov27/validation/hq-history/check.py /path/to/evs/c-code
```

## Where the reports can be observed

Physical bit zero is the MSB of the signalling octet. At 13.2 kb/s, the five-bit signalling indices for NB, WB and SWB low-rate MDCT are 29, 30 and 31. Physical bit 5 selects HQ when zero. For NB or WB HQ, bit 6 indicates the ACELP-to-HQ switch. With bit 6 clear, bit 7 is the transient flag. With bit 6 set, bit 7 describes the previous ACELP frame length and bit 8 is the transient flag. The two history bits occur later, after the variable-length band-energy and tonality fields.

In this wideband control, the first history bit occupied physical positions 39 through 86. Both report bits lay within the first 128 bits in all 978 words. Under the transport projection that retains the mode and payload offsets `i % 3 != 0`, both bits occupied directly received positions in 690 reports, one in 61 and neither in 227. These occupancy counts use the parser's known addresses. Reading a report from a partial word also requires locating its fields.

Under four-position interleaving, 238 position-three reports referred to the immediately preceding position-two word. Both report bits occupied directly received positions in 173 of those 238. Such a report can check the two pulse-presence flags from a complete earlier decode. Many pulse counts and encoded words yield the same pair. In particular, the report does not identify any of the six late payload octets, and the SWB branch supplies no such report.

The reference uses the bandwidth-to-inner-length table in `lib_com/rom_com.c` line 14170. The two writes are in `lib_enc/hq_lr_enc.c` lines 591 and 826, under the conditions at lines 329 and 594. The state update at lines 845–858 tests `npulses[bands-2]` and `npulses[bands-1]`. The decoder reads these flags in `lib_dec/hq_lr_dec.c` lines 257–264 and 522–528. This control exercises the 13.2 kb/s WB and SWB branches. The NB condition comes from the source.

## Applicability on the broadcast

Of 67,320 received words in 1,122 complete, disjoint development groups, 12,358 signalled HQ. All selected the SWB mode. The two retrospective pulse flags therefore had zero eligible words in these recordings. Run `python on_air.py /path/to/data_units.npz` in this directory to reproduce the count on a CRC-checked transport archive. [Counts by recording and archive hash](received-counts.json)
