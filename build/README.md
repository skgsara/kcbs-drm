# Build the KCBS-instrumented Dream receiver

Dream demodulates a DRM IQ recording and writes its Main Service Channel (MSC) frames. The Python tools check packet and data-unit CRCs, recover supported text and pass recovered audio frames to the separately built 3GPP EVS decoder. Existing MSC dumps can go straight to the CRC step below.

## Build on Ubuntu or Ubuntu in WSL

Run these commands from the repository root in a Linux shell.

```bash
bash build/build.sh
test -x build/dream-src/dream
```

The script installs the compiler, Qt 5 qmake and development libraries through APT. Ubuntu provides `libfdk-aac-dev` in its multiverse component. If the build dependencies are already installed, use `bash build/build.sh --no-install`. Set `JOBS` to change the default of four parallel compiler jobs.

The script fetches revision `895658c567d2fd47d6006065e75abf0c3157783f` of MMJEE's Dream fork, adds the project’s MSC and station-information hooks, and applies the finite-file input patch. It configures `console sound sndfile` for a headless receiver with WAV input. With `DREAM_FILE_OFFLINE=1` the receiver reads once at processing speed and exits at end of file. [MMJEE’s Dream fork](https://github.com/mmjee/dream-patched/tree/895658c567d2fd47d6006065e75abf0c3157783f) · [Offline patch](dream-offline-input.patch) · [Third-party notices](../docs/NOTICE.md)

The Python tools honor `KCBS_DREAM` first, then look in `work/dream-build/dream` and `build/dream-src/dream`. To select this exact build when both exist, run `export KCBS_DREAM="$PWD/build/dream-src/dream"`. Windows-hosted Python runs the Linux executable through the Ubuntu WSL distribution. It accepts an absolute WSL path in `KCBS_DREAM` and also supports the older `/root/kcbs/dream-src/dream` installation. Running both the build and Python commands in the same Ubuntu shell uses the Linux path rules.

## Check the receiver on a bundled capture

Install the [Python requirements](../requirements.txt) in your Python environment. This example demodulates the first 45 seconds of an included KiwiSDR IQ recording. Give each run a fresh output directory.

```bash
python scripts/demod_iq_window.py \
  recordings/hl5ntr.ddns.net_2026-03-16T19_49_43Z_3205.000_iq.wav \
  work/dream-check --seconds 45
python scripts/salvage_msc_packets.py work/dream-check/msc.bin --out work/dream-check/crc
```

`work/dream-check/dream.log` records reception and end of input. The adjacent `manifest.json` records the sample range, exit code and output size. Inspect `work/dream-check/crc/report.json` for `crc_good_data_units` and `salvaged_complete_groups`. Reception determines how many pass. For signed 8-bit IQ, use the same demodulator with the CS8 file and its complex sample rate, for example `--sample-rate 912000`. [Demodulator](../scripts/demod_iq_window.py) · [Packet salvage](../scripts/salvage_msc_packets.py)

For an existing 48 kHz stereo IQ WAV, the console receiver can write the dump directly. Supply the path to your recording in `IQ48`.

```bash
mkdir -p work/direct-dump
DREAM_FILE_OFFLINE=1 KCBS_DUMP_MSC="$PWD/work/direct-dump/msc.bin" \
  KCBS_ID="$PWD/work/direct-dump/service.txt" \
  build/dream-src/dream -c 6 --sigsrate 48000 -m 1 -f "$IQ48"
```

KCBS-2 signals a data service. `KCBS_DUMP_MSC` selects its dump file. The separate audio-service hook uses `KCBS_DUMP_AUD` if Dream routes a service through its audio decoder. Without overrides, the hooks write `kcbs_msc.bin` and `kcbs_aud.bin` respectively when called. The optional `KCBS_ID` log records service and multiplex signalling.

On little-endian systems each dump record starts with the four-byte payload length. In the bundled capture that length is 728 bytes, comprising four 182-byte packets. Each packet’s final two bytes hold its big-endian CRC over the preceding 180 bytes. The salvage tool also checks the CRC of the reassembled 716-byte data unit.

## Build EVS for audio

Obtain the floating-point C source for 3GPP TS 26.443 and place its `lib_com`, `lib_dec` and `lib_enc` directories immediately under `work/ref/evs/src/c-code/`. From the repository root, build into a new output directory with the command below. The generated decoder is `work/evs_gcc_independent/EVS_dec`. [Official ETSI reference archive](https://www.etsi.org/deliver/etsi_ts/126400_126499/126443/19.00.00_60/ts_126443v190000p0.zip) · [Codec build script](../scripts/build_evs_gcc_independent.py) · [Capture and playback commands](../README.md)

```bash
python scripts/build_evs_gcc_independent.py --out work/evs_gcc_independent
```
