# Held-out 3205 kHz fields in the November 27 archive

The published mode-only rule predicted the high nibble of EVS payload octet 4 would be `C` in 531 INACTIVE/BWE slots. **All 523 received target nibbles matched.** Eight target octets lacked a packet receipt. No received mode in this interval qualified for the ordinary AUDIO bit-40 check. The predictions were sealed before scoring the target octets from the same recording. These counts describe slots in one transmission. [Mode-only predictions](forecasts.json) · [Forecast seal](forecast-seal.json) · [Observed fields and all 60 primary slots](score.json)

| Four-frame position | Forecasts | Matched | Contradicted | Target unavailable |
|---|---:|---:|---:|---:|
| 1 | 140 | 132 | 0 | 8 |
| 2 | 131 | 131 | 0 | 0 |
| 3 | 128 | 128 | 0 | 0 |
| 4 | 132 | 132 | 0 | 0 |

The first complete native group was **43872973**, starting at zero-based MSC row 9. Its three successive data units passed all twelve physical packet checks and all three data-unit CRCs. It contained 11 eligible nibbles, at slots 17–27, all received as `C`. The full window yielded 859 CRC-valid physical packets with the expected headers out of 1,180 checked, 154 complete native data units, 116 counter-assigned complete data units and 22 complete groups. There were 63 assigned counters, with gaps between 43872971 and 43873067. None appeared in the prespecified 14,958-ID inventory. [Native MSC](native.msc.bin) · [Counter inventory](../../dual-diversity-field/history-origins.json)

In the primary group every position supplied 15 physical slots. Each contributed 2,640 directly observed bits and 1,320 carried bits of unknown clear value. Across all 60 slots, 10,560 bits were directly observed and 5,280 clear bit values remained unresolved. The existing codec rules also conditionally fixed 2, 0, 3 and 5 bits at positions 1–4 respectively. Those ten bits have no independent transmitter-side labels here. The recording supplies zero complete clear EVS words. [Per-position counts and per-slot evidence](score.json)

## Input and timing

The interval contains exactly 1,440,000 complex samples, starting at sample 2,880,000 of the contributor's 12 kHz WAV. The filename and nominal rate place it at 12:19:02–12:21:02 UTC. The WAV contains no station clock timestamps. Decoding the accompanying FLAC reproduced every selected original PCM byte. Two earlier local receiver passes used only the opening 120 seconds. A contributor had already reported aggregate results for about 607 seconds of this 611-second recording. This interval was held out for local field scoring. [Exact input and receiver receipt](reception.json) · [Selected IQ](3205kHz-240-360s-iq12.flac) · [Previous processing](../../swb-transition/README.md)

## Replay

From the repository root, set `KCBS_DREAM` to the finite-input Dream executable. The original pass used SHA-256 `1e398433affbe71e3bdbc30171e9c770ddd3a622c0fe1577b3f3837c3fa07a26`. Python 3.11 or later, NumPy, SciPy and SoundFile with FLAC support are required. Use an empty output directory for each run. [Receiver build](../../../../build/README.md)

```sh
case_dir=examples/nov28/clear-evs-controls/iq
out=$(mktemp -d)
python scripts/demod_iq_window.py "$case_dir/3205kHz-240-360s-iq12.flac" "$out/rf" \
  --start 0 --seconds 120 --reception-profile wiener --mlc-iterations 1
cmp "$out/rf/msc.bin" "$case_dir/native.msc.bin"
python "$case_dir/check.py" freeze "$out/rf/msc.bin" "$out/check"
cmp "$out/check/forecasts.json" "$case_dir/forecasts.json"
python "$case_dir/check.py" score "$out/rf/msc.bin" "$out/check" \
  f4b7fcafab4a050ee236c69029533e0f4a793140c0aaed0554a4da811bd59017
cmp "$out/check/score.json" "$case_dir/score.json"
```

To check the packet and field results without rebuilding Dream, supply the published `native.msc.bin` to the last two Python commands. To regenerate the IQ excerpt from the original WAV, run `python "$case_dir/extract.py" ORIGINAL.wav NEW.flac`. The extractor checks the original hash and compares the decoded FLAC with the selected PCM bytes. [Predeclared interval and field rules](../protocol.md)
