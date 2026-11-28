# What an IQ receiver can verify in super-wideband GSC

At 00:02 UTC on November 28, a three-minute recording of KCBS-2 on 6140 kHz yielded 85 complete groups. The first complete counter, **43908156**, supplied all 60 transmitted frame slots. At each of the four positions, the mode and directly carried payload bytes supplied 2,640 bits. The receiver left 1,320 clear bits unresolved at each position and produced **zero complete clear EVS words**. Two builds of Dream reproduced identical packets, accepted data units and field scores. [Lossless IQ](7l4iou-6140-20261128T0002Z-iq48.flac) · [Accepted data units](edogawa-data-units.npz) · [Receiver results](live-receipt.json) · [Replay hashes](replay-receipt.json)

## A check we can score from IQ alone

In ordinary 13.2 kb/s super-wideband (SWB) GSC AUDIO, the stock encoder writes a noisy-speech flag at physical bit 40, the high bit of payload byte 4. The directly carried mode octet tells us which bandwidth extension it used. Time-domain extension predicts 1 and frequency-domain extension predicts 0. We can hide bit 40, predict from the mode, and then read the bit from the broadcast to score the prediction. Physical numbering starts at the mode octet's high bit. Payload offsets start after the mode octet and count from zero. [Frozen test](protocol.md) · [Scorer](direct.py)

In 11 stock encodes, all 5,287 time-domain and 2,394 frequency-domain predictions agreed with the encoded bit. On seven development broadcast archives, 799 words qualified and all 799 carried the predicted 1. Counters 43790480 and 43790530 each supplied all 15 observations at each of four positions. These counts include correlated frames. The tested source paths are `speech_music_classif.c` and `decision_matrix_enc.c` for the choice of extension, and `gs_enc.c` for the flag.

The fresh recording contained 1,409 SWB GSC **INACTIVE** frames in complete groups and **zero AUDIO** frames. The preregistered rule abstained on all 5,100 slots, leaving no bit-40 accuracy estimate for this recording. All 120 assigned counters were absent from the frozen 12,771-counter history. The recording contains all 8,640,000 requested IQ sample pairs. One receiver timestamp interval differed from nominal by 22.662 microseconds. [Protocol frozen before demodulation](https://github.com/skgsara/kcbs-drm/commit/5886518975dfb7ad2c23c5d4c416aaee9b5a374f)

A second preselected window used seconds 260–320 of the group's November 19 17:31:39 recording. Its 41 assigned counters were absent from the updated 12,891-counter history. It yielded 39 complete groups and zero AUDIO words in 2,340 slots. The first complete counter was 43288822. [Exact input interval](nov19/source.json) · [Test declaration](nov19/declaration.json) · [Results](nov19/result.json) · [Data units](nov19/data_units.npz)

Two other checks did find enough observations to score.

* In the historical INACTIVE prefixes below, all 6,716 had `1100` at bits 40–43. We fixed that prediction and hashed the mode-only decisions for both recordings before reading the four target bits. We already knew the November 28 mode counts. The prediction matched **462/462** eligible November 19 words and **1,409/1,409** November 28 words, including **471/471** second-position words across the two recordings. At counter **43908269** all 60 slots qualified and carried the four predicted bits. Every observed case used frequency-domain extension. All four bits are directly received. The adjacent attack bit at b39 had two documented exceptions to a constant zero in the historical P1 archive. [Prediction freeze](inactive/frozen-decisions.json) · [Per-position counts and exceptions tested](inactive/summary.json) · [Attack-bit records](archived-controls/README.md)
* The previously published frame-order test matched **184/184** held-back predecessor speech-class bits and **183/183** codec-switch flags within the 85 November 28 groups. Only ascending cycles and positions 1, 2, 3, 4 survived all comparisons among 96 layouts. The primary counter alone admitted 21 layouts. Its two exact predecessor predictions were at slots 13 and 24. The two checks use directly carried bits. [Layout scores and alternatives](frame-order.json) · [Scorer](../frame-order/check.py)

## How much can the known prefix say about bytes 24 and 27?

We supplied only the first 128 bits of **6,716 distinct historical first-position words** to the reference-codec observer. All used SWB GSC INACTIVE. The prefixes came from 240 March groups with fixed idle-text support and 737 November groups with repeated-text support. Each word started with a cold decoder. Each run was repeated with the unknown suffix set first to zeros and then to ones. [Prefixes](archived/prefixes.bin) · [Source coordinates](archived/coordinates.csv) · [Frozen scorer](archive.py)

| Cohort | Prefixes | Words with a located pulse-index field at byte 24 | At byte 27 | Byte values excluded |
|---|---:|---:|---:|---:|
| March | 2,945 | 2,577 | 2,945 | 0 |
| November 25–26 | 3,771 | 223 | 3,771 | 0 |

Locating a field is only the first step. In these words, every value from 0 through 255 remained compatible with each individual codebook range we could establish at the target byte. The frozen output contained no predictions. We kept the historical suffix answers sealed. [Exact output](archived/result.json)

We did find a stock SWB GSC AUDIO word for which the first 128 bits require two later bits of byte 24 to be zero. It used mode `6C` and the last bucket of a 142,544-entry codebook. This leaves 64 possible octets. The original octet was `83`. Cold reference-decoder checks on the complete synthetic word accepted the four predicted low nibbles and rejected all twelve others. This was one selected example in a synthetic experiment with 6,013 qualifying codebook fields. [Waveform, positive and negative controls](sender-control/README.md)

The two November 27 handoff targets use different modes. At counter **43869343**, second position has eight SWB INACTIVE GSC words with frequency-domain extension, four generic ACELP words and three voiced ACELP words with time-domain extension. At **43865914**, all 15 second-position words use SWB TCX20. Both sets already have 128-bit prefixes supported by text labels. Across the three November 27 handoff ledgers, none of the 7,695 second-position slots with that prefix support used ordinary SWB AUDIO with frequency-domain extension (`6C`–`6F`). The eight INACTIVE slots at 43869343 all carried `1100`. Earlier prefix traces had already identified those eight values. [Mode inventory and direct packet replication](handoff-modes.json)

## Two different stock outputs with the same surrounding bits

We encoded small variations of synthetic PCM with the unmodified EVS sender. In both pairs, the two alternatives at position 2 agree on all other 263 bits of the current word. All 205 preceding words are identical within each pair.

| Payload byte | Alternatives | Differing physical bit | What happened in the following 34 words |
|---|---|---:|---|
| 24 | `67` or `77` | 203 | All 34 matched |
| 27 | `CB` or `8B` | 225 | Two differed, then 32 matched |

For byte 24, knowing every other encoded bit throughout the full 4.8 seconds still leaves both values possible. The example tests what EVS syntax and surrounding frames can establish. It leaves open what a receiver can learn from other observations in the same broadcast group. [Encoded words and hashes](sender-pairs.json) · [Stock encoder reproducer](sender_pairs.py)

## Reproduce

Run from the repository root with the project Python dependencies. The RF replay takes a fresh output directory and a finite-file Dream executable. The stock EVS checks use the floating-point TS 26.443 distribution pinned in the [reference software instructions](../tcx-zero-pair/README.md).

```sh
case_dir=examples/nov27/validation/swb-gsc
sh "$case_dir/replay.sh" "$case_dir/7l4iou-6140-20261128T0002Z-iq48.flac" /path/to/dream /tmp/kcbs-swb-live
cmp /tmp/kcbs-swb-live/transport/data_units.npz "$case_dir/edogawa-data-units.npz"
python "$case_dir/direct.py" "$case_dir/edogawa-data-units.npz"
python "$case_dir/sender_pairs.py" --encoder /path/to/EVS_cod --out /tmp/kcbs-swb-pairs.json
cmp /tmp/kcbs-swb-pairs.json "$case_dir/sender-pairs.json"
python "$case_dir/archive.py" /path/to/c-code "$case_dir/archived" /tmp/kcbs-swb-prefixes.json
cmp /tmp/kcbs-swb-prefixes.json "$case_dir/archived/result.json"
python "$case_dir/../frame-order/check.py" "$case_dir/edogawa-data-units.npz" --boundaries --out /tmp/kcbs-layouts.json
python "$case_dir/inactive/check_inactive.py" seal "$case_dir/edogawa-data-units.npz" /tmp/kcbs-swb-decisions.json
python "$case_dir/inactive/check_inactive.py" score "$case_dir/edogawa-data-units.npz" /tmp/kcbs-swb-score.json /tmp/kcbs-swb-decisions.json 56cf87b539d5818882a896e01367eaeb91e8ae581705ca4c882537197199dcc1 --failures /tmp/kcbs-swb-failures.json
cmp /tmp/kcbs-swb-score.json "$case_dir/inactive/nov28-score.json"
```
