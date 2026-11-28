# First-position calibration on seven November 27 recordings

The four mode-octet and payload-31 pairs seen on November 19 also occurred in 87 first-position slots in the November 27 packet archives. We recorded the slot coordinates and predictions using those two directly received octets before comparing them with the earlier clear-frame exports. Of 87 slots, 28 had a supplied word, 55 had an explicit erasure and four fell outside the export. All 28 supplied words matched the predicted two bits and agreed with every directly readable octet in their slot (176 bits per word). [All 87 observations](nov27-p1-control.tsv) · [Capture sources, clocks and file digests](nov27-p1-control.sources.json)

| Received mode / p31 | Predicted b8–b9 | Received slots | Matching / supplied P1 words | Matching / supplied with a text witness at column 0 |
|---|---|---:|---:|---:|
| 60 / 3A | 00 | 7 | 2/2 | 2/2 |
| 60 / B6 | 00 | 22 | 10/10 | 8/8 |
| 61 / 6C | 01 | 35 | 10/10 | 10/10 |
| 61 / 4C | 01 | 23 | 6/6 | 6/6 |

The 26 individually witnessed slots span 25 counters, 25 ordinary text-record occurrences and 22 distinct UTF-16LE body fragments. In each counter, at least one byte for column 0 falls within a record's CRC-covered header or body. Two more supplied words matched at 09:56 UTC without that evidence. Those two are the difference between the last two columns. These records support the earlier receiver's clear-word interpretation. The sender's original EVS words for these coordinates are unavailable.

The 06:17, 09:56, 11:05 and 13:17 UTC captures had been used in earlier aggregate P1 transition scoring. They contributed 27 of the 28 comparisons. The additional 09:44, 12:09 and 13:58 captures yielded nine predictions and one supplied comparison. At 09:44, counter 43865561, slot 40, the stored pair was `00` for `60/B6`. Column 0 occurs at offsets 16, 32 and 48 of the ordinary record starting at 43865560 phase 2, whose transmitted CRC was `95B7`. [Earlier transition comparisons](../swb-transition/README.md#where-the-on-air-labels-disagree)

The two `60/3A` observations came from different recordings and different text bodies. At 09:56, counter 43867026 slot 44, the supporting record started at 43867025 phase 1, CRC `BF11`. At 11:05, counter 43869411 slot 40, it started at 43869410 phase 2, CRC `BB4C`. The first-position results calibrate the relationship at these earlier coordinates. They supply no clear reference for position two of counter 43288730.

The TSV suffices to recompute the table, exclusions and record counts. The witness column groups entries by text record. Each entry gives the start counter, phase, transmitted CRC, length of the CRC input, comma-separated offsets within that input, and SHA-256 of the UTF-16LE body. Empty observation and direct-match cells indicate an unavailable reference. Rechecking the RF octets, the original G.192 labels or the record CRCs requires the archived inputs listed in the source receipt. The 06:17 example is in this repository. The member handoffs and other IQ-derived exports are separate.
