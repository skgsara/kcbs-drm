# A stock EVS transition tag predicts two early bits, with on-air exceptions

At 13.2 kb/s in SWB ACELP TRANSITION mode, the stock encoder writes between zero and six reserved zero bits at the end of a 264-bit word. Two observable bytes, the mode and the final payload octet p31, can rule out transition tags that need more terminal zeros than the word contains. This predicts the two high bits of payload octet 0 (physical b8 and b9, with b0 the mode MSB). The receiver reports the alternatives for each slot. It retains the word erasure even when only one pair remains.

## A frozen receiver on the 12:15 recording

The first 120 seconds of the November 27 12:15:02 UTC 3205 kHz recording yielded 148 CRC-valid DUs. Two separately built Dream receivers returned identical MSC bytes and all 148 DUs matched over 105,968 bytes. All 72 assigned counters were absent from the frozen 13,030-ID inventory. Thirty-five groups were complete. Only the DRM IQ was used. An earlier project report already listed the 12:15:02 UTC, 3205 kHz capture with 30,360 slots. It supplied aggregate counts without a file hash or individual counter IDs. The matching time, frequency and duration indicate prior processing of this recording. The 72 received IDs were new to the local inventory, and the public record does not establish a previously untouched capture. [Earlier processing report](../../../docs/november-2026.md#seven-additional-november-27-recordings) [Protocol as published before accessing IQ](https://github.com/skgsara/kcbs-drm/commit/5ba8c7f3e1b2f8556e4b4033e65fa74029943022) · [RF inputs and hashes](reception.json) · [Full per-slot results](field-results.json)

The first complete counter was **43872771**. Each position had 15 received slots and 2,640 directly visible bits. In slot 54, position 3, mode `60` and p31 `D2` left only `00` for b8–b9 under the stock rule. The other two SWB transition words in that group admitted all four pairs. None of the 5,280 hidden bits in this group has a separate clear label in this test. The direct projection remains at 10,560 bits, with **zero complete clear words out of 60**.

| Over all 35 complete groups | P1 | P2 | P3 | P4 | Total |
|---|---:|---:|---:|---:|---:|
| Slots with at least one pair excluded | 36 | 27 | 28 | 31 | 122 |
| Individually predicted hidden bits | 69 | 54 | 49 | 56 | 228 |

Of 205 SWB transition slots, 113 yielded an exact pair, two fixed only b8, seven excluded one pair without fixing either bit, and 83 left all four pairs open. None had an impossible visible suffix. The low bit of p31 was zero in all 47 complete-group mode-`61` slots, an independently observable implication of the mode alone. No independent accuracy score is available for the 228 hidden-bit predictions here.

## Where the on-air labels disagree

All P1 and P2 comparisons below use previously supplied values. For the seven older receiver dumps and the P2 fixtures the relevant text column falls in the ordinary record header or body covered by its CRC. Multiple slots in a counter can share a single text witness.

| Label source | Words with fewer than four allowed pairs | Label inside allowed set | Exact pair predictions matching | Individual bit predictions matching |
|---|---:|---:|---:|---:|
| Public Nov 25–26, P1 | 1,043 | 1,038 | 771/776 | 1,668/1,678 |
| Nov 27 13:17, 17:44 and 17:56, P2 | 308 | 306 | 230/231 | 492/494 |

* **P1.** The five discrepancies came from two counters, 43767843 and 43768148. The contributor marked both supporting text items as replaced. For one record, two different published bodies give the same CRC `E0C8` with the original header. Both text interpretations differ in their high two bits at all six affected column occurrences. This makes the five archived labels uncertain even though the original records pass CRC. A separate check of 642 November 27 P1 development words had 353 restrictive predictions, all of which agreed. [Older-archive scores, examples and all five discrepancies](p1-archive-results.json) · [Record CRC sensitivity](p1-disputed-records.json) · [Comparison with contributor's separate text revisions](p1-text-comparison.json)
* **P2.** Both discrepancies occurred at counter **43877110**. Slot 37 admitted `00` and `01`. Slot 41 admitted only `00`. Both labels were `10`. The two labels share column 11 in the same text record with transmitted CRC `A2C0`. A fresh decode of the original IQ with a separately built Dream recovered the same mode/p31 values, `61/30` and `60/C6`, and identical full DUs bracketed by the neighboring phase-zero anchors. The transport and text checks each reproduce. The cause of the disagreement remains open. [Scored P2 labels](p2/fixture.csv) · [Original packet and text checks](p2/43877110-source.json) · [Fresh IQ replay](p2/43877110-iq-replay.json)

The P2 fixture includes 310 words with a prior record witness and a potentially restrictive mode. Two admitted all four pairs. Another 15 flag-supported words lacked a header/body witness and were excluded from the score. Independently labeled target bits were unavailable at P3 and P4. An allowed-set exclusion is a diagnostic when evaluating the broadcaster. These discrepancies prevent treating it as a universal plaintext requirement.

## Rules and reproduction

The transition tag starts at b6. The standard reference encoder uses `1, 0101, 0100, 011, 001, 0001, 0000`, with minimum terminal-zero counts `0, 1, 3, 6, 2, 6, 0`, respectively. TBE and BWE share the tag and terminal ordering. A zero in extension data can make the zero run longer. A tag ending at b8 leaves b9 unconstrained. The seven source entries are in TS 26.443 `lib_enc/enc_tran.c` and the 11.60 kb/s row of `lib_com/rom_com.c`. [Receiver rule](../../../scripts/evs_transition_tags.py) · [Stock EVS control](stock.json)

From the repository root, the released MSC reproduces the blind-test scorer input. The last command gives the four-position projection for the primary counter.

```sh
study=examples/nov28/swb-transition
gzip -dc "$study/historical-counter-ids.json.gz" > prior.json
python scripts/salvage_msc_packets.py "$study/msc.bin" --transport-only --out replay-du
python "$study/check.py" replay-du/data_units.npz replay-du/provenance.json prior.json > replay-fields.json
cmp replay-fields.json "$study/field-results.json"
python scripts/project_evs_group.py "$study/data_units.npz" --counter 43872771 --field-checks
```

With the group's original WAV and a patched finite-file Dream, use `scripts/demod_iq_window.py` with `--seconds 120 --reception-profile wiener --mlc-iterations 1` and compare the resulting MSC with the released one. The independent replay also reproduced every shared DU byte. [Receiver output](msc.bin) · [CRC-checked DUs](data_units.npz)

The P1 checker can reconstruct the historical score from the contributed receiver dumps in the public repository. The P2 checker rescores the already witnessed labels and verifies their column locations in the released fixture.

```sh
python "$study/p1_archive.py" predict predictions.json
python "$study/p1_archive.py" score predictions.json dcbbed55b9c48c05fe8a9663ddcb198fa6e50ba0c69c492f7228a98da40cd017 score.json
cmp score.json "$study/p1-archive-results.json"
python "$study/p2/check.py"
```

To reproduce the compact native control, generate little-endian PCM with `make_pcm()` in [the published 48-second stimulus](../../nov27/validation/late-payload/gsc-control/stimuli.py). Encode it with `EVS_cod -q -no_delay_cmp -max_band SWB 13200 32 input.s16 stock.192`, then run `python "$study/stock.py" stock.192`. All 43 restrictive cases among 72 transition words in that stream accepted the original pair.
