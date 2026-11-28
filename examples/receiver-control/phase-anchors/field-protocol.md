# Single-receiver phase assignment in a held-out broadcast minute

Freeze this protocol, the strict phase-bracketing code and its controls before running Dream on the selected samples or inspecting their MSC rows or counters. The question is how many already received CRC-valid packets the phase tags can place beyond ordinary salvage, and what those packets add to a 60-slot group.

## Radio input

Use the source WAV named `10min-2026-11-27T12_15_02Z_3205.00_iq.wav`, SHA-256 `8ba5576dc9ab560c14a1de3b7def1a176c2f3e95010dfabe890ab002f40bb624`. It has 7,330,304 stereo I/Q sample pairs at 12,000 Hz, little-endian PCM16, with data starting at file byte 44. Select exactly 720,000 pairs in seconds **[540,600)**, sample pairs **[6,480,000,7,200,000)**, original file bytes **[25,920,044,28,800,044)**. The filename gives nominal UTC **2026-11-27 [12:24:02,12:25:02)** and 3,205 kHz. Station timestamps are unavailable. Verify the lossless excerpt against these source bytes. [Source and preceding interval](../on-air/input.json)

This is the next full minute following the earlier [480,540) run. Documented local receiver runs covered [0,120), [240,360), [360,420), [420,480) and [480,540). No local pre-freeze receiver output for [540,600) was identified in those records. The contributor previously reported whole-recording aggregates for the matching start time, frequency and duration. The local interval selection therefore supports a new local receiver test on a previously studied recording. [Earlier local windows](../on-air/input.json) · [Contributor's whole-recording report](../../../docs/november-2026.md#seven-additional-november-27-recordings)

## Receiver and comparisons

Use the preceding field's single cold finite-input Dream run. Feed the excerpt from its sample zero through EOF at nominal tuning with channel offset 0 Hz, Wiener frequency/time interpolation 2/1, modulation metric 0 and one MLC iteration. The frozen Dream executable is `1e398433affbe71e3bdbc30171e9c770ddd3a622c0fe1577b3f3837c3fa07a26`; SHA-256 for `demod_iq_window.py` is `fb3cc1cee294e995ee80220f55c8bd8931f53fece482c2b92f92754892eba662`, and for `resample_iq.py` it is `2da34edc3e8349639d1f50dbab13ebbc3ca59050d1e8f51f6fcaf6c28cc6e366`. Save the original MSC, its hash, EOF status, record count and receiver settings. Both placement methods use that byte-identical MSC. The run has a single input and a single pass. [Pinned receiver and replay command](../on-air/receipt.json)

1. Run the existing packet salvage with `transport_only=True, save_packets=True`. Retain stock coordinates, individual CRC-valid packets, rejected rows and source-row provenance. The baseline script has SHA-256 `de976480dc1ba2fa6fc10352c1b8bd40a9a3cf7c9fb8a362f05dfa61754bf77e`. [Stock parser](../../../scripts/salvage_msc_packets.py)
2. Apply the frozen strict checker to the same original native rows. Endpoints are received phase-zero anchors with CRC-valid phase and counter packets. An interior row must carry its own CRC-valid phase tag and have the same coordinate in every feasible ordered placement between those anchors. Preserve untagged rows in checking placement feasibility. Respect counter wrap and parser barriers, including malformed lengths, a CRC-valid unexpected ordinal header, or a complete row failing DU CRC. Add only physically received CRC-good packets. Keep conflicting proposals or failed assembled DU CRCs out of accepted coverage. Report the source row, flanking anchors and packet ordinals for each addition. Selection and placement use only this single native stream, independently of the inventory, any peer station, earlier transmission, known text or reference audio.
3. Compare distinct accepted packet coordinates `(counter, phase, ordinal)`, CRC-valid complete DUs, complete three-DU groups and changes to baseline coordinates. Retain zero gains, losses and rejected cases. A reassembled group must be counted separately from an original pristine group.

## Fixed 60-slot selections

**Primary.** Take the earliest three consecutive original MSC rows in file order with phases 0, 1 and 2, all four correctly headed packets and the DU CRC passing on each. Read the transmitted counter from phase zero. A later reconstructed group cannot replace it. If there is no pristine triple, record null.

**Incomplete placement control.** After strict placement, select by the earliest *newly placed native row* that contributes at least one accepted packet coordinate absent from baseline to a group still lacking some physical word octets. Break a tie on row ordinal by ascending counter. Report null if every such group is physically complete or there is no such row. Keep both selections on any historical counter overlap.

For each selected group, report both methods at the same 60 chronological slots. The zero-based slot is `20 × phase + 4 × cycle + position − 1`, with 5 cycles per phase and positions 1–4. Count complete (mode plus all 32 payload octets), partial and absent physical slots per position. The public projector gives a hex byte for a directly carried clear octet, `??` for a physically received octet with unknown clear value, and `--` for an octet whose packet is absent. Count these categories separately. A complete 60-slot transport group supplies 15,840 physical bits, including up to 10,560 directly readable clear bits under this projection. Count a full clear EVS word only when all 264 clear bits are independently available. This test supplies no external labels for the protected octets and no decoded audio target. [Public projection and slot geometry](../../../scripts/project_evs_group.py)

## Prior exposure

After sealing both placement results and the selected counters, intersect all assigned counter IDs from each method with the union of the five published sources below. Report the overlap IDs and counts, including any assigned ID present in the preceding minute. Keep the placement ledger fixed during comparison. The five sets have no mutual overlap in these archives and contain **15,095 distinct IDs**. SHA-256 of their ascending decimal IDs joined with ASCII commas and no newline is `c9881e036bd57ab12cb8af4a5177a02bc30b348dd61d85539c6963d6a36032c1`.

| Published source | JSON field | Unique IDs |
|---|---|---:|
| [Earlier receiver inventory](../../nov28/dual-diversity-field/history.json.gz) | `counter_ids` | 14,958 |
| [First IQ trial](../../nov28/clear-evs-controls/iq/forecasts.json) | `assigned_counters` | 63 |
| [Four-iteration comparison](../../nov28/clear-evs-controls/iq-mlc4/forecasts.json) | `assigned_counters` | 29 |
| [Packet CRC field comparison](../../nov28/packet-bit-repair/field/group-evaluation.json) | `combined_exposure.assigned_counters` | 24 |
| [Immediately preceding on-air minute](../on-air/coverage.json) | `all_assigned_counters` | 21 |
