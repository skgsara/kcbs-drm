# Test of an EVS field at payload offset 30

Use the 7L4IOU Edogawa 3205 kHz IQ recording from November 27 at
21:26 UTC, SHA-256 `d96c3f22638c45ef1ef966a022f03afb29032b0fbb70d9e116783b415d40c8d0`.
Use the full original recording of 8,640,000 complex samples at 48 kHz.
Keep the existing receiver settings and pool only CRC-checked transport
packets. Previous work inventoried this recording's mode octets and
applied its paired-reception test to counter 43900392.
[Recording and receiver details](../paired-43900392/comparison.json)

Exclude 43900392, sort the remaining 73 complete counters and select
their median, 43900403. Select by counters and phase availability before
opening any application fields for this experiment. Report all 60 slots
at the selected counter, including any abstentions. Also count coverage
on the full set of 73 complete counters.

In ordinary 13.2 kb/s SWB GENERIC or VOICED ACELP with TBE, use the
standard decoder's two upper-frequency-limit checks. The signal inputs
are the mode and the 13 directly transmitted bits immediately around
payload byte 30. In MSB-first word coordinates these are bits 243–247
and 256–263. Use only signalling indices 10, 11, 19 and 20 with the
TBE selector. Compute the expected count of alternatives each context
can reject from the reference code's entire synthetic parameter space
before evaluating any radio inputs. Count eligible fields by position
and how many alternatives survive. Keep unscored bytes as erasures.
This experiment assumes the ordinary EVS layout for these modes.
