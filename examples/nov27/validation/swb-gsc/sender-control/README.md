# A synthetic SWB GSC word with a checkable p24 field

The first 128 physical bits of one stock EVS word predict that the low nibble of payload octet 24 must be **0, 1, 2 or 3**. The sender wrote `83`. This leaves 64 possible octets on the strength of the field alone. The example uses regular SWB AUDIO/GSC with BWE at 13.2 kbit/s, mode octet `6C`. Physical bit 0 is the MSB of that mode octet. Payload offsets exclude it.

From this directory, run the following command with Python 3, NumPy, GCC, the pristine floating-point TS 26.443 source dated 4 November 2021 and its stock encoder.

```sh
python -B check.py --source /path/to/c-code --encoder /path/to/EVS_cod --out replay.json
```

The command regenerates 102.06 seconds of synthetic mono PCM. Pitched harmonics and filtered noise cycle through bandwidth changes. At the transition from a 3.3 to a 6.5 kHz noise cutoff, the final 60 ms includes a gain peak centered at 1.575 kHz. The reference encoder processes all 5,103 words from reset. The selected word is zero-based slot 5102, third in a synthetic four-slot grouping. Its 128-bit prefix and its complete word each appear once in this replay. [Waveform generator](waveform.py) · [Aggregate result](result.json)

The bounded native reader starts PVQ at physical bit 89. Its third large vector index uses a 16-dimensional, five-pulse codebook with 142,544 entries. The upper symbol is 139 and the remaining 10 bits occupy [204,214). Since `142544 − 139 × 1024 = 208`, a legal residual lies in [0,208). The four most significant residual bits are the low nibble of p24, at physical bits 204 through 207. Bits 204 and 205 must be zero. The genuine residual of 195 gives index 142,531.

The verifier records the field before opening the original residual. It finds the same index size, upper symbol and address after the complete sender history, after a cold reset and when the synthetic word's entire suffix after bit 127 is replaced with zeros or ones. The bounded walker copies only the first 128 bits, takes both endpoints of any uncertain arithmetic prefetch, and halts on an ambiguous symbol. It shares the existing source-pinned observer implementation. [Bounded reader](../../late-payload/gsc-control/bounded.py)

For the final check the verifier changes only the low nibble, retaining the other 260 bits. On independent cold runs, all four predicted nibbles pass the specific stock `entry.index < entry.size` check and all twelve others trigger its native error branch. The aggregate result separates this reproducible replay from the exploratory sender-PCM counts. The selected word was the lone positive among 6,013 p24-capable vector-index occurrences in a deliberately tone-emphasized corpus. Its prefix had one occurrence among those 24,576 words. The waveforms share two synthetic onsets, so these counts describe the discovery experiment and cannot estimate a broadcast occurrence rate. [Exact denominators and outcomes](result.json)
