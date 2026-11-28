# Recovering physical packets from two receiver configurations

Two Dream configurations demodulate the same IQ recording. The solver considers a packet only when both original decodes fail, both have its expected header and they disagree at 1–12 physical bits. It computes whether exactly one combination in those positions satisfies the transmitted packet CRC. A proposal also needs three CRC-accepted sibling packets and a complete 716-byte DU passing its transmitted CRC. One unique, unchanged, CRC-accepted sibling anchors the two rows. The existing row matcher rejects inconsistent overlaps, ambiguous partners and ordering conflicts.

Both CRCs use the same polynomial. An error shared by both decodes can therefore survive both checks. The synthetic control exhibits a unique, doubly CRC-valid proposal that still differs from the sender at four physical bits. A separately received CRC-accepted wire permits a stronger check, provided another ordinal anchors the row. Proposed packets remain distinct from native receipts.

## Replay

Run from the repository root with the project's Python dependencies installed. The shipped MSC inputs allow an offline replay without Dream. Set `D`, `S` and `W4` as below. Use an existing directory of your choice for `tmp`.

```sh
D=examples/receiver-control/disagreement
S=examples/nov28/same-6140-1232
W4=examples/nov28/clear-evs-controls/transport-mlc4/edogawa-mlc4-msc.bin
tmp=$(mktemp -d)
python "$D/solve.py" propose "$S/edogawa-msc.bin" "$D/dev/edogawa-linear4-msc.bin" > "$tmp/decisions.json"
sha256sum "$tmp/decisions.json"
cmp "$tmp/decisions.json" "$D/dev/linear-proposals.json"
```

The development decision seal is `3896a7a5e6be7cd660fcb8c7a79612b6d4a1fb3adf83bfd64d18596d01ec4f7b`. For a new input, record its decision SHA externally before opening a comparison receiver. The score stage verifies both the saved SHA and the complete proposal recomputation before reading the witness. Identify the acquisition relationship explicitly.

```sh
seal=3896a7a5e6be7cd660fcb8c7a79612b6d4a1fb3adf83bfd64d18596d01ec4f7b
python "$D/solve.py" score "$S/edogawa-msc.bin" "$D/dev/edogawa-linear4-msc.bin" "$tmp/decisions.json" --seal "$seal" --peer "$S/yokohama-msc.bin" --witness-origin independent-station
python "$D/solve.py" score "$S/edogawa-msc.bin" "$D/dev/edogawa-linear4-msc.bin" "$tmp/decisions.json" --seal "$seal" --peer "$W4" --witness-origin same-iq
python "$D/materialize.py" "$S/edogawa-msc.bin" "$D/dev/edogawa-linear4-msc.bin" "$tmp/decisions.json" --seal "$seal" --out "$tmp/export"
python "$D/development.py" > "$tmp/field-score.json"
cmp "$tmp/field-score.json" "$D/dev/field-score.json"
python "$D/synthetic.py" > "$tmp/synthetic.json"
cmp "$tmp/synthetic.json" "$D/synthetic.json"
```

The exporter requires a new output directory. Each `row-NNNNNN.du` contains the proposed packet's body plus the three unchanged CRC-accepted siblings. `proposed.msc.bin` is a separate row-preserving overlay suitable for the standard transport reader. `material.json` records the source branch for every sibling, proposed DU digest, transmitted CRC, phase and changed physical bit offsets. Row numbers are zero-based local receiver indices. Absolute counters for phase 1/2 need the transport reader or a separately anchored group.

## 12:32 UTC, 6140 kHz development recording

Both Edogawa inference branches start at sample pair 0 of the same 4,320,000-pair capture. Wiener MLC1 versus Wiener MLC4 yielded 85 jointly rejected packets across 136 anchored rows and zero complete proposals. Wiener MLC1 versus linear-time MLC4 yielded 42 jointly rejected packets across 131 anchored rows. Six had unique packet solutions. Three lacked accepted siblings, and three produced proposals. The independently acquired Yokohama receiver matched all 182 bytes of each proposed wire and all 716 bytes of each assembled DU. The third Edogawa configuration, Wiener MLC4, accepted one of the three proposed target wires and agreed with it. Its other two comparisons were unavailable.

| Edogawa row / q | Counter / phase | Changed direct EVS bytes, primary → peer | Other changed byte |
|---|---|---|---|
| 41 / 0 | 43945666 / 0 | Slot 3 P4 payload 7, E8 → C2 | |
| 129 / 0 | 43945695 / 1 | Slot 21 P2 payload 13, 17 → 47 | One physical bit in P2 payload 12, a non-direct octet |
| 156 / 0 | 43945704 / 1 | Slot 22 P3 payload 31, 19 → 1F. Slot 23 P4 mode, 88 → F8 | |

Here the three proposed packets changed 10 direct EVS bits and one non-direct transport bit. Row 129 also needed an already accepted linear-time q1 sibling. Its substitution changed one direct bit and three non-direct transport bits relative to the failed primary q1. Both source and destination values for direct octets are hexadecimal. Payload offsets exclude the mode octet. The overlay increases Edogawa from 82 to 85 complete DUs and from 17 to 18 complete 60-slot groups. Yokohama already had the additional group 43945704. This development sample tests physical transport bytes.

The linear-time MLC4 input is included for replay. To regenerate it, use the same Dream executable as the published capture, SHA-256 `1e398433affbe71e3bdbc30171e9c770ddd3a622c0fe1577b3f3837c3fa07a26`. The compressed Edogawa IQ file SHA-256 is `780aef117a8f3445a6879b79e34ecdf2f063047d0aa3d67a1e8f71249889c294`. The runner uses frequency interpolation 2, time interpolation 0, metric 0 and four MLC iterations. The 160,308-byte output SHA-256 is `0de1ec4f3718ae0898f4ca4e1c8def67c623c16376c8e3854f6f92b5e1b5ebeb`. [Original two-site reception](../../nov28/same-6140-1232/README.md)

```sh
KCBS_DREAM=/path/to/dream python scripts/demod_iq_window.py "$S/iq/edogawa-6140khz-iq48.flac" "$tmp/linear4" --start 0 --seconds 90 --reception-profile linear-time --mlc-iterations 4
cmp "$tmp/linear4/msc.bin" "$D/dev/edogawa-linear4-msc.bin"
```
