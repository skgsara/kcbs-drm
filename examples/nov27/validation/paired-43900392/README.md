# Two independent 3205 kHz IQ recordings of counter 43900392

On November 27, 2026, two Japanese SDRs recorded three minutes of KCBS-2
at 3205 kHz. Each wrote 8,640,000 complex sample pairs at 48 kHz. The
receiver timestamps show no jumps larger than a sample. JL1EDU in
Yokohama yielded 11 complete groups. 7L4IOU in Edogawa, Tokyo, yielded
74. Both identified service `A00002`.

Before recording, we chose the earliest complete group recovered at
Yokohama as the target. We froze the receiver before demodulation, then
saved its output for that counter before demodulating the Tokyo recording.
Both stations recovered the same three data units at `43900392`. At each
of the four positions all 330 directly transmitted octets matched, with
165 received octets whose clear value is unknown. Across the 60 slots,
10,560 bits can be compared and 5,280 clear-text bits remain unscored.
The result contains zero complete clear EVS words. The second position's
15 received mode octets indicate eight HQ and seven TCX20 frames.
[Input hashes, timing and comparison](comparison.json)

We also checked whether EVS advertised a redundant copy of an earlier
frame. At 13.2 kb/s the EVS reference decoder reads the first five bits
of the mode octet. Values 21 through 28 signal channel-aware mode.
All 60 slots at this counter had value 31. Across the full three-minute
recordings, none of the 5,800 distinct headers from CRC-checked data
units signalled channel-aware mode. Yokohama supplied 880 headers and
Tokyo supplied 5,540, including 620 received at both stations.

## Reproduce from IQ

The two 24-second stereo IQ excerpts were resampled to 12 kHz. Both
reproduce the target's three original MSC records byte for byte. The
original sample ranges are in 48 kHz complex pairs with the end excluded.

| Station | Original sample range | Target rows in excerpt, zero-based | Excerpt WAV SHA-256 |
| --- | --- | --- | --- |
| JL1EDU | 2016000–3168000 | 35–37 | `97116019f94aa5457d9fdf2e521f79dba07b956a959e8a49c0d4358b46091671` |
| 7L4IOU | 2304000–3456000 | 27–29 | `b452351d8987cd788a03b9058c9c71d4a9c306e702917ef1e96e3bdfae22b06a` |

From the repository root, use the patched Dream build and a fresh output
directory for each station.

```bash
inputs=examples/nov27/validation/paired-43900392
for station in jl1edu 7l4iou; do
    run=work/$station-43900392
    python scripts/demod_iq_window.py "$inputs/$station-3205-43900392-iq12.wav" "$run" --seconds 24
    python scripts/salvage_msc_packets.py "$run/msc.bin" --out "$run/units" --transport-only
    python scripts/project_evs_group.py "$run/units/data_units.npz" --counter 43900392 > "$run/projection.json"
    sha256sum "$run/projection.json"
done
```

Each projection must have SHA-256
`5070d33e922265638c9279169988c963c713c75d3ecf5ad7ddcaaf8fce80b54a`.
