# 3205 kHz DRM and 3250 kHz AM reception, November 28 at 16:57 UTC

Yokohama's JL1EDU recorded 150 seconds of IQ at 3205 kHz. The frozen receiver reached end of file and produced zero MSC rows. There were zero packet CRC trials and no counter, primary, partial control or EVS word to score. The executable exposed no FAC or SDC CRC count or service ID in this pass. We recorded the receiver settings before acquisition. [Receiver protocol](receiver-protocol.json) · [Result](receiver-result.json) · [Receiver log](receiver.log) · [Group selection](group-seal.json) · [Fields](group-fields.json)

Edogawa's 7L4IOU recorded 120 seconds at 3250 kHz after its initial connection closed at 1.0675 seconds. The conventional AM envelope contains changing pitched audio. The carrier was about 1.5 Hz above nominal. The two stations' **directly timestamped** intervals overlapped for **92.4730215 seconds**, from 16:58:41.266788754 to 17:00:13.739810254 UTC. A backward AM timestamp step of 21,094 ns is counted once. Each acquisition started with 60 ms of IQ lacking station timestamps. All samples and packet timestamps were retained. [IQ and timing files](https://github.com/skgsara/kcbs-drm/tree/fc1cb68ceb10cabcdf7435603239fa3856a2e811/pilot-1657) · [3250 AM audio](https://raw.githubusercontent.com/skgsara/kcbs-drm/fc1cb68ceb10cabcdf7435603239fa3856a2e811/pilot-1657/3250-am.wav) · [Reception and hashes](recordings.json) · [AM measurements](am-measurements.json)

The programme comparison produced no score. The longest uninterrupted overlap was 50.873 seconds, and no received DRM mode bytes were available. The separate online KCBS-2 listening feed returned HTTP 403 and yielded zero samples. The earlier field test of this comparison method used an independently confirmed AM simulcast. [Programme comparison](programme-test.json) · [Timing rules](programme-protocol.md) · [Stream availability](stream-access.json) · [Earlier positive control](../four-frequency/member-100239/README.md)

After sealing the digital result, we tested for the repeated guard interval in DRM Mode B. At the 3205 kHz center, **zero of 15 ten-second blocks** passed. Four other channel centers within the recording also yielded zero detections. The same detector passed **12 of 12 blocks** on an earlier 3205 kHz recording with verified packets and zero of 75 noise-control blocks across the five centers. This bounds the result to the sampled time, receiving site and detector sensitivity. [Detector rule](rf-check/protocol.txt) · [Block scores](rf-check/results.json)

## Reproduction

Download the recordings from the data branch. Its README restores a canonical PCM WAV from a FLAC. From the repository root, with `KCBS_DREAM` set to the executable identified in the receiver protocol, run these commands in fresh output locations. The first accepts the IQ FLAC directly. The second expects the restored WAV named `yokohama-3205.wav` to reproduce the recorded source-file identity as well as the same samples.

```sh
python scripts/demod_iq_window.py jl1edu-3205.flac receiver-3205 --seconds 150 --reception-profile wiener --mlc-iterations 1
python examples/nov28/paired-3250-1657/rf-check/check.py yokohama-3205.wav examples/receiver-control/agreed-bytes/field/3205kHz-121122-0-120s-iq12.flac cp-3205.json
```

The follow-up captured both channels on a single receiver clock at 6100 and 6140 kHz. [Common-clock reception](../common-clock-6122/README.md)
