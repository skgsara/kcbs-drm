# Can an exact audio reference identify the original EVS words?

We constructed 16 different EVS streams that reproduce the **same 441,600 signed PCM samples** published by 3GPP. Each stream lasts 55.2 seconds and uses the same 22 directly observable octets at every one of its 2,760 frame positions. All 16 passed a byte-for-byte comparison against the complete official 8 kHz decoded output. This provides a controlled example where even an exact digital recording of the output cannot distinguish the original encoded bytes. [Combinations, stream hashes and output hashes](playback.json)

## Identical source audio in two reference encoders

3GPP TS 26.444 supplies sender vectors for fixed-point and floating-point reference implementations. We retrieved the 13.2 kbit/s clean and two noise cases in each of narrowband, wideband and super-wideband. For each of the nine conditions we compared every byte of the two original encoder inputs (`.INP`), checked their SHA-256 hashes, and aligned the two official G.192 sender outputs (`.COD`) by frame index. This gives 12,480 paired frames. The projection keeps the mode octet and the 21 payload octets carried directly in our broadcast receiver. [Official source-file receipts and measured counts](official.json) · [Fixed-point archive](https://www.3gpp.org/ftp/Specs/archive/26_series/26.444/test_sequences/26444_ce0_da0_e60_f40_g50-TestSeq_BASOP_26442.zip) · [Floating-point archive](https://www.3gpp.org/ftp/Specs/archive/26_series/26.444/test_sequences/26444_g50-TestSeq_Float_26443.zip)

Of those aligned frames, 2,140 had identical complete words. A further **33 had all 22 observed octets in common and differed elsewhere**. In six of the 33, both immediate neighbours were identical complete words. In the strongest example, frame 1960 of the narrowband clean sequence, the preceding 12 and following 12 complete words matched. The target words differed only at bit 249, where payload octet 30 was `98` in the floating-point word and `D8` in the fixed-point word. Each of the 33 pairs has at least one differing projected observation elsewhere in its aligned 60-word group where that full group is available. This experiment isolates uncertainty about the encoding implementation even with identical encoder input audio. [Context and group coverage](official.json)

## What the decoder could distinguish

For each of the 33 aligned differences we took its original, unmodified floating-point sender word and substituted it at the same slot in the fixed-point stream. All other words were identical. We decoded both streams from reset through end-of-file at their native output rate. The unmodified fixed stream had to match the official fixed-point `.OUT` file before testing the substitution. Twenty-nine substitutions changed at least one sample. **Four reproduced the entire official output exactly.** All four occurred in ordinary narrowband speech, at slots 1648, 1664, 1702 and 1743, with mode octet `E8`. [Per-slot playback comparisons](playback.json) · [Checker](playback.py)

We then tested every combination of those four complete-word substitutions. All 16 coded-stream SHA-256 hashes were distinct and every decoded output had SHA-256 `297b3b1938193937b6de8b657d64e57127eb1bf1f7a851a55412b1642e18dd01`. These combinations are controlled decoder inputs assembled from two genuine encoders' words. The official archives establish which words the two encoders actually emitted. As a positive control, the substitution at slot 891 of the same file changed 616 samples at 8 kHz. We also checked each of the four substitutions separately and all four together at 48 kHz with the fixed-point decoder, and at 8 and 48 kHz with the floating-point decoder. They left every sample unchanged relative to each decoder's own output. [Native-rate combinations and additional decoder checks](playback.json)

The two changed bits in each word are flags about pulse presence in the highest two bands of a previous eligible HQ frame. Their transmitted values were `00` and `11`. Instrumenting the stock floating-point decoder showed that the flags changed the calculated energies. In these four cases both calculations still allocated zero bits to the top two bands and produced identical quantized spectra. This explains how meaningful encoder fields can differ without changing playback. [Field locations, native decoder trace and its limits](field-trace/README.md)

A separate stock-encoder control shows how much a different bit can matter. Two synthetic signals used the same first five complete words. At slot 5, exactly one of 264 encoded bits differed, at the most significant bit of payload byte 3. All 22 projected octets still agreed. In the next 20 ms output block at 16 kHz, the RMS level went from 122.75 to 347.17 PCM counts, a 9.03 dB difference. The six subsequent encoded words also differed. Two builds reproduced the full encoded streams and the 8, 16, 32 and 48 kHz playback measurements. This is a digital amplitude measurement on an impulse. [Stimulus and replay](pulse.py) · [Four-rate results](pulse.json)

The earlier on-air primary, counter 43872587, had neither `E8` nor the impulse example's `FA` among its 60 mode octets. These tests supply no new clear bit for that group. They show why the receiver reports byte accuracy and audio agreement separately. [Original on-air per-slot report](../agreed-bytes/field/group-fields.json.gz)

## Reproduction

Run these commands with Python and NumPy from the repository root. Set `fixed_dec` to the TS 26.442 fixed-point reference decoder, and `float_enc` and `float_dec` to the TS 26.443 floating-point reference executables. The first two commands fetch the required original members from the public ZIPs into a local cache. The replay publishes only measurements and hashes. [Reference build and test-vector documentation](../../nov28/clear-evs-controls/README.md)

```sh
d=examples/receiver-control/reference-ambiguity
cache=$(mktemp -d)
python "$d/official.py" "$cache" --fetch --check > /dev/null
python "$d/playback.py" "$cache" --fixed-decoder "$fixed_dec" --float-decoder "$float_dec" --fetch --check > /dev/null
python "$d/pulse.py" --encoder "$float_enc" --decoder "$float_dec" --expect "$d/pulse.json" --out /tmp/evs-pulse-check.json
```
