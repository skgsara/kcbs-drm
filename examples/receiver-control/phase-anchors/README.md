# Assigning CRC-valid phase tags between two counters

This single-receiver transport check added **176 exact EVS words** on the declared-clear 40-group synthetic transmission. It locates a received packet in a group using its row's phase tag. The extra words consist entirely of bytes that already passed their own physical packet CRC. [Synthetic result](synthetic.json) · [Original test transmission and stock receiver](../README.md)

| Synthetic sender comparison | Stock | With extra phase assignments |
| --- | ---: | ---: |
| Assigned CRC-valid packets in the 40 groups | 424 | 459 |
| Complete CRC-valid data units | 100 | 108 |
| Exact words out of 2,400 | 2,113 | 2,289 |
| Extra erasures beyond the 78 required by the lost packets | 209 | 33 |
| Wrong words or words supplied at a required erasure | 0 | 0 |

## How a row gets a coordinate

The stock parser checks each packet's transmitted header and CRC and the enclosing CRC of any complete data unit. Two phase-zero rows must each have an intact first packet carrying the phase tag and an intact fourth packet carrying the counter. The counters must advance by one or two, modulo 2³². The bracket may contain at most three native row intervals per counter increment. The checker rejects a bracket with a parser barrier, a wholly unreadable row, or a repeated CRC-valid first packet.

The checker first requires at least one chronological placement for **all** interior rows. On any placement of a phase-zero row with a valid fourth packet, its transmitted counter must agree. The checker then considers every chronological placement of just the rows with CRC-valid phase tags, allowing gaps. A tagged row receives an extra coordinate only if every placement gives it the same counter and phase. Opaque rows can rule out an inconsistent bracket. They cannot supply a phase tag or choose among several possible placements.

For example, synthetic native row 63 has a CRC-valid phase-zero tag but lacks its counter packet. The directly received anchors on either side differ by two. Every permitted placement assigns the middle phase-zero row to counter 16909071. Its three CRC-valid packets can then be read at that coordinate. A lone phase-one tag between anchors two counts apart can belong to either group and stays unresolved.

The method assumes native callbacks are chronological. Reordered callbacks with otherwise plausible phase tags can defeat this assumption. Short brackets, the repeated-first-packet veto, and consistency checks reject identifiable problems. An independent receiver or a known sender provides a separate test of any new placement. Conflicting observations and a failed reassembled DU CRC reject the proposed addition at that coordinate. All previously accepted stock packets remain available, and previously quarantined stock coordinates stay quarantined. [Receiver checker](phase_anchors.py) · [Wire and quarantine controls](controls.py)

## Independent receiver comparison

At 12:32 UTC on 6140 kHz, 48 added packets at Edogawa matched all 182 bytes of Yokohama's independently assigned, CRC-valid wires in complete groups. In the reverse direction, four added Yokohama packets lacked a stock witness at Edogawa. Across the archived 12:32 and 21:26 receiver pairs in both directions, 90 of 278 added site observations had a corresponding independently assigned wire. All 90 matched. The remaining 188 lack this test. [Per-site wire comparisons](peer.json)

The separate prerecorded single-receiver application uses a nominal 60-second interval on 3205 kHz. Its protocol fixes the bounds, receiver and reporting criteria before the excerpt is examined. Broadcast packet placement establishes which wire bytes arrived. Their clear EVS values require an independent label wherever the application format leaves them unknown. [Field protocol](field-protocol.md)

## Reproduction

From the repository root, use Python with the project dependencies. The synthetic replay checks the original receiver's sealed native MSC and packet archive, its entire previously published word/erasure timeline, and the original stock encoder's independent G.192. The included 76 kB compressed native dump reproduces the transport experiment without rerunning the modulator. The original synthetic IQ reception can also supply the dump via the synthetic checker's `--native` argument.

```sh
case_dir=examples/receiver-control/phase-anchors
python "$case_dir/synthetic.py" --check "$case_dir/synthetic.json"
python "$case_dir/controls.py"
python "$case_dir/peer.py" --check "$case_dir/peer.json"
python "$case_dir/phase_anchors.py" NATIVE.msc.bin --out /tmp/new-phase-study
```

The last command accepts a single ordinary little-endian, length-prefixed MSC dump. It writes packet and data-unit archives under `stock/` and `extended/`. Its JSON report lists proposed row coordinates, original CRC-valid packet ordinals, stock and extended coverage, and additions quarantined before updating the extended snapshot.

## Held-out 3205 kHz broadcast

The fixed single-receiver rule placed **23 additional CRC-valid packets** in a locally held-out minute, providing **113 additional frame slots with all transmitted octets**. The input was the last full minute starting at 540 seconds in the November 27 12:15:02 UTC recording. Its contributor had already reported whole-recording aggregates. Reception used one cold IQ pass. The 29 assigned counters had zero overlap with the frozen local registry of 15,095 IDs. The test assumes the receiver callbacks preserve transmission order. This recording supplied no independent receiver to verify the new coordinates. [Input and selection protocol](field-protocol.md) · [Lossless IQ and source bounds](field/input.json) · [Dream receipt](field/reception.json)

| In this minute | Stock receiver | With CRC-checked phase placement |
| --- | ---: | ---: |
| Assigned packet coordinates | 213 | 236 |
| Complete CRC-valid data units | 50 | 55 |
| Complete three-phase groups | 10 | 10 |
| Complete transmitted word slots | 1,064 | 1,177 |
| Directly readable bits with assigned coordinates | 187,800 | 207,968 |
| Complete clear EVS words | 0 | 0 |

The first complete group in native row order was **43873223**, starting at row 8. Each of its four positions had 15 complete transmitted slots. The projector reported 10,560 directly readable bits and 5,280 bits with unresolved clear values. All 28 checks against readable fields matched, covering 112 distinct direct bits. In slots 9 and 20 the existing transition-tag rule conditionally excludes `01` from clear word bits 8–9; `00`, `10` and `11` remain allowed. Those two bits have no independent clear observation at either slot. [Sealed selections and per-row anchors](field/seal.json) · [Full machine-readable results for both receivers](field/score.json.gz)

The incomplete control was **43873230**. The new rule placed native row 31 at phase 2 and increased complete physical slots from 20 to 40, ten per position. At slot 52, a newly available field condition allows `00` and `01` for word bits 8–9. This prediction leaves bit 8 conditionally zero and supplies no measured clear value there. [Accepted packet ordinals](field/placements.json)

From the repository root the frozen data and scripts reproduce the field report. Use a new output directory for the receiver.

```sh
case_dir=examples/receiver-control/phase-anchors
field_dir="$case_dir/field"
work_dir=$(mktemp -d)
python "$case_dir/phase_anchors.py" "$field_dir/native.msc.bin" --out "$work_dir/receiver" > "$work_dir/placements.json"
python "$case_dir/score_air.py" seal "$field_dir/native.msc.bin" "$work_dir/receiver" > "$work_dir/seal.json"
cmp "$work_dir/seal.json" "$field_dir/seal.json"
python "$case_dir/score_air.py" score "$work_dir/seal.json" "$work_dir/receiver" \
  9b58bb342cf18706bf9e18045398db13f671825075d25b9a6fcac8cee24b78d1 > "$work_dir/score.json"
gzip -dc "$field_dir/score.json.gz" | cmp - "$work_dir/score.json"
```
