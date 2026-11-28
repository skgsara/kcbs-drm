# Two member-reported counters from November 28

The team has seen proposed field values for **43916890** and **43917329**. Treat both IDs as previously discussed in future blind evaluations. The frozen [13:47 inventory](edogawa-audio-branch/history-origins.json) contained 14,955 IDs and included neither. The two member handoff archives checked here also had no packet rows for either counter. These observations do not establish a reception time for the screenshot or supply a reference answer.

The member reported that six of seven candidate prefixes without a transmitted text CRC gave plausible Korean weather text in a phase withheld from reconstruction. One of these six had been examined before. Among the five newly examined groups, 43917329 had four remaining candidates for the position-two mask at payload offset 15, and the same candidate at offset 30 ranked first for the entire segment and for both halves. At 43916890 seven candidates remained at offset 15, and the two halves favored different values at offset 30. The reported reductions depend on the proposed text prefixes. The whole-segment score reuses both halves.

An older bulletin provides an example of the distinction between understanding a forecast and reading its exact characters. Its verified November 25 text gives Hyesan as `혜산시 -11℃정도로 예견됩니다`. Replacing `-11` with `-10` leaves a grammatical forecast and changes the transmitted character. The November 25 number belongs to that bulletin. [Original Korean text, item 2](../../contrib/kcbsdrm/reference/bulletin_2026-11-25_all.txt#L21-L22)

The original target packets, the bytes of the withheld record, and its transmitted text CRC, if present, would allow a separate check of the reported text. There are currently zero independently verified new clear EVS words from these two reports.

### What the later count for 43917329 measures

The member subsequently reported 208 surviving **joint** values for the bytes at payload offsets 15 and 18. With 256 choices at each of offsets 21, 24 and 27, the arithmetic gives exactly `208 × 256³ = 3,489,660,928`. It assumes the proposed text prefix and a fixed value of `0x35` at offset 30. The number refers to one position-two mask reused across the group's 15 slots. We could verify the multiplication from the screenshot. The inputs required to reproduce the 208 pairs or confirm either assumption remain unavailable here.

This count supplies no measurement of a master key's length, a mask-generation algorithm, or how a receiver obtains its parameters. A receiver that plays the service could in principle use transmitted information, preconfigured information, or both. The available observations are compatible with all three possibilities.

We subsequently audited six public GSC and ACELP field checks on nine official EVS test sequences. They retained all 1,098 known words on which they excluded an alternative value. The group's reported filter would require its own known-answer comparison. [Official-word audit and its coverage](clear-evs-controls/README.md)

### Pricing a complete pass

On November 28, 2026, the AWS public On-Demand Linux price for a Northern Virginia `c7i.2xlarge` was $0.357 per instance-hour. For a full enumeration, compute cost in dollars is the candidate count divided by the measured whole-instance throughput per second, divided by 3,600, multiplied by the hourly price. A candidate here means one proposed answer evaluated across the group's 15 affected words, including scoring. These example rates are hypothetical. Storage, data transfer and retries are additional. [Official regional AWS pricing](https://b0.p.awsstatic.com/pricing/2.0/meteredUnitMaps/ec2/USD/current/ec2-ondemand-without-sec-sel/US%20East%20%28N.%20Virginia%29/Linux/index.json)

| Complete candidates per second on one instance | 3,489,660,928 candidates | 35,000,000,000 candidates |
| ---: | ---: | ---: |
| 100 | 9,693.5 hours · $3,460.58 | 97,222.2 hours · $34,708.33 |
| 1,000 | 969.4 hours · $346.06 | 9,722.2 hours · $3,470.83 |
| 10,000 | 96.9 hours · $34.61 | 972.2 hours · $347.08 |

The project's local timing of 12,480 known EVS words in 6.79 seconds measures ordinary decoding and comparison with reference PCM. The sustained AWS rate for a complete candidate evaluation is unknown. In the group's held-out AM comparison with four alternatives, the correct value ranked uniquely first in 3/15 cases at byte 24 and 1/15 at byte 27. In a separate stock-encoder test, changing the preceding audio changed all 70 complete EVS words during an identical digital-silence suffix. A spending decision needs evidence that the scoring method can distinguish the actual encoded word on held-out groups, including how often it returns an ambiguous result, as well as a throughput measurement. [AM control](four-frequency/README.md) · [Silence comparison](clear-evs-controls/stock-inactive/README.md) · [Ordinary decoder timing](clear-evs-controls/decoder-timing.json)
