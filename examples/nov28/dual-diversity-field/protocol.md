# Prospective two-station DRM reception

Record one new 90-second interval of the public 6140 kHz broadcast at 7L4IOU Edogawa and JL1EDU Yokohama. The two simultaneous raw IQ files are the only observations available to the joint receiver. The two original, separately decoded MSC streams remain available for a separate comparison. Publish this protocol, the receiver code, its development checks and the prior-exposure inventory before opening either radio connection. [Capture settings and station endpoints](receive-plan.json) · [Prior exposure](history-origins.json)

Start both connections together after the freeze. Request 4,320,000 stereo PCM16 complex pairs per station at 48 kHz and preserve per-packet station timestamps. Use all received pairs up to the requested count, starting at sample zero. Preserve a partial or empty capture, sample geometry, exact time coverage when available, gaps and uncertain timestamps. Each station gets one connection attempt. If a station delivers zero pairs, record the missing observation explicitly and represent its native MSC and cell observations as empty for this evaluation. If Edogawa is absent, the joint timeline is empty.

## Receiver and measurement

1. Use one finite-input demodulation per recording, from a cold start at nominal tuning with the Wiener reception profile and one multilevel decoding iteration. Save the native decisions and the deinterleaved complex cells at the stock DRM channel decoder's input. The local observer binary digest is `2519ad5f9224e89e65d9dd9e4c85886f986ee656ed889f25e5d7437b9f2df42a`. The separate 16-QAM decoder digest is `8a154e21481152856e3cd6e0adc5b29e68da1ed3c5db939272c474c64e67f581`. [Build and observer format](../same-6140-1232/diversity/observer/README.md) · [Channel decoder build](../same-6140-1232/diversity/fusion/README.md)
2. Keep the Edogawa native row order. A cross-station row match requires a full, unique CRC-valid packet at the same ordinal in both streams. Reject ambiguous, contradictory or out-of-order matches. A matched pair can pool valid native packets. It can also combine cells if both standalone decodes reproduce the native hard decisions, their geometry matches, and the predeclared signal weights can be calculated. A newly reconstructed packet enters the output only in a complete data unit that passes the transmitted CRC and agrees with every already accepted packet. Preserve every original left row outside a witnessed pair. Report gains from pooling and from combining separately. [Alignment and weighting development](../same-6140-1232/diversity/README.md)
3. Run the existing transport-only parser on the two native MSC files and the joint MSC file separately. Select the first three consecutive joint rows carrying phases 0, 1 and 2 with all packet and data-unit CRCs valid. Also report the earliest assigned counter with a partial packet phase, if present. Keep the selections on a prior-exposure collision. Record every assigned counter that appears in the 14,958-ID inventory. A result with any such overlap remains labelled as exposed for the run.
4. For each selection report all four positions, every observed or missing field, and whole-word erasures. Freeze standard EVS field predictions using only Edogawa's native mode bytes. Compare them with the independently decoded target fields in the native Yokohama stream at the same coordinates. Count missing targets and retain the alternative field values each rule rejects. This comparison can verify those individual observable fields. Both stations contribute to the joint receiver, so neither is an independent reference for the joint output as a whole. Unresolved clear bits and missing slots remain explicit.

The 12:32 and 13:47 UTC recordings are development controls. The first contains two previously verified recoveries before channel decoding. The second contains no packet that passed CRC at both sites. No audio reference, supplied mask table, later reception or alternative tuning enters the field evaluation.

## Replay

Supply a fresh work directory, the two receiver binaries, the original IQ files and each sample count. Sample indices count complex I/Q pairs. Run from the repository root. [Development check with both recordings](development.json)

```sh
case_dir=examples/nov28/dual-diversity-field
python scripts/observe_drm_iq.py "$edogawa_iq" --start-sample 0 --sample-count "$edogawa_count" --dream "$dream" --out "$work/edogawa"
python scripts/observe_drm_iq.py "$yokohama_iq" --start-sample 0 --sample-count "$yokohama_count" --dream "$dream" --out "$work/yokohama"
python scripts/drm_diversity.py --left "$work/edogawa" --right "$work/yokohama" --decoder "$decoder" --out "$work/joint"
python "$case_dir/field.py" --left "$work/edogawa" --right "$work/yokohama" --combined "$work/joint" --out "$work/fields"
```
