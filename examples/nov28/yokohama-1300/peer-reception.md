# Independent 6140 kHz check for the opening of the 13:00 UTC window

The scheduled primary uses only the Yokohama 3205 kHz IQ and the original receiver at `c7fab069`. Its first complete group and partial control are selected by the published procedure. This additional recording tests whether another site and frequency carried the same data at those coordinates. [Primary protocol](protocol.md)

On November 28, request 120 seconds of 6140 kHz IQ from the public 7L4IOU receiver in Edogawa at 13:00 UTC. Use the 48 kHz stereo PCM16 recorder at `8c9a9edd` with per-packet timing. Preserve the original samples, the station timing and their hashes, including any partial capture. Use the actual station times when reporting overlap. A failed acquisition or a capture with no CRC-valid output is a reportable outcome.

Seal the Yokohama result before comparing it with the peer data. Demodulate the peer file from sample zero using the finite-input Dream binary identified in the primary protocol, with nominal tuning, the Wiener profile and one MLC iteration. Read the packet headers and CRCs independently using receiver revision `c7fab069`. Compare the 179-byte packet bodies by counter, phase and physical packet ordinal, and check each available complete 716-byte data unit and its transmitted CRC. Report disagreements and missing peer coordinates, including when the primary falls outside the 120-second reference. A shared complete group permits comparison of the mode and 21 directly transmitted payload octets at all 60 slots. Record masked clear values as unresolved.

When the primary is absent, report the independent peer's reception on its own frequency with a null primary comparison. The peer recording cannot select or replace the scheduled primary.
