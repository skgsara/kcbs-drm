# Why the stock SWB INACTIVE encoder emits 1100

Both reference encoders emit **1100 at word bits 40–43** on their ordinary EVS Primary Mode 1, 13.2 kbit/s super-wideband GSC INACTIVE/BWE path (mode octets `74`–`77`). Counting the mode MSB as bit zero, these four bits form the high nibble of payload octet 4. The encoder chooses noise index 6 and two subframes. Their order on the wire matters.

| Step in the reference encoder | TS 26.443 floating-point source | TS 26.442 fixed-point source |
| --- | --- | --- |
| At 13.2 kbit/s the five-bit signalling index 14 denotes non-channel-aware SWB INACTIVE. BWE adds a one-bit extension selector and takes 1.6 kbit/s, leaving an 11.6 kbit/s core. End- and mid-frame LSFs take 31 + 2 bits. The attack flag occupies b39. | `lib_com/rom_com.c` 70–78, 109, 132; `lib_enc/decision_matrix_enc.c` 210–217, 274–275, 484–494; `lib_enc/gs_enc.c` 68–77 | `lib_com/rom_com_fx.c` 55–63, 94, 117; `lib_enc/decision_matrix_enc_fx.c` 270–282; `lib_enc/gs_enc_fx.c` 76–86 |
| The classifier resets noisy speech for this frame. Enabling it requires active VAD. In Mode 1 the later zero-VAD INACTIVE selection explicitly sets the noise level to SP3. BWE also requires noisy speech to be clear. | `speech_music_classif` in `lib_enc/speech_music_classif.c` 109, 158–171; `pre_proc` in `lib_enc/pre_proc.c` 457–485 | `speech_music_classif_fx` in `lib_enc/speech_music_classif_fx.c` 184–209; `pre_proc_fx` in `lib_enc/pre_proc_fx.c` 656–692 |
| INACTIVE skips the dynamic noise quantizer. At this core rate the encoder writes SP3 − SP0 = 14 − 8 = 6 in three bits. Independently, INACTIVE selects two subframes and writes a zero flag. | `encod_audio` in `lib_enc/gs_enc.c` 94–118, 160–187; `lib_com/cnst.h` 1376–1380 | `encod_audio_fx` in `lib_enc/gs_enc_fx.c` 103–135, 182–204; `lib_com/cnst_fx.h` 1359–1363 |
| The transmitter stores indices by ID. `IND_NOISE_LEVEL` precedes `IND_HF_NOISE`; the G.192 writer traverses this order and emits the MSB first. The decoder consumes three noise bits followed by one subframe bit. | `lib_com/cnst.h` 242–245; `push_indice` and `write_indices` in `lib_com/bitstream.c` 158–187, 467–489; `decod_audio` in `lib_dec/gs_dec.c` 53–59, 79–105 | `lib_com/cnst_fx.h` 202–205; `push_indice_fx` and `write_indices_fx` in `lib_com/bitstream_fx.c` 154–188, 489–511; `decod_audio_fx` in `lib_dec/gs_dec_fx.c` 102–129 |

Previous activity can postpone the first eligible frame. A changed ACELP frame length, a previous HQ/TCX core, or a switch from frequency-domain comfort noise can first force a TRANSITION frame. Once the ordinary INACTIVE branch runs, it overwrites the previous noise level. The separate INACTIVE assignments for rates above 24.4 kbit/s, Mode 2, and a switch to TCX20 take other coding paths. Channel-aware 13.2 kbit/s signalling has separately enumerated indices. SWB AUDIO can transmit a noisy-speech bit and dynamically quantize noise, and SID/no-data frames have their own structures. The gate above excludes all of these. [Reference source archives](#source-archives)

These branch distinctions can be checked in floating-point `lib_enc/pre_proc.c` 352–369, 457–505, 555–602, `lib_enc/io_enc.c` 515–517, 542–545 and `lib_com/rom_com.c` 70–81. The corresponding fixed-point INACTIVE assignments are in `lib_enc/pre_proc_fx.c` 688, 699, 707 and 822. A broadcaster can use another encoder or configuration. Record a received disagreement as evidence. A decoder can consume other noise-index and selector values, so successful playback does not identify the emitter.

## Reproduce on clear PCM

The generator writes 2.4 seconds of signed 16-bit mono PCM at 32 kHz. The first case is all zero. The second begins with 50 frames of a 1 kHz integer square wave at levels ±4096, followed by 70 silent frames. Each case and encoder starts a new process with `-q -no_delay_cmp -max_band SWB 13200 32`. The script reads the complete G.192 output and retains the original 20 ms slot indices. It requires Python and NumPy. [Generator and check](check.py) · [Complete histograms and SHA-256 digests of PCM, executables and G.192 outputs](expected.json)

| Input | First eligible slot (zero-based) | Fixed-point C / eligible | Floating-point C / eligible |
| --- | ---: | ---: | ---: |
| Digital silence | 3 | 117 / 117 | 117 / 117 |
| Square wave followed by silence | 72 | 48 / 48 | 48 / 48 |

The final 70 input frames in the two stimuli are byte-for-byte identical digital zero, totaling 44,800 samples. Comparing the same frame index **within each encoder**, 0 of 70 complete 264-bit words matched. At slots 72–119, both histories yielded the same mode octet `74` and nibble `C` in every frame. All 48 complete words still differed, in both implementations. At slot 72, after 440 ms of identical zero input, the two fixed-point words differed in 17 bits and the two floating-point words differed in 80. Knowing the PCM of the silent interval therefore leaves multiple possible encoded words when the preceding signal is unknown. The receipt includes hashes of the common PCM suffix and the first differing same-mode words.

Both encoders emitted only mode `74` among eligible frames in these controls. All runs had 120 words. From the repository root, run the following command with the two executables from your builds. Local executable hashes depend on the build. Each output stream has its own reference digest.

```sh
python examples/nov28/clear-evs-controls/stock-inactive/check.py \
  --fixed /path/to/fixed/EVS_cod --float /path/to/float/EVS_cod > results.json
```

## Source archives

The ETSI V19.0.0 packages contain the following ANSI C distributions. All 423 fixed-point and 406 floating-point C/header files compared in the local source trees matched the corresponding official archive bytes.

| Distribution | Outer ZIP SHA-256 | Inner ANSI C ZIP SHA-256 |
| --- | --- | --- |
| [TS 26.442 fixed-point](https://www.etsi.org/deliver/etsi_ts/126400_126499/126442/19.00.00_60/ts_126442v190000p0.zip) | `17a167277c41d4d5267f4d2d0e4e20f847cb092c577491c04056b1116d3086d5` | `c2621dbd02969e6d2cbe20c8c34068d83604f5bc7bccf691110b58d198987e9f` |
| [TS 26.443 floating-point](https://www.etsi.org/deliver/etsi_ts/126400_126499/126443/19.00.00_60/ts_126443v190000p0.zip) | `f3e0928f917fe67a620a37578757b0db00e0ca216481a96a99ea8ff5e3b8271b` | `1f7faaf22e77320d65bd295cd508e83bcf1056b86b5f7b7b685c46661e960c2d` |
