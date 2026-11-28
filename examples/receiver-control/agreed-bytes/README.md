# Can two damaged receptions of one IQ file recover a physical packet?

On a locally held-out 3205 kHz recording, two demodulations failed the first packet of counter **43872625**, phase 0. Their hard decisions differed at 11 of the packet's 1,456 bits. The frozen solver found exactly one of the 2,048 combinations that satisfied the transmitted packet CRC. Its three unchanged sibling packets also produced a complete 716-byte unit with the transmitted CRC `CF6F`. A third demodulation of the same IQ independently passed the packet CRC and reproduced the proposed **182 bytes exactly**. All three passes processed the same first 120 seconds of the contributor recording dated November 27 at 12:11:22 UTC by filename. The contributor had published whole-recording aggregates. [Frozen method](protocol.md) · [Lossless IQ and sample bounds](field/input.json) · [All three receiver settings and hashes](field/reception.json)

The one-iteration Wiener output had four incorrect wire bits in slot 2 at the third position when compared with the third pass. Two were in directly transmitted payload byte 5. Two were in the transmitted form of protected payload byte 6. Correcting that packet let the receiver assign nine packet coordinates at counter 43872625 and four at 43872626. At 43872625 this gave 46 complete wire slots, five partial slots, nine absent slots and 8,280 directly readable bits. The third pass already supplied all 13 of those additional coordinates, and every corresponding packet body agreed. The count of complete transport groups stayed at 42. [Sealed packet proposal](https://github.com/skgsara/kcbs-drm/commit/7972ebd) · [Full-wire check](field/packet-score.json) · [Coordinates and directly affected fields](field/transport-comparison.json)

The independent-station check comes from a separate development recording at 6140 kHz. There the two settings on Edogawa IQ produced three whole-packet proposals. A separate receiver at Yokohama recorded all three 182-byte packets and all three 716-byte units exactly as proposed. A synthetic control produced a wrong packet that still satisfied both CRCs when the two demodulations shared errors. This leaves common errors as a source of ambiguity even after a unique CRC solution. [Independent receiver and synthetic controls](../disagreement/README.md)

## Individual bytes in packets that failed both CRCs

The two Wiener passes provided a second test. We sealed all their predictions before running the linear-time receiver. A prediction required a run of at least eight identical **directly carried** EVS octets in address order within the damaged packet. This yielded 12,475 proposed octets across 114 packets. The third pass provided a CRC-valid label for 3,518 predictions in 32 packets. It agreed on 3,462, disagreed on 56, and supplied no label for the remaining 8,957 predictions. Only seven of the 32 labelled packets agreed on every issued prediction. The simpler rule that issued any agreeing octet gave exactly the same 3,518 labelled predictions here. Either original pass used on its own matched 3,463 of the 3,520 directly carried octets with labels. [Octets sealed before the third pass](https://github.com/skgsara/kcbs-drm/commit/27317b4) · [Per-method denominators](field/octet-summary.json) · [Per-octet outcomes](field/octet-scores.json.gz)

On the earlier Edogawa recording, Yokohama independently checked 8,868 such predictions and disagreed with 209. Agreement within one IQ recording therefore carries measurable information about damaged bytes, but using these estimates as received EVS fields would introduce errors. [Historical station comparison](peer.json)

## Four-position result

The original one-iteration receiver's first complete group was **43872587**. Each position had all 15 wire slots, 2,640 directly carried bits and 1,320 carried bits with unknown clear values. Across the group, 56 mode-conditioned checks matched 224 directly checkable bits. Under the ordinary EVS transition rule, slot 0 allowed `00` or `01` for word bits [8,10), and slot 26 allowed only `01`. These three conditionally fixed bits have no independent clear labels here. The primary had **0/60 complete clear EVS words**. The partial control, 43872591, had 9,896 directly carried bits, 4,944 carried with unknown clear values and 1,000 missing transport bits. None of the 75 original assigned IDs or the 80 seen across all receiver outputs occurred in the 15,194-ID pre-test local inventory. [Original selections](field/group-seal.json) · [Every slot, field exclusion and erasure](field/group-fields.json.gz)

We also looked for these 60 slots in the two published 06:17:22 UTC EVS streams. Each target slot had a distinct sequence of 22 directly transmitted octets. The text-supported stream contained 355 supplied words and the programme stream contained 1,150, including those 355. **Neither stream contained any of the 60 target sequences.** As a positive control, the same lookup against the accompanying 06:17 packets placed all 355 and all 1,150 words uniquely at the exact counter, phase, cycle and position in their slot ledger. This tests file alignment. The November 27 contributor table lists 730 text-supported frames for the entire 12:11:22 recording without giving their slot coordinates. [Lookup code](../../../scripts/locate_evs_slots.py) · [06:17 packets](../../nov27/receiver/packets.npz) · [Slot ledger](../../nov27/frames.csv) · [Contributor's report](../../../docs/november-2026.md#seven-additional-november-27-recordings)

## Reproduction

From the repository root, set `KCBS_DREAM` to the pinned finite-input executable. These commands replay the three native streams and verify them byte-for-byte. The published native files can also be used directly. The first seal predates the third pass. The second predates checking the packet proposal against the four-iteration Wiener output.

```sh
d=examples/receiver-control/agreed-bytes
f="$d/field"
m=examples/receiver-control/disagreement
a=examples/receiver-control/phase-anchors
w=$(mktemp -d)
iq="$f/3205kHz-121122-0-120s-iq12.flac"
for n in 1 4; do
    python scripts/demod_iq_window.py "$iq" "$w/w$n" --seconds 120 --reception-profile wiener --mlc-iterations "$n"
    cmp "$w/w$n/msc.bin" "$f/wiener$n-msc.bin"
done
python "$d/sealed.py" seal --one "$f/wiener1-msc.bin" --four "$f/wiener4-msc.bin" --out "$w/forecast.json.gz"
cmp "$w/forecast.json.gz" "$f/octet-forecasts.json.gz"
python scripts/demod_iq_window.py "$iq" "$w/linear" --seconds 120 --reception-profile linear-time --mlc-iterations 4
cmp "$w/linear/msc.bin" "$f/linear4-msc.bin"
python "$m/solve.py" propose "$f/wiener1-msc.bin" "$f/linear4-msc.bin" > "$w/proposals.json"
cmp "$w/proposals.json" "$f/packet-proposals.json"
packet_seal=787c4f34d8d295ea10e4710c89731fe1876c51e1481fa824cc1bbde99033c2e7
octet_seal=9717e90bc285c8608613b0eea32a3791db6d08e1195cf5e7df81ae868e6c50bb
python "$m/solve.py" score "$f/wiener1-msc.bin" "$f/linear4-msc.bin" "$w/proposals.json" \
    --seal "$packet_seal" --peer "$f/wiener4-msc.bin" --witness-origin same-iq > "$w/packet-score.json"
cmp "$w/packet-score.json" "$f/packet-score.json"
python "$d/sealed.py" score --one "$f/wiener1-msc.bin" --four "$f/wiener4-msc.bin" \
    --sealed "$w/forecast.json.gz" --sha256 "$octet_seal" --peer "$f/linear4-msc.bin" \
    --label-source same-iq --out "$w/scores.json.gz"
cmp "$w/scores.json.gz" "$f/octet-scores.json.gz"
python "$d/compare_transport.py" "$f" --seal "$packet_seal" > "$w/transport.json"
cmp "$w/transport.json" "$f/transport-comparison.json"
python "$a/phase_anchors.py" "$f/wiener1-msc.bin" --out "$w/coordinates" > "$w/placements.json"
python "$a/score_air.py" seal "$f/wiener1-msc.bin" "$w/coordinates" > "$w/groups.json"
cmp "$w/groups.json" "$f/group-seal.json"
python "$d/field_groups.py" "$w/groups.json" 02c69e60ff2387974fbbd77f13edfdd6ebb4834ed72c9b98487183cb9ae1adc8 \
    "$w/coordinates/extended/packets.npz" | gzip -nc > "$w/fields.json.gz"
cmp "$w/fields.json.gz" "$f/group-fields.json.gz"
```
