# A received packet independently verified at two stations

A single four-iteration Dream pass on Edogawa’s previously published 12:32 UTC IQ corrected five bits in one physical packet. Three unchanged packets in the same row establish its correspondence to the one-iteration baseline. The transmitted CRC stayed `14A1`. The computed CRC changed from `99E8` to `14A1`. Yokohama independently received the exact corrected 182-byte packet. The two directly readable EVS fields affected were P3 payload byte 31 at slot 22 (`19` to `1F`) and the P4 mode at slot 23 (`88` to `F8`). [Native rows, bytes and peer verification](wire-change.json)

At counter **43945704**, the correction allowed assignment of eight new packet coordinates. Seven of those wires had already passed their physical CRC in Edogawa’s original file. All eight newly assigned wires and both newly assigned 716-byte data units matched Yokohama. Across the recording, Edogawa retained all 288 previously assigned packets and 67 complete data units. Its total rose to 296 packets, 69 data units and 18 complete groups. [Edogawa decisions sealed before peer scoring](https://github.com/skgsara/kcbs-drm/commit/1892b0aed6e07f12baf16c440f923abbe944a447) · [All peer comparisons](peer.json)

| Group 43945704, each of P1–P4 | Received slots | Directly readable bits | Received bits with unresolved clear values | Missing bits |
|---|---:|---:|---:|---:|
| Edogawa, one iteration | 5 | 880 | 440 | 2,640 |
| Edogawa, four iterations | 15 | 2,640 | 1,320 | 0 |

Both stations supplied all 12 wire packets in this group. The three transmitted data-unit CRCs were `600B`, `867E` and `2952` in phase order. Phase zero was already complete on Edogawa. All 60 slots now have their 33 on-air octets. Each has 88 unresolved clear bits, leaving zero complete clear EVS words.

## Replay

From the repository root, set `KCBS_DREAM` to the finite-input Dream binary with SHA-256 `1e398433affbe71e3bdbc30171e9c770ddd3a622c0fe1577b3f3837c3fa07a26`. Use a new directory for `work`. The prediction and comparison stages use original accepted packet bytes at recorded native row indices. [Frozen conditions](../erasure-benchmark/protocol.md) · [Original IQ hashes and receiver settings](../../same-6140-1232/iq/replay.json)

```sh
case_dir=examples/nov28/same-6140-1232
trial=examples/nov28/clear-evs-controls/transport-mlc4
work=$(mktemp -d)
python scripts/demod_iq_window.py "$case_dir/iq/edogawa-6140khz-iq48.flac" "$work/rf" \
  --start 0 --seconds 90 --reception-profile wiener --mlc-iterations 4
cmp "$work/rf/msc.bin" "$trial/edogawa-mlc4-msc.bin"
python "$trial/check.py" seal "$work/rf/msc.bin" "$work/decisions.json.gz"
python "$trial/check.py" score "$work/rf/msc.bin" "$work/decisions.json.gz" --out "$work/peer.json"
python "$trial/wire_change.py" "$work/rf/msc.bin" --out "$work/wire-change.json"
cmp "$work/peer.json" "$trial/peer.json"
cmp "$work/wire-change.json" "$trial/wire-change.json"
```
