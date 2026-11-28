# 6140 kHz blind reception at 13:47 UTC, November 28

The Edogawa receiver had **no complete group to select**. It located three CRC-valid packets at counter **43949404**, phase 0. All 16 mode octets available at assigned coordinates fell outside the SWB GSC AUDIO rule. Both prediction branches had zero eligible slots, and the preselected zero-branch control was empty. This run gives no estimate of bit-40 accuracy or complete-word accuracy. The receiver, input, selection and comparison with a constant-one baseline were published before acquisition. [Protocol at freeze](https://github.com/skgsara/kcbs-drm/blob/b9823848190fcc4e318ee7bc7c940faeea8edfb9/examples/nov28/edogawa-audio-branch/protocol.md) · [Primary result](results/primary.json) · [Field score and both denominators](results/audio.json) · [Seal](results/seal.json)

| Station | Original IQ pairs at 48 kHz | Duration | Packets passing CRC and header checks | Complete native data units | Assigned complete groups |
|---|---:|---:|---:|---:|---:|
| 7L4IOU Edogawa, primary | 4,206,480 | 87.635 s | 26/444 | 4 | 0 |
| JL1EDU Yokohama, independent comparison | 5,760,000 | 120.000 s | 0/432 | 0 | 0 |

The primary connection closed 32.365 seconds short of its sample target. Its station timestamps cover 13:47:32.226972–13:48:59.861984 UTC with all packet times present. The peer's estimated interval is 13:47:31.499306–13:49:31.499289 UTC. The first 1,920 peer samples (40 ms) precede its first timestamp. We sealed the primary results at 13:49:51.137723 UTC and started peer demodulation at 13:50:12.547949 UTC. [Primary clock and error receipt](results/edogawa/source-seal.json) · [Peer clock receipt](results/yokohama/sealed.json) · [Peer receiver result](results/yokohama/peer-transport.json)

## What the three packets establish

Edogawa MSC row 27 supplied phase-zero packets 0, 1 and 3 for counter 43949404. The counter was absent from the 14,955-ID inventory. The following supplementary projection accounts for all 15 slots at each position. Its directly carried bits come from a single receiver. The independent station supplied zero bits at these coordinates.

| Position | Directly observable bits | Carried bits with unresolved clear values | Bits without packet receipt | Complete clear words |
|---|---:|---:|---:|---:|
| 1 | 680 | 336 | 2,944 | 0/15 |
| 2 | 704 | 352 | 2,904 | 0/15 |
| 3 | 656 | 328 | 2,976 | 0/15 |
| 4 | 528 | 264 | 3,168 | 0/15 |
| Total | 2,568 | 1,280 | 11,992 | 0/60 |

At 13 slots, the stock TCX previous-core rule predicts a one at physical word bit 8 and excludes zero conditional on the codec rule. The clear target is unavailable at every one of those slots. Each stays in the unresolved column. [Per-slot alternatives, erasures and source bits](results/comparison/partial-43949404.json)

Four complete Edogawa units at native rows 25, 28, 29 and 32 passed their own CRCs. They carried phase tags 1, 1, 2 and 2 respectively. No counter could be assigned to them under the frozen receiver, and the peer supplied no matching unit. A separate inspection of their 80 mode octets found four `FD`, 13 `FE` and 63 `FF`. None qualified for the AUDIO check. [Native row and peer comparison](results/comparison/supplementary-native-and-direct-peer.json) · [Modes by native row](results/comparison/unassigned-direct-mode-audit.json)

## Reproduce the result

The two lossless FLAC files restore the exact original stereo PCM16 WAV files, including their headers. The recordings directory includes the original per-packet timing CSVs and a hash for each source. A fresh replay from the Edogawa FLAC reproduced the MSC, packet archive, data-unit archive and both sealed score files byte for byte. [Edogawa IQ](iq/edogawa-6140khz-iq48.flac) · [Yokohama IQ](iq/yokohama-6140khz-iq48.flac) · [Restore commands](iq/RESTORE.md) · [Recording hashes](iq/verification.json) · [Replay hashes](iq/reproducibility.json)

The pinned RF command and Dream executable digest are in the [receiver plan](receive-plan.json). To reproduce the sealed field reports directly from the archived MSC and packet inputs, run the following from the repository root. Write the field score to a fresh path.

```sh
case=examples/nov28/edogawa-audio-branch
source_dir="$case/results/edogawa"
python "$case/primary.py" "$source_dir/msc.bin" "$source_dir/transport" > /tmp/edogawa-primary.json
python "$case/score.py" "$source_dir/transport/packets.npz" --repo . --out /tmp/edogawa-audio.json
cmp /tmp/edogawa-primary.json "$case/results/primary.json"
cmp /tmp/edogawa-audio.json "$case/results/audio.json"
```
