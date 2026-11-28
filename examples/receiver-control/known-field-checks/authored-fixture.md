# Two EVS field checks on an authored radio transmission

The stock receiver recovered enough mode information to forecast one TCX20 bit in 252 words. All 252 matched the independently saved encoder output, including eight zero bits. A constant-one forecast matched 244. The SWB ACELP transition rule restricted the two-bit field in 39 words. All 39 original pairs were within the predicted set. Only three of those sets fixed the complete pair. [Forecast sealed before scoring](forecast.json.gz) · [Machine-readable score](score.json)

| Authored IQ control | P1 | P2 | P3 | P4 | Total |
|---|---:|---:|---:|---:|---:|
| TCX b8 matches / forecasts | 52/52 | 68/68 | 71/71 | 61/61 | 252/252 |
| Constant b8 = 1 matches | 52 | 63 | 68 | 61 | 244 |
| Transition pair within a restrictive set | 13/13 | 10/10 | 8/8 | 8/8 | 39/39 |
| Constant 01 equals the original pair on those slots | 3 | 0 | 1 | 3 | 7 |

Among 63 transition forecasts, 3 admitted one pair, 10 admitted two, 26 admitted three, and 24 admitted all four. Together they excluded 55 alternatives to the sender's actual pair. The rule fixed b8 in 13 words and b9 in three. All 16 individual bits matched, versus 15/16 for the corresponding bits of constant 01. Each baseline uses the same eligible coordinates as the rule it accompanies.

Shifting only the sender labels backward and forward by one slot gave TCX matches of 226/252 and 231/249. The restrictive transition sets gave 19/37 and 30/37. Each shift stops at the 60-slot group boundary. Adjacent words can have similar field values, so agreement can survive a wrong offset.

The uninterrupted sender had 275 eligible TCX words and 72 transition words. The stock receiver lacked the current mode in 23 and nine of those respectively. At counter 16909074, phase 1, cycle 4, P2 (group slot 37), packet 2 was missing. The preceding P1 word became an erasure, while its F8 mode remained available at DU offset 6 in packet 0. Together with the current FD mode it predicted the actual b8 value of one. Hiding that predecessor mode caused an abstention even though an earlier mode survived at slot 32.

## Reproduction

Run these commands from the repository root with the repository's Python dependencies. Use a fresh output directory. The first route starts with the stock native MSC produced from the synthetic IQ and checks the original packet snapshot digest. To include the radio demodulator, run the documented clear-fixture `receive.py` command on `challenge-iq48.flac` and supply its `receiver/packets.npz` to the same forecast command. Both routes reproduced the same compressed ledger byte for byte. [Raw IQ receiver command and dependencies](../README.md) · [Original receiver receipt](../result/receiver.json)

```sh
case_dir=examples/receiver-control
study="$case_dir/known-field-checks"
out=$(mktemp -d)
gzip -dc "$case_dir/phase-anchors/synthetic-native.msc.bin.gz" > "$out/input.msc"
python scripts/salvage_msc_packets.py "$out/input.msc" --transport-only --save-packets --out "$out/stock"
python "$study/check.py" forecast "$out/stock/packets.npz" "$out/forecast.json.gz"
cmp "$out/forecast.json.gz" "$study/forecast.json.gz"

seal=6094f8bda93d80222431c43de73277b23061b757e43909424f92bc782a16a7e9
python "$study/check.py" score "$out/forecast.json.gz" "$seal" "$case_dir/fixture/sender.192.gz" > "$out/score.json"
cmp "$out/score.json" "$study/score.json"
python "$study/test_check.py"
```

The forecast includes all 2,400 scheduled slots. Packet flags determine which inputs are available. The rule adapter reads the current and immediately previous mode within a group and the final payload octet of eligible transition words. The score verifies the ledger SHA-256 before opening the sender file, then checks both its compressed and uncompressed hashes. All 2,130 received mode octets and 63 selected endings matched the sender. This is a retrospective calibration on locally generated speech-like signals, tones, noise and silence from one encoder configuration. It supplies no original labels for broadcast radio. [Sender provenance](../fixture/sender.json)
