# 12:28 UTC simultaneous reception on 3205 and 6140 kHz

The primary receiver in Yokohama produced zero CRC-valid physical packets on 3205 kHz. The primary counter is therefore **null**. The independent Edogawa receiver on 6140 kHz supplied 52 complete chronological groups. Both receivers recorded 5,760,000 complex samples over 120 seconds on November 28. [Selection protocol](protocol.json) · [Source hashes and station clocks](sealed-sources.json) · [Comparison](comparison.json)

| Receiver | CRC-valid physical packets | Complete native data units | Assigned counters | Complete chronological groups |
|---|---:|---:|---:|---:|
| Yokohama, 3205 kHz | 0/1,152 | 0/288 | 0 | 0 |
| Edogawa, 6140 kHz | 769/1,172 | 176/293 | 64 | 52 |

Edogawa supplied 688 coordinate-assigned packets and 167 assigned full data units. Its 64 counters were absent from the 14,747-ID archive inventory, which was compiled after recording began and before review of the outcome. Six Yokohama packets lacked a station timestamp. One adjacent Edogawa timestamp differed from the nominal sample clock by 21,336 ns. [Yokohama receipt](yokohama-native.json) · [Edogawa receipt](edogawa-native.json) · [Historical inventory](history/freeze.json)

The secondary check takes only the Yokohama mode byte and compares its EVS field prediction with payload octet 4 at Edogawa. Yokohama supplied zero mode bytes, so this recording has zero eligible predictions. There is no complete-group audio score. [Field protocol](direct-fields-protocol.json) · [Counts at all four positions](fields.json)

## Replay

The FLAC files preserve the two signed 16-bit I/Q channels at 48 kHz. Their packet-time CSVs accompany the samples. The distribution receipt includes the original WAV and decoded PCM hashes. [Yokohama IQ](iq/yokohama-3205khz-iq48.flac) · [Edogawa IQ](iq/edogawa-6140khz-iq48.flac) · [Distribution receipt](iq/verification.json)

Use the receiver build and settings in the protocol to repeat demodulation from sample zero. To repeat just the field comparison from the two CRC-checked transport snapshots, run from the repository root.

```sh
case_dir=examples/nov28/dual-iq-1228
python "$case_dir/score_fields.py" "$case_dir/yokohama-packets.npz" "$case_dir/edogawa-packets.npz" --primary none > /tmp/dual-1228-fields.json
cmp /tmp/dual-1228-fields.json "$case_dir/fields.json"
```
