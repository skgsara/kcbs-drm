# A four-bit GSC check on two radio receptions

At counter 43908300, phase 0, cycle 2, position 1 (slot 8), the 3205 kHz member receiver accepted packet 0 carrying mode `74` at DU byte 4. It discarded packet 1, which covers payload octet 4 at DU byte 273. The independently recorded 6140 kHz Edogawa receiver accepted all four packets and the DU CRC. Its payload octet 4 was `C1`. The field predictions were computed from the 3205 capture before passing any accepted target to the comparison.

| Existing check | Source bits of mode 74 | Target word bits, MSB first | Allowed values | Accepted 6140 value |
|---|---|---|---|---|
| `inactive_nibble`, an empirical SWB INACTIVE pattern | [0,6) = 011101 | [40,44) | 12 (1100) | 12 |
| `swb_gsc_inactive`, a reference-codec pitch-band range | [0,5) = 01110 | [44,48) | 0 through 10 | 1 |

The first row compares four determined bits in one field of one word. The second row eliminates five nibble values and determines no individual bit. Both full EVS words remain erased. These observations come from two RF recordings of the same transmitted content and the case was chosen retrospectively. They do not constitute four independent trials or a test of any scrambled octet.

Both original native records are supplied, including their length prefixes, physical headers and transmitted CRCs. The 3205 record's packet 1 CRC was `F872` calculated versus `30E0` sent. The 6140 record's packet 1 CRC was `30E0` calculated and sent, and its DU CRC was `1EEF`. Inspection after scoring found that the rejected 3205 packet had the same target octet. Across the two raw 716-byte DUs, the only difference was four bits at byte 211. Accordingly this is a genuine 3205 **packet erasure**, with matching contents at the target location in the raw rejected packet.

The checker first verifies the raw packets and their phase-0 embedded counter. It calls the public projection and field rules with only accepted received bytes. Replacing every unaccepted storage byte with either 00 or FF leaves the 3205 projection and predictions identical. Removing the peer's target packet gives the same predicted domains. Removing the source mode packet suppresses both checks. The peer's intact target is then compared. The native byte-difference audit runs last.

Run from the repository root with Python 3 and NumPy. The receiver revision used for the original analysis was `30a3b2fee0f0f1822329a2455814adb958c4f40c`.

```sh
cd examples/nov28/group-boundary/four-bits
python check.py --scripts ../../../../scripts | diff - expected.json
```

With the full native MSC dumps, add `--original-3205 MEMBER_WINDOW0_MSC --original-6140 EDOGAWA_MSC` to check that the two excerpts are byte-identical to original records 1120 and 434 respectively (zero based). Full-file and excerpt SHA-256 digests plus all packet and DU checksums are in `expected.json`.
