# Which EVS words survive a missing packet?

In a 40-group, file-only test transmission with a known sender, the receiver emitted **2,113 exact EVS words**, emitted zero wrong words, and marked 287 slots as erasures. The programmed packet failures accounted for 78 necessary erasures. Another 209 arose because the receiver could not assign some intact packets to a counter and phase. The original receiver output and input were published before comparison with the sender. [Frozen test and settings](protocol.md) · [Sealed receiver output](result/receiver.json) · [Independent per-word comparison](result/verification.json)

| Position | Complete words allowed by packet geometry | Emitted and exact | Additional erasures |
| --- | ---: | ---: | ---: |
| 1 | 573 | 529 | 44 |
| 2 | 582 | 529 | 53 |
| 3 | 582 | 526 | 56 |
| 4 | 585 | 529 | 56 |
| **Total** | **2,322** | **2,113** | **209** |

The artificial service `EF0201`, labelled `DRM IQ TEST`, carries known EVS words in clear packet data. The programme consists of locally generated harmonics, seeded noise and silence. The reference words come from the stock 13.2 kbit/s floating-point EVS encoder before packetization. We changed one bit of the **stored packet CRC** in 12 different packets across the three phases. All other data stayed intact. Dream's file transmitter and receiver share a radio implementation. The independently saved encoder words let us check every bit of the receiver output. The earlier pristine version of this procedural signal had been exercised locally. This study uses the new 12-packet challenge and the public checkout. [Sender products and codec settings](fixture/sender.json) · [Exact changed locations and IQ digests](transmitter-receipt.json)

All 468 packets expected to pass CRC reached the receiver's native MSC output byte-for-byte. Its counter-assignment rules accepted 424 and left 44 unassigned across five groups. The other 12 packets arrived with their deliberately invalid checksums and remained excluded. For example, at counter 16909068 the phase-zero packet carrying the phase tag failed CRC. Eleven intact packets then lacked sufficient anchoring under this receiver's rules. The sender reference identifies their coordinates retrospectively. The single-station receiver did not have that reference. [Native row alignment and cause by group](result/transport-origin.json)

The stock decoder produced 768,000 PCM samples at 16 kHz from the received timeline. Before the first erasure, all 480 words and all their output samples matched. After an erasure, **1,260 of the 1,633 exactly received words** produced at least one sample different from the uninterrupted reference. At slot 540, the first exact word after the first gap, 317 of 320 samples differed. An AM or music reference can establish programme timing, while a sample mismatch alone leaves the current encoded word ambiguous. [PCM comparison](result/pcm.json)

## Real 3205 kHz IQ

The separate on-air run used one locally held-out minute of the November 27 recording. It assigned 21 counters, none in the 15,074-ID prior local inventory. Seven original native groups were complete. At the first, **43873173**, all 60 physical words arrived, with 10,560 directly carried bits and 5,280 carried bits whose clear values remain unknown. There were **zero complete clear EVS words**. The first incomplete group, 43873171, retained all 33 physical octets in 20 slots and none in 40 slots. The receiver used its normal broadcast configuration. The contributor had previously reported aggregate results on the longer recording. [Broadcast IQ and receiver provenance](on-air/input.json) · [Group and partial-word coverage](on-air/coverage.json) · [Exact per-slot fields and alternatives](on-air/score.json)

## Reproduction

The Python scripts use the repository's standard dependencies. `receive.py` requires the finite-input Dream receiver with the public signalling observer patch and a stock floating-point EVS decoder. It accepts the lossless 48 kHz, stereo PCM16 FLAC or WAV, verifies the test service's identity and 728-byte layout, and writes the G.192, decoded PCM, packet flags, word availability and parsed text to a fresh directory. The test profile supplies the first counter and 40-group span. The FLAC is the receiver's only sample input. [Base build and EVS decoder instructions](../../build/README.md) · [Dream signalling observer](../nov28/yokohama-1300/README.md) · [Regenerating the synthetic RF file](transmitter/README.md)

```sh
case_dir=examples/receiver-control
python "$case_dir/receive.py" "$case_dir/challenge-iq48.flac" \
  --dream "$dream_signalling" --decoder "$evs_decoder" --out /tmp/clear-drm-received
python "$case_dir/verify.py" /tmp/clear-drm-received/audio/programme.192 \
  "$case_dir/fixture/sender.192.gz" --transport-mask /tmp/clear-drm-received/receiver/transport-mask.json \
  --negative-controls --out /tmp/clear-drm-verified.json
```

The verifier intentionally exits 1 for the frozen receiver's 209 extra erasures. The report preserves them even when the optional per-packet comparison explains every emitted word. Verifying the committed `result/received.192.gz` uses the same command with `result/transport-mask.json` and requires only Python's standard library. The negative controls reject a one-bit change, a slot rotation, a missing good word and supplying the sender's exact bytes at a required erasure.

To reproduce the audio comparison, decompress `fixture/sender.192.gz` and decode it with the same stock decoder using `-q -no_delay_cmp 16`. Pass the uninterrupted PCM as the last argument to `compare_pcm.py RECEIVED_G192 RECEIVED_PCM REFERENCE_PCM`. Run `trace_transport.py /tmp/clear-drm-received` to reproduce the packet-origin report.

For the original on-air minute, the exact Dream command is in [the reception receipt](on-air/receipt.json). Replay the published native MSC with the following commands from the repository root and a fresh output path.

```sh
field=examples/receiver-control/on-air
check=examples/nov28/clear-evs-controls/iq/check.py
seal=53de32ea561b51e0a678aed216b1ff54f9fd0c6cedc81f96660046e8d9508029
python "$check" freeze "$field/native.msc.bin" /tmp/clear-drm-field
python "$check" score "$field/native.msc.bin" /tmp/clear-drm-field "$seal"
python "$field/coverage.py" /tmp/clear-drm-field --seal "$seal" > /tmp/clear-drm-coverage.json
cmp "$field/coverage.json" /tmp/clear-drm-coverage.json
```

## Damaged packets in on-air recordings

Two channel estimates from the same IQ recovered three physical packets in the 6140 kHz development recording. A second station recorded all three packets byte-for-byte. A further 3205 kHz trial used the frozen receiver on a locally unopened interval and checked its one complete packet proposal against a third demodulation. The reports include the four-position EVS results, the costs of accepting individual bytes from failed packets, and a synthetic case where a unique CRC solution still contains errors. [Independent station comparison](disagreement/README.md) · [Frozen field test](agreed-bytes/README.md)
