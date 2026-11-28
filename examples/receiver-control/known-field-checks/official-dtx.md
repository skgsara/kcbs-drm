# Test the two field rules on official DTX streams

On three clean official DTX sequences, every restrictive transition set contained the original two-bit value (128/128). The previous-core rule matched 778/778 eligible TCX bits. A constant one matched 772/778 of those same bits. The six observed zeros account for the rule's gain over that baseline. [Frozen forecast](official-dtx-seal.json) · [Scores by condition, file and position, with source SHA-256 values](official-dtx-score.json)

| Measure | Clean | f06 | b10 |
|---|---:|---:|---:|
| Good 264-bit words / physical slots | 3,514/4,160 | 3,308/4,160 | 3,157/4,160 |
| Good SID / good no-data slots | 99 / 547 | 95 / 521 | 83 / 477 |
| Bad-frame markers, at all three lengths | 0 | 236 | 443 |
| Restrictive transition sets containing the sender value | 128/128 | 119/119 | 114/114 |
| Equal-sized sets rotated by one, same fields | 61/128 | 54/119 | 53/114 |
| Individually fixed transition bits correct | 123/123 | 118/118 | 110/110 |
| Constant zero, same bits | 103/123 | 98/118 | 93/110 |
| Exact singleton transition fields correct | 45/45 | 43/43 | 39/39 |
| Constant `00`, same singleton fields | 25/45 | 23/43 | 22/39 |
| TCX previous-core bits correct | 778/778 | 687/687 | 663/663 |
| Constant one, same TCX bits | 772/778 | 681/687 | 657/663 |

Each condition represents the same 83.2 seconds. The impaired copies reduce coverage, and all remaining forecasts have clean sibling labels at the same slot and current mode. An additional 73, 70 and 65 transition events respectively allowed all four values. Those events contribute no restrictive prediction. The clean `c` file supplied 759 of its 778 eligible cases, `n1` supplied 19, and `n2` supplied none. Across P1–P4 the clean restrictive-transition counts were 33, 28, 31 and 36, and the TCX counts were 189, 196, 194 and 199. These are chronological positions in these codec vectors. The experiment used no broadcast reference.

## Frozen selection and replay

Freeze the published SWB transition-tag and TCX previous-core rules and this protocol before reading the selected G.192 members. The inputs come from the floating-point TS 26.443 conformance sequences in TS 26.444. The ZIP directory identifies the three clean SWB members named `testvec/testv/bitstreams/swb/stv32{c,n1,n2}_dtx_13200_32kHz.COD` and their six `.f06.COD` and `.b10.COD` variants. Include all nine files. The three conditions share their source material and must have separate scores. The non-DTX versions of the same three source recordings appeared in earlier public controls. [Official archive](https://www.3gpp.org/ftp/Specs/archive/26_series/26.444/test_sequences/26444_g50-TestSeq_Float_26443.zip) · [Previously checked non-DTX streams](../../nov28/clear-evs-controls/erasure-benchmark/corpus.json)

Preserve all 2,760, 700 and 700 physical 20 ms slots in each condition, including final 40-slot tails in the two shorter recordings. P1 through P4 follow slot modulo four from the start of each file. Reset rule history at each file and each 60-slot group. A good 264-bit frame supplies its mode and last octet. A good 48-bit SID, a good zero-bit no-data slot, or a bad-frame marker of any of those three lengths supplies neither. Record these cases separately by position. Reject unexpected sync, length, truncated input, bad serial symbols in a good frame, or a mismatch in per-slot bit lengths between sibling streams. Bad-frame payloads have no reference value.

The preparer writes separate feature and label files. Forecasting reads the mode, final octet and physical coordinates. It knows no target bits. Seal its result before scoring against the corresponding clean word at the same physical slot. Require a good 264-bit clean word and matching current mode for comparison. Record missed comparisons. The transition rule uses bits 8–9 from the clean sender as labels. Report restrictive-set membership, membership in an equal-sized set rotated by one, individually fixed bits and exact singleton fields, with a constant-zero baseline for fixed bits and singletons. For TCX20, compare predicted bit 8 to the clean original and report both constant baselines. An absent eligible rule or class stays absent. The standard vectors do not provide I/Q or radio position labels. [Transition rule](../../../scripts/evs_transition_tags.py) · [Core-history rule](../../../scripts/evs_core_history.py)

Run from the repository root after the freeze. Use a fresh directory for local inputs and results. The range downloader fetches only the named compressed ZIP records and checks their directory metadata and CRC-32. The preparer also hashes each uncompressed member. Keep the original conformance payloads local.

```sh
d=examples/receiver-control/known-field-checks
work=$(mktemp -d)
python "$d/dtx_catalog.py" "$work/members"
python "$d/official_dtx.py" prepare "$work/members" "$work/staged"
python "$d/official_dtx.py" predict "$work/staged/features.json" "$work/forecasts.json"
sha256sum "$work/forecasts.json"
python "$d/official_dtx.py" score "$work/forecasts.json" "$work/staged/labels.json" "$work/report.json"
```
