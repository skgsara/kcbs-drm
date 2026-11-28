# Three late-octet differences in synthetic EVS words

Each row compares two unmodified stock encoder outputs at the same frame index. The complete 33-byte words differ only at the listed payload octet. Offsets start at zero after the mode octet. Word bits start at the mode MSB. The synthetic quartet position is `1 + frame_index % 4`. [Fixed inputs, complete words and SHA-256 digests](receipt.json)

| Payload octet | Mode | Frame index / quartet position | Original octets | Differing word bits | Immediate previous / following words equal |
|---|---|---|---|---|---|
| 15 | FE, TCX20 | 2 / P3 | F7 and FD | 132, 134 | No / No |
| 18 | 5A, SWB VOICED ACELP | 1 / P2 | BF and 6F | 152, 153, 155 | Yes / No |
| 21 | 5A, SWB VOICED ACELP | 1 / P2 | 39 and 37 | 180, 181, 182 | Yes / No |

The p18 and p21 examples each use three 20 ms frames of synthetic voiced PCM. The earlier retained sender manifest recorded both center words and both full-stream hashes for each pair. The p15 example uses an 84-frame chord, first alone and then with a weak harmonic. The earlier shape-34 aggregate counted one p15-only word pair. Replaying its original experiment reproduced that aggregate and identified the two fixed settings and word hashes listed here. Each case uses two runs of the same reference sender. The examples establish ambiguity of the selected bits under the within-word comparison. They supply no clear label for a broadcast word.

For p15, the 22 directly transmitted word octets agree in 6 of the first group’s 60 slots and in 1 of its 15 P3 slots, the selected frame 2. The three-frame p18 and p21 stimuli end before a complete group.

## Replay

With NumPy and the stock floating-point TS 26.443 encoder dated November 4, 2021, run this from the repository root.

```sh
python examples/nov27/validation/late-payload/early-examples/check.py --encoder /path/to/EVS_cod
```

The checker regenerates only the six specified mono 32 kHz inputs. It checks every PCM hash, full G.192 stream hash, complete target word, exact bit difference and adjacent-word equality. A separate stock MIME encode must unpack to the same sequence of words. [Voiced waveform and common encoder helper](../sender_pairs.py)
