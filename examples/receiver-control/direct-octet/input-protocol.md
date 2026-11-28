# Frozen single-IQ input for the directly observed octet test

Use the entire 120-second gap between the two earlier local receiver windows in the November 27 3205 kHz recording. The bounds were selected from receiver receipts before examining the segment's samples, packets, counter IDs, modes or field values. The selection uses one contiguous, fixed-length input with no replacement if it yields poor or empty reception.

| Item | Frozen value |
| --- | --- |
| Original WAV | `10min-2026-11-27T12_15_02Z_3205.00_iq.wav` |
| Original file size and SHA-256 | 29,360,172 bytes, `8ba5576dc9ab560c14a1de3b7def1a176c2f3e95010dfabe890ab002f40bb624` |
| Recorded format | Stereo little-endian PCM16 I/Q, nominal 12,000 complex sample pairs/s, data begins at file byte 44 |
| Span of valid source audio data | 7,330,304 complex sample pairs |
| Selected source seconds | [120, 240) |
| Selected source sample pairs | [1,440,000, 2,880,000), 1,440,000 pairs |
| Original file bytes | [5,760,044, 11,520,044), 5,760,000 PCM bytes |
| Nominal UTC from the filename | November 27 [12:17:02, 12:19:02) UTC; no station timestamp series |

Local receiver records document [0,120) and [240,360); subsequent local runs cover [360,420), [420,480), [480,540) and [540,600). A second replay of the first window used the same start at sample zero. We found no local receiver pass covering this middle interval in the identified manifests. The contributor had already published whole-recording counts and described a separate per-capture verification bundle. The test therefore measures a locally held-out interval. The selection does not establish that the contributor never examined its frames. Earlier reception on both sides makes this a reasonable place to test reception; whether these two minutes contain a complete group remains an outcome. [Opening pass](../../nov28/swb-transition/reception.json) · [Pass starting at 240 seconds](../../nov28/clear-evs-controls/iq/reception.json) · [Later intervals](../phase-anchors/field/input.json) · [Contributor's full-recording report](../../../docs/november-2026.md#seven-additional-november-27-recordings)

## Receiver and scoring order

1. Publish the receiver revision, source interval and byte-rule scoring protocol before extracting IQ or running Dream. Verify the full source file SHA-256. Copy precisely the PCM slice above in the recorded I/Q order. Encode the excerpt losslessly, decode it back, compare every byte, and record its PCM and FLAC SHA-256.
2. Perform one cold finite-input Dream pass from sample zero of the excerpt through EOF, with zero channel offset. Use the earlier fixed Wiener settings (frequency interpolation 2, time interpolation 1, modulation metric 0, one MLC iteration). The Dream SHA-256 is `1e398433affbe71e3bdbc30171e9c770ddd3a622c0fe1577b3f3837c3fa07a26`. The demodulation helper is `fb3cc1cee294e995ee80220f55c8bd8931f53fece482c2b92f92754892eba662`, and the resampler is `2da34edc3e8349639d1f50dbab13ebbc3ca59050d1e8f51f6fcaf6c28cc6e366`. Save settings, input count, return and EOF status, output length, native row count and MSC SHA-256. [Prior receiver receipt](../phase-anchors/field/reception.json)
3. Run stock packet salvage and the published strict phase-anchor checker on that single native MSC. Save both packet archives, complete data units, row assignments and quarantine outcomes. Use the earliest pristine native 0/1/2 group for the primary even if its modes yield no eligible field. Every such row must have all four canonical packets and both packet and DU checksums passing. If the group is absent, report null. Retain every eligible slot in the separately reported cohort defined by the byte-rule protocol, including abstentions and misses. [Phase-anchor checker](../phase-anchors/phase_anchors.py)
4. Seal the coordinate ledger, primary selection and byte forecasts before scoring against the observed target octets. Use only the rule's declared input fields to produce the forecasts. A receipt flag on a packet can establish that it arrived. It cannot by itself establish the clear value of a protected application octet. An absent target contributes to the missing-target count. Retain the source, settings, rule and denominator if all scores are zero.

## Local counter exposure

After sealing the placements and forecasts, intersect the assigned counter IDs (including partial packet-only coordinates) with the published [five-source inventory](../phase-anchors/field-protocol.md#prior-exposure), then include `extended.assigned_counters` from the [immediately preceding field seal](../phase-anchors/field/seal.json). The five-source union contains 15,095 IDs. The 29 IDs in the sixth file are disjoint and include all 27 stock-assigned IDs from that interval. The six-source set contains **15,124** distinct unsigned counter IDs. The SHA-256 of the sorted decimal IDs joined with ASCII commas and no trailing newline is `e586971034668bee5a39208f551bcbbb4ad8a8c716486a4f9d0e30747c9f8b5f`. The sixth source file has SHA-256 `9b58bb342cf18706bf9e18045398db13f671825075d25b9a6fcac8cee24b78d1`. Report collisions and keep the original selection.
