# Scheduled 3205 kHz IQ test, November 28 at 13:00 UTC

The recording window is 13:00–13:20 UTC on JL1EDU in Yokohama at 48,000 complex samples per second. For this receiver test use only the **first 600 recorded seconds of the earliest in-window IQ file**. If shorter, use the available in-window samples from that file. A reconnection starts a new file. Use file sample order, record any timestamp discontinuities and flag uncertainty in wall-clock alignment. Preserve the full capture, including later files, for the group. Ten minutes is the maximum window supported by this demodulation entry point.

Record the original sample interval, sample count, segment SHA-256, receiver revision and Dream binary SHA-256 before scoring. Demodulate once from reset at nominal tuning, Wiener profile, one MLC iteration. Use the checked physical packet headers and packet/data-unit CRCs. Use just this one MSC input in salvage. If there is no IQ, MSC, assigned counter or complete group, retain that outcome.

Compare every assigned counter, including incomplete or subsequently quarantined coordinates, against the 13,483-ID frozen inventory. Any historical intersection disqualifies the run from a novel-counter score. The primary is the first complete group in original MSC row order, using its phase-zero packet 0 as the time coordinate. Separately score the first counter containing a phase with one through three accepted packets. Use its first assigned physical row and break a tie with the lower counter. Each selected counter gets all 60 ordered slot reports, with direct octets, missing packet locations, conditional codec checks and word erasures. One receiving station supplies one observation of each distinct coordinate. Replaying it supplies a reproducibility check. Exact clear-bit accuracy requires a comparison that establishes those clear values independently. [Frozen counter inventory and source totals](history-receipt.json)

Use the finite-input Dream build from upstream revision `895658c567d2fd47d6006065e75abf0c3157783f` with the patches in this repository revision. The prepared Linux executable has SHA-256 `1e398433affbe71e3bdbc30171e9c770ddd3a622c0fe1577b3f3837c3fa07a26`. If building on a different host, record the executable digest and build environment. [Build recipe](../../../build/README.md)

From the repository root, point `KCBS_DREAM` at that build and set `segment` to the verified first in-window segment. Run the commands in a fresh output location. If the first file starts before 13:00 UTC, first trim it losslessly to the in-window samples using the recorder timestamps and retain the original.

```sh
python scripts/demod_iq_window.py "$segment" scheduled-rf --seconds 600 --reception-profile wiener --mlc-iterations 1
python scripts/salvage_msc_packets.py scheduled-rf/msc.bin --transport-only --save-packets --out scheduled-transport
python examples/nov28/yokohama-1300/score.py scheduled-transport > scheduled-fields.json
```

The scorer checks that the complete data units appear identically in the packet snapshot. Hexadecimal values in the slot report cover the mode plus up to 21 directly transmitted payload octets. The receiver records known restrictions on masked bits separately. It leaves a word erased whenever its full clear value remains unresolved.
