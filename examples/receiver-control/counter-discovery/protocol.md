# Receiving complete clear test groups without a counter range

The test asks whether a file-only receiver can find complete EVS groups in a fresh IQ recording when its first counter, payload duration and sender ledger are withheld. Its service preset is the authored, declared-clear `EF0201` / `DRM IQ TEST` signal. The on-air KCBS-2 service uses a different payload format. Its full-word milestone remains a separate field test.

## Receiver and input

Develop against the published 40-group clear fixture. Freeze the receiver on the public branch before the sender chooses the holdout chronology. The receiver gets only the lossless IQ file, the finite-input signalling-enabled Dream executable, and a new output directory. Fix the nominal tuning, Wiener reception and one MLC iteration as in the original clear fixture. The receiver consumes the file once, verifies the FAC/SDC service description, and catalogs complete groups from the native MSC row sequence.

A complete word export requires three consecutive rows with phases 0, 1, 2, the four expected packet headers and CRCs per row, and a valid CRC for each enclosing data unit. Read the group counter from phase 0. Identify acquisition and drain guards by their serialized contents in the authored transmitter format. Keep repeated counter occurrences distinct and preserve their order across an unsigned counter rollover. An incomplete reception supplies no group file in this mode. There is no assumption about the number of counters that elapsed across a discontinuity. The original receiver's explicit-range mode remains available for partial-word and partial-packet coverage.

## Held-out transmission and scoring

Use a contiguous selection of the previously published stock EVS encoder output in a fresh file-only modulation. Choose the selection and new counters after the receiver freeze. Include a counter rollover and a repeated intact group. Damage one stored packet checksum in a different group. The stock modulator supplies its ordinary acquisition and drain guards. The sender retains its original clear words, counter order and damage ledger. Reusing known encoded audio tests discovery and framing with new counters and packet chronology.

Seal the receiver report, catalog and hashes of all exported group files before comparing them with the sender ledger. Score every emitted word in all four positions and report missing occurrences separately. Check the chronological sequence including the duplicate, the unsigned rollover, the failed packet and boundaries with the guards. Wrong words, missing intact groups, groups emitted for guards or for the damaged group, and any extra occurrences must be reported. Source code and the generation parameters released after scoring must allow a second operator to regenerate the same IQ samples.
