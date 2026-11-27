# Held-out field test on counter 43005013

Use the median of the 109 complete counters in the November 15 transport
inventory, row 55 in ascending counter order. The inventory was public
before development of these field checks. It contains counters and DU
CRCs only. The selected counter is 43005013, with phase CRCs A705, 48C7
and 8E5F. Retain it for every outcome, including zero applicable fields.
[Inventory](../complete-counters.csv)

The receiver input is the entire 199.8933-second 3205 kHz recording of
November 15 at 10:58 UTC, SHA-256
`39d8c862b82af3797531f4df53c374c220f89e6d95e8c1746000c445633959f0`.
Use all 2,398,720 stereo IQ pairs at 12 kHz, resampled to 48 kHz, and
the original one-pass Wiener settings (MLC iterations 1, metric 0,
frequency interpolation 2, time interpolation 1). Run the local offline
Dream build with SHA-256
`3f24768b2a3075ad8cd4be6ada18dadaf695f69ffbb90b6fd38a175459471a82`.
Extract CRC-checked packets and DUs. The only selected application input
is the directly received projection of the three in-order DUs of this
counter. The only prior mode a check can use is the immediately
preceding received slot inside this group.

Use ordinary uninterrupted 13.2 kb/s primary EVS framing as the model.
Word bit 0 is the mode byte's most significant bit. For a current
MDCT word, indices 0–20 in the previous mode imply an ACELP core, and
indices 29–31 imply a transform core. Abstain on a missing predecessor
or indices 21–28. For TCX20, predict word bit 8 as 0 after ACELP and 1
after a transform core. For HQ, predict the directly received word bit 6
as 1 after ACELP and 0 after a transform core. Exclude the current
flag from that prediction and compare it afterward.

Apply three same-word checks independently. For a received mode of
0xF9, the first bit of a non-switching super-wideband HQ class is 1.
The reference encoder emits classes 00, 01 and 10, which predicts word
bit 8 as 0. For mode index 8 (wideband GSC AUDIO), require bit 40 to be
0. For index 14 (super-wideband GSC INACTIVE), require the unsigned
four-bit value at bits 44 through 47 to be at most 10.

Report every eligible field and rejected alternative, abstentions and
full words by position. An unchecked prediction from standard encoder
behavior remains conditional. A successful comparison against a
directly received field checks only that field. An independent local
control uses the existing 48-second synthetic PCM, reversed at sample
boundaries, sign-inverted and clipped to signed 16-bit range, encoded
from fresh state. Score its original G.192 bits and deliberately wrong
values separately. Keep all 60 slots when scoring either data set.
