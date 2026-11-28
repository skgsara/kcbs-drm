# Prospective 6140 kHz field check, November 28

Begin one 120-second IQ48 reception at 13:47:30 UTC on 7L4IOU Edogawa. Start an independent recording at JL1EDU Yokohama on the same frequency and clock schedule. Each station has one connection attempt. Preserve original samples and packet timestamps, including uncertain intervals, and report any shortfall. The Edogawa WAV is the receiver's only programme input. Use the published Edogawa receive plan and its finite-input Dream build for one unpadded Wiener/MLC1 pass. Process peer samples only after sealing the primary results. [Receiver plan](receive-plan.json) · [Independent station plan](peer-plan.json)

Select the first directly received sequence of three consecutive CRC-valid data units in phases 0, 1 and 2, in native Edogawa MSC file order. Check that all three match the accepted packet snapshot. Report all 60 slots, the four position totals, standard field checks, the values they exclude and any word erasures. Any intersection of assigned counter IDs with the frozen inventory disqualifies a novelty claim. Preserve the first selection even on a collision or a peer miss. If the primary has no complete group, report the empty primary. [Selection and projection](primary.py) · [14,955 prior IDs and sources](history-origins.json)

Test the SWB GSC AUDIO prediction of physical bit 40 from its directly transmitted mode octet. Make predictions across all received modes, including those in partially received groups. Separately select the lowest (counter, phase, cycle, position) whose mode predicts zero, even if its target bit is missing. Hash the decisions before reading the target field. Report both prediction branches, a constant-one baseline, and controls displaced by one chronological slot before and after. An empty branch has no field accuracy estimate. Compare directly received bytes at the primary counter against independently received peer bytes after sealing. The peer cannot fill any primary erasure. [Field scorer](score.py) · [Frozen source dependencies](scorer-dependencies.json) · [Seven development archives](development.json)

On development data, 799 directly observed eligible fields in whole data units all carried a one. Of these, 687 were in complete three-phase groups. Both the mode rule and the constant-one baseline matched every eligible target. The zero branch therefore has no on-air examples in that development set. The adjacent-slot controls scored 730/794 and 720/793. Missing observations are excluded from these two score denominators.

From the repository root, use the accepted MSC dump and transport directory for both commands. The outputs are sealed together.

```sh
case=examples/nov28/edogawa-audio-branch
python "$case/primary.py" rf/msc.bin transport > primary.json
python "$case/score.py" transport/packets.npz --repo . --out audio.json
```
