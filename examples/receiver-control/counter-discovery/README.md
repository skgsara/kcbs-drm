# Finding clear test groups from IQ alone

The frozen receiver found **all 10 intact group occurrences** in a new file-only transmission of the declared-clear EF0201 service. All **600 supplied EVS words** agreed with the separately saved stock encoder output, 150 words at each of the four positions. The sender emitted 11 group occurrences in total. One contained a deliberately damaged packet checksum, and the receiver withheld all 60 slots of that group in complete-group mode. [Results by counter and position](score.json) · [Sender ledger](sender.json)

We used the previously published encoder words in a new order of transmitted counters. The receiver had no starting counter, group count, sender ledger or reference audio. Starting at 4,294,967,289, it followed the rollover from 4,294,967,295 to 0, withheld counter 1, kept a second occurrence of 4,294,967,292, and then emitted counter 2. The two matching occurrences of 4,294,967,292 start at native MSC rows 39 and 57. The catalog also identified 15 complete transmitter guard groups and wrote no audio words for them. [Native catalog, gzipped JSON](catalog.json.gz)

The receiver and [protocol](protocol.md) were [frozen before generation](https://github.com/skgsara/kcbs-drm/commit/8c8eddb05aa1c876a5cbc4eb223ee385e4b24a26). The sender then chose a seed and committed to the IQ and sender ledger by SHA-256. We [sealed the receiver output](receiver-seal.json) before opening that ledger. Regeneration from the released seed reproduced the entire original WAV and sender G.192 file byte for byte. On the earlier 40-group development fixture, discovery produced 28 intact groups with 1,680 exact words. The existing scored-timeline mode reproduced its original receiver hashes and 2,113 words, including those recovered from incomplete groups.

## Reproduce from the recording

The [lossless IQ recording](iq48.flac) contains all 1,670,400 original stereo PCM16 I/Q sample pairs at 48 kHz, lasting 34.8 seconds. Its SHA-256 is `aefb03b842162624e4d8bbd4749e13d82cce9749e0e78460378dd6cdf2d95046`. Use the [signalling-enabled finite-file Dream build](../../nov28/yokohama-1300/README.md) with SHA-256 `ab62ff02da57356f27bfe4f64ae9ed62a3c48a129378d49438008f0272e29467` to reproduce the receiver catalog. Set `dream_signalling` to its path. The following commands run from the repository root. The receiver invocation takes only the IQ as observed data. The sender file is opened by the subsequent scorer.

```sh
d=examples/receiver-control/counter-discovery
out=$(mktemp -d)
python examples/receiver-control/receive.py "$d/iq48.flac" --discover --dream "$dream_signalling" --out "$out/receiver"
python "$d/holdout.py" score "$d/sender.json" "$out/receiver/groups/catalog.json" \
  --truth-sha256 dccb8e7960e6a014b82ac815aebd0104a211d7cbf7faab6089adfcd2d3fd023f \
  --catalog-sha256 2d2700f10a1b94bc39eb341729ae289efd54d77f9ef6bca6a019ee23d2bc5c78 > "$out/score.json"
cmp "$out/score.json" "$d/score.json"
```

To regenerate the transmitter output, build the [file-only modulator](../transmitter/README.md), then run `holdout.py generate MODULATOR NEW_DIRECTORY --seed SEED` with the seed from the [sender ledger](sender.json).

The catalog uses native row adjacency and the received phase tags. If a demodulator silently omitted a whole three-row cycle, the phase tags alone would leave that gap ambiguous. On the previously examined Yokohama broadcast, the shared FAC/SDC check identified service A00002 and stopped the clear-test export before it wrote any EVS words. The bit-exact result above applies to EF0201. [Broadcast service check](on-air-service-check.json)
