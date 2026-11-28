# Reception with withheld IQ measurements

## Development

Use the public 22-second November 19 6140 kHz channel excerpt and the published November 27 3205 kHz 480–540 second excerpt for the sign test. Use the already received complete groups to check packet geometry and the distinction between a field-domain check and an individual fixed bit. Preserve any failed acquisition. The two field inputs below are fixed before either field pass.

## Sign and full-resolution reception

Use the entire file `2026-11-27T12_00_34Z_6140.00_iq.wav`, SHA-256 `936531e7c934a2fcee981f375a9075dfd7c0e144bf9957b7e431459c584e326c`, 2,417,664 complex samples at 12 kHz (201.472 seconds). Use `quantize.py` to replace each component with +8192 for zero or positive and −8192 for negative. The first receiver reads only this stereo WAV. Save the quantized WAV digest and the first receiver's MSC, packet receipts and decisions before processing the original PCM16 samples. Run the same receiver once on those original samples. Report its own first complete group even if the sign-only arm has no acquisition. The two decodes use the same RF recording. The full-resolution comparison withholds amplitude information, and shares the sign measurements.

The contributor already processed this recording. Their public summary gives 498 CRC-good DUs across the file, with individual counter IDs unspecified. Report local inventory overlap separately. [Original report](https://github.com/skgsara/kcbs-drm/blob/2b5cb213eefffa7caf6894925299770dfd550a20/docs/november-2026.md#seven-additional-november-27-recordings)

## Disjoint original samples

For a separate test, use the November 19 `onair_drm_6.140MHz_0.912Msps_20261119-173139.cs8` recording, SHA-256 `0764eb4f22d318efdda8572efe78269796f6ae8bd6257b63738537c95617486f`. Read original complex-pair indices [142272000,164160000), corresponding to recording seconds [156,180). Each pass receives exactly 10,944,000 complex pairs at 456 kHz. The first pass receives even-indexed pairs only. The withheld pass receives odd-indexed pairs only. Split original bytes before any filtering. Treat both files as centered at 6140 kHz with zero digital offset. New RF acquisition begins at the start of each view. The two subsequences are offset by one original sample period and come from the same antenna and broadcast.

Seconds [156,176) overlap previously inspected RF and serve as acquisition time. Seconds [176,180) fill the previously unprocessed four-second gap in the documented local receiver intervals. Preserve every assigned ID and its overlap. Seal the first arm before examining the odd-indexed view. Report any exact agreement on directly carried bits under matched counters and positions. Complete wire equality and word-level erasure are distinct measurements.

## Common receiver and scoring

The two sign-only development recordings both reached file end with zero MSC rows. Keep the sign test as a measurement of the cost of discarding amplitude.

Run the finite-input Dream executable with SHA-256 `1e398433affbe71e3bdbc30171e9c770ddd3a622c0fe1577b3f3837c3fa07a26`, at nominal tuning using the Wiener profile and one MLC iteration. Give each view one pass over its full declared span. Use the unmodified receiver MSC as the sole input to stock packet salvage with `--transport-only --save-packets`. Record empty MSC output explicitly. Use a fresh directory per arm.

Select the earliest consecutive native group in MSC row order with phases 0,1,2 and all twelve packet headers, twelve packet CRCs and three DU CRCs accepted. Also record the first such group absent from the frozen local inventory, and the earliest assigned incomplete counter in original MSC row order. Use the same selection for each arm and preserve a null outcome. The prior inventory is the 15,274 distinct IDs from `agreed-bytes/field_groups.py:history()` and `agreed-bytes/field/transport-comparison.json:all_arm_assigned_counters`. Its SHA-256 over sorted decimal IDs joined by commas is `2b7855f7b861f4d6f7ba6704225306bd165ca06c2749dccf3ee866299e5f8664`.

Keep all 60 word slots of each selected group, the allowed and excluded field values, the bytes physically received, and missing and opaque positions. A field domain may rule out several combinations while fixing zero individual bits. Report matching bit counts only on directly carried coordinates observed in both passes. The comparison does not supply independent clear labels for opaque bytes. No text templates, external audio, published masks or other receiver output enter either first arm.

[Original sample files and SHA-256 index](https://github.com/skgsara/kcbs-drm/releases/download/samples-2026-11-28/samples.json)
