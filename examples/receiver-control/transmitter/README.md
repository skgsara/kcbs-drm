# Generate a DRM IQ file from synthetic MSC frames

`msc_to_iq` takes a file of 728-byte MSC frames in transmission order and produces a stereo 48 kHz PCM16 WAV. Channel 1 carries I and channel 2 carries Q. The generator adds a synthetic service announcement and acquisition and drain guards. It runs offline.

## Build and run

From the repository root, build the pinned Dream console receiver, including its transmitter objects. Link the file generator against those objects, then pass its executable to the benchmark generator. The last command reads the supplied sender template, changes the 12 packet checksums, and writes the IQ FLAC and its receipt to a fresh directory. [Dream build instructions](../../../build/README.md) · [Benchmark generator](../generate.py)

```sh
bash build/build.sh
python3 examples/receiver-control/transmitter/build.py \
  --dream-build build/dream-src --out work/receiver-control-tools
python3 examples/receiver-control/generate.py \
  work/receiver-control-tools/msc_to_iq work/receiver-control-rebuild
```

For other prepared MSC inputs, use `msc_to_iq rows.bin output.wav`. The input file must contain a positive whole number of frames, with no length prefixes. The generator accepts application packet headers and transmitted CRCs exactly as supplied. It constructs packet and data-unit CRCs for its own guard frames.

The build helper reads the compiler flags, libraries and object list from the completed qmake Makefile. It also supports a shadow build with a separate object directory. Pass `--dream-source PATH` when the Makefile does not identify its source tree. The output directory contains `msc_to_iq`, `build.log` and `build.json`. The receipt records the transmitter source digest, Dream revision and module source digests, Makefile digest, linked object digests and executable digest. [Build helper](build.py)

## Signal and timing

The generator feeds each input octet MSB first into MSC stream 0 and fills the spare MSC capacity with zeros. Dream applies channel coding and long interleaving, maps the carriers and pilots, and performs OFDM modulation. The service uses robustness mode B, 10 kHz occupancy, 64-QAM MSC with part B protection level 1, and 16-QAM SDC. The test service ID is `EF0201`, its label is `DRM IQ TEST`, and its data stream carries 179-byte packet payloads with packet ID 0. [File generator](msc_to_iq.cpp) · [Pinned Dream transmitter](https://github.com/mmjee/dream-patched/blob/895658c567d2fd47d6006065e75abf0c3157783f/src/DrmTransmitter.cpp)

Each frame lasts 400 ms and contributes 19,200 complex samples. For an input of *N* frames, the WAV contains (30 + *N* + 24) × 19,200 complex samples. The leading guard lasts 12 seconds and the trailing guard lasts 9.6 seconds. Their synthetic counters begin at `0x0F800000` and `0x0F810000`, respectively. Use the input's own counters for scored rows. The receiver can have acquisition and interleaver delays, so a decoded MSC callback index alone cannot locate a source frame in the WAV.
