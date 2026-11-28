# Stage-0 registration for the repaired DEV comparison and live sets

`registration.json` (SHA-256 `a17a823a4f8baf507e832090c64767d1a1e1819828844ac4dd2b96b141c7cb13`)
was written at 2026-11-28 17:24 UTC, before any stage it governs produced output.
It fixes the following:

- the input hashes;
- the union of DEV tuning groups;
- the 200-group common DEV subset (`common_subset.json`), with each in-sample
  method flagged;
- the leave-one-capture-out threshold rule;
- the live-set rule (fill crib ≥15/16, CRC-valid data units only);
- the oracle-decode conditions;
- the kill criteria.

The same thresholds govern the prospective acquisition in
[`../../../prospective-acquisition/`](../../../prospective-acquisition/). This
commit precedes the labelling of any prospective group.
