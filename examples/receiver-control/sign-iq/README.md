# Four-position reception from alternate IQ samples

The first complete group outside our frozen local counter inventory was **43288750**. The even-numbered samples and the withheld odd-numbered samples each recovered all 60 physical slots. Their 10,560 directly carried bits agreed. The original clear values of another 5,280 bits lack an independent label. The receiver returned **zero complete clear EVS words**. [Protocol frozen before reception](https://github.com/skgsara/kcbs-drm/commit/f4baa45718786c9756fd62511cd8db9eac0b11d3) · [First-pass decisions sealed before the comparison](https://github.com/skgsara/kcbs-drm/commit/d3bb62e9ba4d562f0e008de39e3047ab3c5cdec9)

## November 19 wideband recording

Each receiver used 10,944,000 disjoint I/Q pairs from seconds [156,180) of the 6140 kHz recording. Both produced an identical 38,796-byte MSC file. Each accepted 212 physical packet CRCs across 53 data units. All 204 physical packets in their 17 complete groups matched byte for byte. The first complete group was 43288735, which was already in the inventory. Counters 43288750 and 43288751 were complete and previously unregistered. The next counter, 43288752, had one assigned phase, with 3,520 direct bits independently reproduced across both views. The source was recorded at one antenna. RF fading and transmitter behavior are shared across the two views. [Sample boundaries and prior exposure](field/inputs-and-exposure.json) · [Direct bit comparisons by counter and position](field/even-comparison.json)

| Counter 43288750 | P1 | P2 | P3 | P4 |
|---|---:|---:|---:|---:|
| Received slots | 15 | 15 | 15 | 15 |
| Direct bits matching the withheld sample view | 2,640 | 2,640 | 2,640 | 2,640 |
| Individually fixed direct bits from EVS field rules | 2 | 2 | 1 | 2 |
| Conditional bit predictions within the 1,320 opaque bits per position | 12 | 11 | 14 | 11 |
| Complete clear EVS words | 0 | 0 | 0 | 0 |

The seven individually fixed direct bits are included in the 10,560. At consecutive slots 35–41, the receiver predicted HQ word bit 6 was zero. A separate parser read zero at all seven coordinates in the odd-sample native MSC and checked all twelve packet CRCs and three DU CRCs. A constant-zero baseline also scores 7/7 here. The 48 conditional bits comprise 44 TCX history predictions of word bit 8 and two transition predictions of the pair at word bits [8,10). The second sample view receives the same opaque bytes and supplies no clear labels for scoring those predictions. The compressed JSON records each rule's assumptions, its allowed values, its excluded-value count, and the affected word bits at each slot. [Even-sample fields](field/even-fields.json.gz) · [Odd-sample fields](field/odd-fields.json.gz) · [Withheld raw MSC](field/odd-msc.bin) · [Seven individual bit checks and their physical offsets](field/even-raw-field-check.json)

## November 27 amplitude check

The sign-only receiver produced zero MSC rows on the entire 201.472-second 12:00:34 UTC recording. The full-resolution PCM16 receiver produced 497 MSC rows, 486 native CRC-good data units and 156 complete native groups. Its first complete counter was 43872048. It produced zero clear EVS words at that counter. The contributor had previously analyzed this file. Their summary reports 498 CRC-good data units, and the identity of their individual counters is unavailable. None of our 163 assigned IDs occurred in the frozen 15,274-ID registry. The historical mono-IF development control exposed another 71 IDs. Neither field test overlaps those 71. [Source and outputs](field/inputs-and-exposure.json) · [Full-resolution field decisions](field/original-fields.json.gz) · [Sign-only comparison](field/sign-comparison.json)

The same sign quantization also failed to produce packets on two development recordings that yielded complete groups at full resolution. Preserve the original amplitude samples when using these recordings with the tested Dream receiver. [Development measurements](development.json) · [Mono real-IF input and control results](../real-if/README.md)

## Replay

Download the two original recordings from the [sample release](https://github.com/skgsara/kcbs-drm/releases/tag/samples-2026-11-28). Set `KCBS_DREAM` to the pinned finite-input Dream executable and `PYTHON` to a Python interpreter with the project dependencies. From the repository root, choose an empty working directory with absolute path `$tmp`, and set `$wide` and `$stereo` to the original CS8 and WAV file paths.

```sh
D=examples/receiver-control/sign-iq
"$D/replay.sh" even "$wide" "$tmp/even"
"$D/replay.sh" sign "$stereo" "$tmp/sign"
cmp "$D/field/even-fields.json.gz" "$tmp/even/fields.json.gz"
cmp "$D/field/sign-fields.json.gz" "$tmp/sign/fields.json.gz"
"$D/replay.sh" odd "$wide" "$tmp/odd"
"$D/replay.sh" original "$stereo" "$tmp/original"
"$PYTHON" "$D/evaluate.py" compare "$tmp/even/fields.json.gz" \
 b079ce56f627aead14cd511bbcc624349fe5cb0a36ee330392bd2715149e7c6f \
 "$tmp/odd/rf/msc.bin" "$tmp/odd/stock/packets.npz" "$tmp/even/rf/msc.bin"
```

The seven fixed-bit checks can also be replayed against the archived native bytes with the Python standard library.

```sh
python3 examples/receiver-control/sign-iq/verify_raw_fields.py examples/receiver-control/sign-iq/field/odd-msc.bin
```
