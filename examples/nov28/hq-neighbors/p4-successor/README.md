# A later HQ word can constrain the preceding word

The November 27 13:17 UTC 3205 kHz receiver supplied five first-position EVS words in three complete counters with a positive high-band spectral-domain shortening flag. The previous fourth-position word had a directly received mode octet of `F8` in every case. The five G.192 fourth-position slots were erasures. The comparison uses consecutive 20 ms words at 13.2 kbit/s in regular, non-switching superwideband HQ mode.

## Reproduce the receiver measurement

Give the checker the `c-code` folder from the floating-point TS 26.443 reference package. It builds a decoder with one logging statement and reads each first-position word as a fresh, single-word stream. The fixture contains the five already supplied audio words, the nine complete 716-byte received data units from the three counters, first-position transport projections, source hashes and the ordinary text records' header, body and transmitted CRC. Python 3 and GCC are required. [TS 26.443 source package](https://www.etsi.org/deliver/etsi_ts/126400_126499/126443/19.00.00_60/ts_126443v190000p0.zip)

```sh
python check.py --source /path/to/c-code
```

The default check uses the included `received-du.bin` to verify each data unit's phase, embedded counter where present, SHA-256 and transmitted CRC. It compares the five directly received preceding mode octets and all 22 direct first-position octets per word. The 6,444-byte file preserves received data in counter and phase order. Audio exported in clear EVS format is limited to the five supplied first-position words.

Owners of the original joined packet snapshot and ordinary G.192 replay can also verify the binding to both full files, including the five supplied G.192 words and preceding erasures. The optional packet archive check requires NumPy.

```sh
python check.py --source /path/to/c-code --packets /path/to/packets.npz --g192 /path/to/programme.192
```

| Counter | Prior P4 phase/cycle | Supplied P1 phase/cycle | P1 slot | High band (0–3) | SPT bit in P1 | Physical source |
|---:|---:|---:|---:|---:|---:|---|
| 43876415 | 1/0 | 1/1 | 32184 | 1 | 111 | text-supported payload |
| 43876415 | 1/1 | 1/2 | 32188 | 2 | 108 | text-supported payload |
| 43876415 | 1/4 | 2/0 | 32200 | 2 | 102 | direct payload |
| 43876822 | 1/1 | 1/2 | 56608 | 3 | 117 | direct payload |
| 43876848 | 2/3 | 2/4 | 58196 | 3 | 102 | direct payload |

Physical bit 0 starts the mode octet. Bits 102 and 117 lie in directly transmitted payload octets 11 and 13. Bits 108 and 111 lie in payload octet 12. The native parser locates each flag after reading the full supplied P1's class, variable-length band energies and current tonality flags. A transport bit at a listed address gains its SPT meaning from that parse.

## What the sender rule says

In the reference sender, `lib_enc/hq_lr_enc.c:spt_shorten_domain_set` emits a one for a high band only when its previous saved peak is nonzero and the current peak lies inside the shortened domain. Before this operation, the sender clears the saved peaks if the preceding HQ class was other than `HQ_NORMAL`. After a normal frame it also clears each band's peak if that frame’s peak-to-average flag was zero or its pulse count was zero. The routine `updat_prev_frm` in `lib_com/swb_bwe_com_lr.c` copies those peaks to the next frame. The four bands remain aligned under the conditions above.

Consequently, each later one implies an earlier normal class (physical b8=0 for `F8`), an earlier peak-to-average flag of one for that specific band and an earlier nonzero pulse count. The earlier flag's physical location depends on the earlier word's own variable-length encoding. A later zero permits either earlier tonality value. A stock-sender conformance test uses unprotected artificial PCM and the same public source.

```sh
python sender.py --source /path/to/c-code
```

The sender control uses NumPy to generate eight seconds of artificial audio. The stock and logging-only encoders produce the same 400 words. Among 14 consecutive `F8` pairs, four shortening flags were one. All four had a matching earlier peak-to-average flag, positive pulse count and saved spectral peak. The eight zeros followed five earlier zero tonality flags, two earlier ones and one transient frame.

## How the five were selected

The full 88,880-slot ordinary replay contained 6,561 supplied first-position words, including 1,837 with mode `F8`. Of these, 1,737 in 246 P1 counters immediately followed a received `F8` P4 mode. One-word cold decoding reproduced the original chronology's addresses and values for all 1,737. There were 510 transmitted shortening flags across 437 of those P1s. Nineteen were one in 15 P1s.

Requiring all 15 P1s of the successor counter to be text-supported and free of observed native BFI or BER left 1,671 pairs in 237 counters and six positives. Requiring both words to lie in the same counter left 1,554 pairs in 232 counters and five positives. All 232 counters had three complete CRC-valid data units. Three positive flag bits lie on direct lanes, one in each of the three positive counters. The other two positive P1s belong to one of those same counters. [Exact group and slot denominators](fixtures.json)

The three supporting ordinary text records used historical phrase matching and a transmitted CRC. The header/body/CRC portion covers every one of the eleven columns used for P1 in the corresponding counter. The text CRCs are `6B00`, `2091` and `A2E8`. Thus this is a text-assisted test, including the cases where the final flag bit itself was directly received. The cross-word test uses only the preceding P4 mode octet. The stock-sender implication has no independent clear fourth-position export in this recording for a bitwise comparison.
