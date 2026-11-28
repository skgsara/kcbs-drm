# November 28 blind test of the GSC field checks

Use the full 180 seconds of IQ beginning at the first sample of the new 7L4IOU Edogawa connection on 6140 kHz, starting 00:28:38.703 UTC. The original WAV SHA-256 is `d30a326723237a1c107084822cc9cc7b6b2619bf783e934bb4a4ea1538771d2c`. All 8,640,000 sample pairs arrived. Retain the 27.492-microsecond timestamp discrepancy. The RF setup, one Wiener pass at nominal centre, single MLC iteration, and inventory of 12,938 historical counters were fixed before connecting. The inventory SHA-256 is `228387faf758345f1d98aa69563ab6f18d592cdc56e290f5abc3d5a51faf1f8a`.

After freezing the application code, demodulate the original IQ and assemble CRC-valid transport. Compare every assigned counter, including partial receptions, against the frozen inventory before scoring. With zero overlap, use the earliest complete counter as primary and report all complete groups. Verify that ascending counter order agrees with the physical timeline for primary selection. Retain a failed reception, overlap or zero eligible fields in the result.

Test these three previously observed properties of ordinary 264-bit EVS words. Word bits count MSB first, including the mode. Payload bytes count from zero after the mode.

| Observations allowed for prediction | Field withheld from that prediction | Predicted value |
|---|---|---|
| SWB GSC AUDIO mode, index 13 | Bit 40 (payload 4 high bit) | 0 for frequency-domain extension, 1 for time-domain extension |
| SWB GSC INACTIVE/BWE mode, 74–77 hex | Bits 40–43 (payload 4 high nibble) | Binary 1100, an empirical prediction |
| AUDIO/TBE mode 68–6B hex, noisy flag set at bit 40, and a pitch-band index of 1–10 at bits 41–44 | Bit 223 (payload 26 low bit) | 0, the last padding bit before the backward-coded pulse index |

Hash the sorted mode-only predictions before extracting payload 4. Next form and hash the list of padding predictions using just the mode and the upper five bits of payload 4. Only then read payload 26. A mismatch is a recorded counterexample. Each predicted bit excludes its complement and the predicted nibble excludes the other 15 values. Report all disagreements, primary cases, per-position coverage, and which prediction directions were untested. Keep the clear-word erasure count distinct from the number of individual fields checked.

The receiver takes only the new IQ. Use the source revisions of `scripts/evs_gsc_fields.py`, `scripts/project_evs_group.py` and `check.py` in this commit. The earlier side-by-side TCX spectral controls use a separate, already published first-position fixture.
