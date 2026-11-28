# Prospective IQ acquisition, November 28–29 UTC (registered before recording)

This file was committed before any recording it describes began. Its commit time
is the registration time. The four mask-byte methods in
[`../blind-mask-benchmark/method-panel/`](../blind-mask-benchmark/method-panel/)
were frozen at `f79d70f`, before any of these recordings existed. Any groups
labelled from these recordings are therefore a prospective, out-of-time test
set for those methods.

## Receivers

Only two public UberSDR receivers within 3,000 km of Pyongyang offer `iq48`
(checked against the UberSDR instance directory on 2026-11-28 17:20 UTC):

| name | origin | session limit |
|---|---|---|
| `jl1edu` (Yokohama) | `https://ubersdr.jl1edu.freeddns.org` | none reported |
| `7l4iou` (Edogawa) | `https://7l4iou.tunnel.ubersdr.org` | 3,600 s |

## Schedule

KCBS-2's reported operating hours are 05:00–23:00 KST (20:00–14:00 UTC).

| session | UTC window | carriers probed | purpose |
|---|---|---|---|
| M (KST morning) | 2026-11-28 19:58 → 2026-11-29 00:00 | 3205 kHz; 6140 kHz | keyed groups for a prospective label set; two-station coverage |
| E (KST evening) | 2026-11-29 12:10 → 13:20 | 6140 kHz only | common-clock 6100 kHz AM plus 6140 kHz DRM reference window |

A 6140 kHz recording is always tuned to **6122 kHz**. This places the DRM
channel at +18 kHz and the 6100 kHz AM carrier at −22 kHz, both sampled by the
same clock.

## Fixed procedure

[`acquire.py`](acquire.py) runs both sessions unattended:

1. **Probe.** Each receiver records 12 s on each probed carrier. The DRM gate is
   the mean in-channel power (|f| < 4.5 kHz) minus the mean adjacent power
   (5.5–9.5 kHz away), at least **3 dB**.
   - Positive control: archived Edogawa 6140 kHz DRM measures 18.8 and 15.5 dB.
   - Negative control: overnight noise measured −0.5 to 1.2 dB at 17:22 UTC.
2. **Assign.** Each receiver goes to its carrier with the largest excess that
   passes the gate. If neither passes, the receiver is probed again every 5 min
   until the session ends.
3. **Record.** Once assigned, a receiver records back-to-back `iq48` segments of
   3,600 s (Yokohama) or 3,500 s (Edogawa) until the window closes.
   - Each segment uses `scripts/record_ubersdr_iq.py` with packet timing.
   - Reconnection gaps are left as gaps; they are never filled.
4. **Store.** Each WAV is converted to 16-bit stereo FLAC. The WAV is deleted
   only after the FLAC decodes to the recorder's `iq_pcm_sha256`. Every probe,
   assignment and segment is appended to `log.jsonl`.

## Use of the recordings

- **Demodulation.** IQ goes through the repository's Dream pipeline and then
  `scripts/salvage_msc_packets.py`. Only CRC-valid data units are used, with no
  single-bit repairs.
- **Keys.** Keys come from the text fill crib at the **≥15/16** gate. On DEV
  this gate agreed with CRC-supported keys in 318/318 and 174/174 groups.
- **Sealing.** Labels are built in the `dev.T1` layout and sealed by SHA-256
  before any mask method reads them.
- **Methods and thresholds.**
  - The methods scored are the frozen scripts and models whose hashes appear in
    the method-panel freezes.
  - Inclusion follows the DEV-only common-subset comparison.
  - Thresholds come from the stage-0 registration (`work/catchup/next/registration.json`).
    Its SHA-256 will be committed before the first prospective group is labelled.
- **Reporting.**
  - Results are reported per receiver and per carrier, with a wrong-group
    control and group-bootstrap intervals.
  - Counters already present in any benchmark split or contributed key file are
    excluded and counted.

The 13:00-style null outcome is possible: zero CRC-valid groups at a receiver
or carrier will be reported as such.
