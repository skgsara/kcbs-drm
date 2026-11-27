# Replay a complete 6140 kHz reception from IQ

The Edogawa receiver recorded KCBS-2 on 6140 kHz for three minutes beginning at 22:58 UTC on November 27. The receiver settings, the HQ class rule and the choice of the first complete counter were fixed before recording. All three data units of counter **43904973** passed CRC. All **60** frame slots arrived, 15 at each position. The direct projection recovered 10,560 clear bits. The clear values of 5,280 masked bits remained unresolved. The HQ rule gave no prediction on this counter, leaving **0 of 60** complete clear EVS words. [Frozen protocol](6140-protocol.json) · [Capture and per-field results](6140-receipt.json)

The recording contains all 8,640,000 original signed 16-bit I/Q sample pairs, stored losslessly as FLAC. The capture client flagged one receiver timestamp excursion of 23.218 µs, slightly longer than the 20.833 µs sample period. Both demodulator passes on the distributed FLAC produced byte-identical MSC dumps to their respective passes on the original WAV. [Full three-minute IQ recording, 26.9 MB](7l4iou-6140-20261127T2258Z-iq48.flac)

## Reproduce the result

From the repository root, use the KCBS-patched offline Dream build. Set `KCBS_DREAM` to its executable if installed outside the default locations. The WAV or FLAC supplies the only receiver observations. The following commands create new output directories. [Build instructions](../../../../build/README.md)

```sh
study=examples/nov27/validation/rf-iterations
iq="$study/7l4iou-6140-20261127T2258Z-iq48.flac"
for count in 1 4; do
    python scripts/demod_iq_window.py "$iq" "replay-6140/iter-$count" --seconds 180 --mlc-iterations "$count"
done
python scripts/salvage_msc_packets.py replay-6140/iter-1/msc.bin replay-6140/iter-4/msc.bin --transport-only --out replay-6140/du
python scripts/project_evs_group.py replay-6140/du/data_units.npz --counter 43904973
python examples/nov27/validation/hq-class/observe.py replay-6140/du/data_units.npz
```

Either iteration setting, and both pooled together, yielded the same **657 packets** with a known counter and position, **143 data units** and **35 three-unit groups**. Of 885 CRC-good physical packets at one iteration, all 885 agreed byte for byte at four iterations. The latter recovered one further packet whose counter could not be assigned.

## What the signal says about the clear words

The 35 groups supplied 2,100 frame slots, 525 at each position. Five mode octets allowed the previously tested HQ rule to exclude values for the first two bits of payload octet 0. The alternatives in this table assume the transmitter uses the EVS reference encoder's class choices. This capture supplies no independent clear-value comparison for those five masked fields. Slot numbering begins at zero. [HQ rule and earlier text-CRC checks](../hq-class/README.md)

| Counter | Slot | Position | Mode | Clear high-bit pairs excluded | Pairs still possible |
|---|---:|---:|---|---|---|
| 43904982 | 1 | 2 | F9 | 10, 11 | 00, 01 |
| 43904987 | 57 | 2 | F9 | 10, 11 | 00, 01 |
| 43905008 | 8 | 1 | FA | 11 | 00, 01, 10 |
| 43905024 | 3 | 4 | FA | 11 | 00, 01, 10 |
| 43905026 | 27 | 4 | FA | 11 | 00, 01, 10 |

A secondary test used the previously published ACELP checker. It hides the earlier frame's transmitted class bits from the predictor, then compares its prediction with those bits. Of 129 eligible adjacent pairs, 30 gave a restriction and all 30 agreed with the held-back field. Thirteen fixed its high bit at zero. Reversing the frame order produced 17 contradictions. This checks the frame order and class rule on fresh IQ. The checked field is already transmitted in the clear. We selected this additional analysis after reception. To reproduce it, run `python examples/nov27/validation/acelp-class-history/check.py replay-6140/du/data_units.npz`. [ACELP checker and field definition](../acelp-class-history/README.md)

## Reception controls on 3205 kHz

Two earlier three-minute Edogawa recordings identified the same service and packet format. At 22:27 UTC, 1,272 of 1,772 nominal packet slots passed header and CRC checks on the default path. At 22:41 UTC, zero of 1,292 passed. Median weighted modulation error ratio on the main service channel fell from 13.26 dB to 9.31 dB. The later recording still passed 424 of 444 fast access channel checks. We did not determine what caused the signal to weaken.

One fixed treatment detected spikes in the IQ outside the occupied channel and interpolated the marked samples. Pooling CRC-good packets from the original and treated passes gained two complete groups in the stronger recording. Moving the same interventions by 24,001 samples gave no gain. The following counts pool three different Dream channel estimates for each waveform.

| 3205 kHz waveform | 22:27 data units / groups | 22:41 data units / groups |
|---|---:|---:|
| Original | 200 / 52 | 0 / 0 |
| Interpolated | 212 / 53 | 0 / 0 |
| Original plus interpolated | 213 / 54 | 0 / 0 |
| Shifted control alone | 200 / 52 | 0 / 0 |

The original and treated receivers agreed on all 199 data units they both recovered at 22:27. The two additional groups were 43903493 and 43903524. In 43903493, slots 6 (position 3) and 53 (position 2) have mode F9. The HQ rule abstained on 43903524. Three 20-second cold-start crops failed to reproduce all three data units of 43903493. Its published data units come from the full recording. [Six CRC-checked data units](3205-added-data-units.npz)

On the held-back simultaneous 21:26 UTC captures, pooling the original and treated passes at Edogawa added **one packet** at counter 43900467, phase 0, quarter 1. Its computed CRC changed from `547C` to the transmitted `6744`. The next quarter remained missing. The two stations gained zero complete data units or groups, and all 31 data units received by both stations agreed. A separate one-versus-four iteration test using Wiener interpolation increased the two-station total from 1,133 to 1,137 assigned packets, with 263 complete data units and 68 groups in both runs. [Iteration comparison protocol and input digests](protocol.md)

To repeat the interpolation experiment on a 48 kHz stereo PCM16 IQ WAV, pass the original and processed samples through each profile and pool the CRC-checked results. The shifted control uses the same procedure with `--shifted-control` appended to the interpolation command.

```sh
study=examples/nov27/validation/rf-iterations
python "$study/impulses.py" original.wav repaired.wav
for waveform in original repaired; do
    for profile in wiener linear-time linear-time-modmetric; do
        python scripts/demod_iq_window.py "$waveform.wav" "replay-3205/$waveform/$profile" --seconds 180 --reception-profile "$profile"
    done
done
python scripts/salvage_msc_packets.py replay-3205/*/*/msc.bin --transport-only --out replay-3205/pooled
```
