# Four iterations on held-out 3205 kHz IQ

The prespecified receiver found **8 complete native groups** and assigned 29 counters in this 60-second interval. The first complete group, **43873081**, starts at zero-based MSC row 32. All 60 slots arrived, 15 per position. Each position has 2,640 directly readable bits and 1,320 carried bit values whose clear values are unknown. The primary thus has **10,560 direct bits, 5,280 unresolved clear bit values and zero complete clear EVS words**. None of the 29 counters appeared in the 15,021-ID local comparison inventory. A contributor previously reported aggregate reception from most of the same source recording. [Frozen receiver and input](protocol.md) · [Per-slot primary results](score.json) · [Inventory and transport comparison](transport.json)

In slots 18 and 30 (P3) and 43 (P4), the stock SWB transition rule admits only `00` at physical word bits 8–9. Under that rule each case excludes `01`, `10` and `11`. These six bit predictions have no independent transmitter labels in this case. Elsewhere the underlying rule has disagreed with two text-supported P2 labels. [Named bit evidence](score.json) · [Previous disagreements](../../swb-transition/README.md)

Across the interval, 166 expected INACTIVE/BWE high nibbles could be read directly. All 166 equalled `C`, including 43 at P2. No AUDIO case was eligible. These forecasts and their observations came from the same recording. [Sealed mode forecasts](https://github.com/skgsara/kcbs-drm/commit/937a8a6fd1beb6c596745f5c08fb931eac429203)

| Archived 3205 kHz interval | One MLC iteration | Four MLC iterations |
|---|---:|---:|
| Native header- and CRC-valid packets of 576 checked | 378 | 381 |
| Assigned packet coordinates | 189 | 209 |
| Assigned complete data units | 41 | 46 |
| Complete groups | 6 | 8 |

Every shared assigned packet and complete data unit agreed. Of the 20 gains, 18 wires were already CRC-valid in the earlier native rows and gained a coordinate. The other two wire identities were absent from that earlier valid set. Four iterations added groups 43873090 and 43873094 and retained all earlier complete groups on this interval. In a separate 6140 kHz trial with two receiving sites, both stations independently confirmed the corrected wire bytes of counter 43945704. [This interval's wire comparison](transport.json) · [Independent 6140 kHz control](../transport-mlc4/README.md)

A separate replay of this exact minute recovered 146 CRC-valid FAC blocks and 48 CRC-valid SDC blocks. Each advertised the same single packet-data service. [Five-window service and packet audit](../../standard-service-audit/README.md)

## Replay

The published FLAC losslessly holds original complex samples [4,320,000, 5,040,000) at 12 kHz. Its SHA-256 is `e2c0ad1d6a214f8da14c5c9c4da2159e32b5a035fc6d2f61d3fb8bfdbe0c586d`. The decoded interleaved little-endian int16 PCM digest is `ec5869c354d8b7782e75308fee467620b997366ab931a2f68f4c611c43d5e65a`. The nominal time range from the filename is 12:21:02–12:22:02 UTC on November 27. The WAV has no receiver clock timestamps. [IQ excerpt](3205kHz-360-420s-iq12.flac) · [Input hashes and both receiver runs](reception.json)

Set `KCBS_DREAM` to the pinned executable named in the protocol, and run from the repository root. The published MSCs also permit replay from the field-check stage alone.

```sh
case_dir=examples/nov28/clear-evs-controls/iq-mlc4
out=$(mktemp -d)
python scripts/demod_iq_window.py "$case_dir/3205kHz-360-420s-iq12.flac" "$out/rf4" \
  --start 0 --seconds 60 --reception-profile wiener --mlc-iterations 4
cmp "$out/rf4/msc.bin" "$case_dir/mlc4-msc.bin"
python "$case_dir/../iq/check.py" freeze "$case_dir/mlc4-msc.bin" "$out/check"
cmp "$out/check/forecasts.json" "$case_dir/forecasts.json"
python "$case_dir/../iq/check.py" score "$case_dir/mlc4-msc.bin" "$out/check" \
  7de2fbe6418376526be48c23834ea7278fe706a19db4dc45f94ed5e9c8e0102e
cmp "$out/check/score.json" "$case_dir/score.json"
python "$case_dir/compare_transport.py" --out "$out/transport.json"
cmp "$out/transport.json" "$case_dir/transport.json"
```
