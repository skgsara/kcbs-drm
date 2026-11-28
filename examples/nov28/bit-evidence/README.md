# Checking an IQ receiver against partial frame exports

The receiver can report what it knows at each of the 60 frame slots. Each slot accounts for 264 bits across three categories. A directly transmitted octet contributes eight direct bits. A received masked octet contributes eight bits with unresolved clear values. A missing or quarantined packet provides no accepted receipt for its octets. Each codec check lists the input slots and bit ranges it used, the allowed target values, and any target value that the receiver can actually observe. Coordinates use MSB-first word bits and half-open ranges. [Bit evidence reporter](../../../scripts/evs_evidence.py)

## An IQ test fixed before opening the selected samples

We selected the last 7.34456 seconds of the November 19 17:31:39 recording at 6140 kHz. Earlier documented accesses to this recording ended at sample 291840000, where this test starts. The original contributor's use of this portion is unknown. We published the input limits, receiver revision, acquisition settings, 13,731 prior counter IDs by digest, and the first-complete-group selection rule before requesting these samples. [Published protocol](https://github.com/skgsara/kcbs-drm/commit/75bd339afc2522d1b9097cb4f47299bcd78f0822) · [Range and reception receipt](tail-reception.json)

The single cold receiver pass produced 12 data units with valid CRCs. Two came before the first counter anchor. The remaining ten contained complete groups 43288873–43288875 and phase zero of 43288876. All four counters were absent from the prior inventory. The primary group was 43288873. Every position had 15 received slots and 2,640 direct bits. The TCX20 predecessor check made 14 predictions at position one and 15 at each other position, all for word bit 8. The first slot lacked an in-group predecessor. The underlying clear bit is unobserved in all 59 predictions.

| Primary group 43288873 | P1 | P2 | P3 | P4 | Total |
| --- | ---: | ---: | ---: | ---: | ---: |
| Directly transmitted bits | 2,640 | 2,640 | 2,640 | 2,640 | 10,560 |
| Received bits with unresolved clear values | 1,320 | 1,320 | 1,320 | 1,320 | 5,280 |
| Bits without a packet receipt | 0 | 0 | 0 | 0 | 0 |
| Conditional bit-8 predictions | 14 | 15 | 15 | 15 | 59 |
| Complete clear EVS words | 0 | 0 | 0 | 0 | 0 |

Run from the repository root. The included MSC is the original output of the frozen RF pass. The field report from the current projector matches the frozen receiver's primary report.

```sh
case_dir=examples/nov28/bit-evidence
out=work/bit-evidence-tail
python scripts/salvage_msc_packets.py "$case_dir/tail-msc.bin" --transport-only --save-packets --out "$out"
python scripts/project_evs_group.py --packets "$out/packets.npz" --counter 43288873 --evidence > "$out/evidence.json"
python scripts/project_evs_group.py --packets "$out/packets.npz" --counter 43288873 --field-checks > "$out/projection.json"
```

## Comparing a text-supported handoff

The comparison reads a saved projection and a G.192 or mono EVS storage file. It aligns supplied words using the export's starting counter, phase, cycle and position. It retains explicit erasures, slots outside the export and every disagreement on directly comparable bits. When a supplied slot disagrees on a direct coordinate, checks depending on that slot are marked as having conflicting inputs. The source of the supplied word determines which conclusions a match supports. [Comparison tool](../../../scripts/compare_evs_evidence.py)

In the November 27 11:05 handoff for **43869343**, the member supplied 15 first-position words. Their 2,640 directly comparable bits matched. In slot 32 the codec check allowed `00`, `10` and `11` for bits 8–9. The supplied word contained `11`. The check excluded one pair and neither bit was individually determined. Two further checks on eight other slots used the high and low nibbles of the same directly received octet. [Control results and input hashes](reference-controls.json)

At **43865918**, the existing first-position export derived from the group's 17:56 text data also matched all 2,640 directly comparable bits. The same TCX20 predecessor rule used in the new IQ test predicted one at bit 8 in all 14 eligible first-position words. The stored words gave zero in all 14. Their text support traces to one ordinary record, starting at 43865917 phase zero, with transmitted CRC `B81A`. The 14 comparisons share that witness. The comparison reproduces a previously documented discrepancy. Its cause remains unresolved. [Earlier discrepancy report](../../nov15/validation/field-check-43005013/README.md) · [Control receipts](reference-controls.json)

For a new handoff, a G.192 with explicit erasures preserves the timeline. Recording the counter, phase, cycle, position and supporting text record for each added word lets the group distinguish newly supplied positions and repeated uses of one record. The original 11:05 example can be run with the member's extracted handoff as follows.

```sh
python scripts/project_evs_group.py --packets "$handoff/receiver/packets.npz" --counter 43869343 --field-checks > "$out/1105.json"
python scripts/compare_evs_evidence.py "$out/1105.json" "$handoff/replay/known-first-position.192.gz" --start 43869284 0 0 1
```
