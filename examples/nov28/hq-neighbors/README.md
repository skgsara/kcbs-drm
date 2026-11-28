# What a later EVS word can tell us about an earlier one

On November 28 at 01:25 UTC, the public 7L4IOU receiver in Edogawa recorded 120 seconds of 6140 kHz IQ. We sealed the recording and published the receiver settings and field test before opening it for demodulation. Dream produced 267 MSC records. Zero of the 1,068 candidate packets passed their CRC. The test consequently had no assigned counter, no complete group and no field comparison. The lossless file contains all 5,760,000 original complex sample pairs. [Frozen protocol](protocol.md) · [Receiver commit](https://github.com/skgsara/kcbs-drm/commit/67e3dbff0e9aa85b3fc73da9ce5ff4d5bd008eb7) · [IQ recording](7l4iou-6140-20261128T0125Z-iq48.flac) · [Reception receipt](live-receipt.json)

## Which alternative the signal can reject

A separate frozen 20-second test using a strong November 19 recording received 12 complete groups. No word in that interval had the required preceding `F9` mode. The first complete counter was 43288806. [Four-position result and secondary GSC comparison](airspy-gap/README.md)

The test concerns three consecutive ordinary 13.2 kb/s super-wideband HQ words under continuous stock EVS encoding. Word bits are numbered from zero, most significant bit first. We selected triples using the directly carried mode `F9` in the preceding word, `F8` in the middle word, and the high seven mode bits `1111100` in the following word. We held back the following word's mode bit 7 until scoring. Every triple lies within one complete CRC-checked group.

The middle word's bit 8 distinguishes NORMAL (0) from TRANSIENT (1). The preceding `F9` word signals a nontransient class. A fresh transient in the middle would carry over into the following word. If the held-back bit is 1, the following word is harmonic (`F9`), which excludes a middle transient under the stock rule. If the bit is 0 (`F8`), both middle values remain possible. A gap, encoder reset or change of extension can break the carryover. Exact bit accuracy on the middle P3 and P4 words remains unmeasured.

| Retrospective source | Complete groups | P3 transient excluded / eligible | P4 transient excluded / eligible |
|---|---:|---:|---:|
| Five IQ demodulations | 1,284 | 6 / 16 | 3 / 15 |
| Two contributed receiver archives | 939 | 0 / 1 | 2 / 2 |

For example, on November 19 at counter 43287515, slot 3 (P4), the received successor mode was `F9`. The fixture includes all three received data units from each of the 29 groups with an eligible P3 or P4. The full archive counts and input hashes are in the ledger. [Received data units](eligible-data-units.npz) · [Cases by archive](archive-cases.json)

A separate retrospective check found five P4 words in three November 27 counters where three consecutive modes were all `F8`. In these five cases the mode sequence alone left the middle bit open. A spectral shortening flag in the following text-supported P1 word rules out TRANSIENT under the stock sender. Three of the five flag bits were directly carried in the P1 payload. The variable-length field address still depends on having a supported P1 word. [Received words, scope and reference-code replay](p4-successor/README.md)

## Controls

The stock sender produced 10 triples with a harmonic successor. All 10 had a normal middle word. With an `F8` successor, it produced eight normal middle words and one transient. The latter occurred at slot 425 and shows why the receiver leaves both values open for that sequence. [Original words and encoder events](stock/witnesses.json) · [Stock source and controls](stock/README.md)

In historical P1/P2 words with a text CRC witness for the middle bit, the rule agreed on 19/19 eligible words with an `F9` successor. All 85 comparable words with an `F8` successor also had a zero middle bit. Always predicting zero would therefore agree with all 104 radio labels. The stock control above is where we observed both middle values. [Label coordinates, counts and witnesses](labelled-early-positions.json)

## Replay

From the repository root, run the archive comparison and inspect the stock sender witnesses.

```sh
study=examples/nov28/hq-neighbors
python "$study/check.py" "$study/eligible-data-units.npz"
python "$study/stock/proof.py"
python scripts/project_evs_group.py "$study/eligible-data-units.npz" --counter 43287515 --field-checks
```

To repeat the fresh RF test, point `KCBS_DREAM` at a finite-input Dream build and run these commands in a new output directory.

```sh
python scripts/demod_iq_window.py "$study/7l4iou-6140-20261128T0125Z-iq48.flac" replay/rf --seconds 120 --reception-profile wiener --mlc-iterations 1
python scripts/salvage_msc_packets.py replay/rf/msc.bin --transport-only --out replay/du
gzip -dc "$study/historical-counter-ids.json.gz" > replay/history.json
python "$study/check.py" replay/du/data_units.npz --provenance replay/du/provenance.json --history replay/history.json
```

An independent replay from the released FLAC reproduced the original 195,444-byte MSC output and all four transport files byte for byte. The recording plan was fixed at 01:25:07 UTC, the IQ was sealed at 01:27:10 UTC, and the frozen receiver opened it at 01:27:54 UTC. [Acquisition plan](plan.json) · [Seal](sealed-receipt.json) · [Opening](opening.json) · [FLAC replay hashes](public-flac-replay.json)
