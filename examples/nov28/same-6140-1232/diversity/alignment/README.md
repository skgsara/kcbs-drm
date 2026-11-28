# Aligning the 12:32 UTC receiver records

The November 28 Edogawa and Yokohama receivers each recorded 6140 kHz. The two original MSC files contain 218 and 220 records, respectively. Of the distinct physical packets that passed the expected header and transmitted CRC at both stations, all 444 occurred at a unique row for each station. They locate 135 row pairs across 14 continuous runs. For every pair, the zero-based Yokohama row number equals the Edogawa row number plus three. The comparison uses only those witnessed pairs. [Edogawa MSC](../../edogawa-msc.bin) · [Yokohama MSC](../../yokohama-msc.bin) · [Sealed row map](row-pairs.json)

The split was fixed on the original Edogawa row index before comparing new decoder results. Edogawa rows 0–71 supply 55 witnessed calibration pairs. Rows 72–83 separate the sets. They contain seven witnessed pairs. Rows 84 onward supply 73 evaluation pairs. No known counter occurs in both calibration and evaluation. This selection requires at least one packet received correctly at both stations, so its reception conditions are selective. [Selection rule](protocol.json) · [Source digests and counts](receipt.json)

The 73 evaluation pairs contain 292 physical packet locations. At 255 locations both original receivers passed the packet header and CRC, at six only Edogawa passed, and at 29 only Yokohama passed. Neither receiver passed packet ordinal 0 at native row pairs 106/109 and 117/120. The other packet ordinals establish the location of those two opportunities in the files. Both stations lacked absolute counter and phase assignments for these two rows.

## Reproduce from the public files

The checker needs Python 3.10+ and NumPy. The two MSC dumps preserve the original wire bytes. Each station’s packet snapshot supplies its previously assigned coordinates. Comparing each accepted packet’s 179-byte body and ordinal with the original CRC-valid wire records gives exactly one local row for every accepted packet. The checker verifies the source hashes against the published station receipts, reconstructs every field of the sealed row map and emits the receipt below. The original IQ is available for an additional receiver replay. [Edogawa snapshot](../../edogawa-packets.npz) · [Yokohama snapshot](../../yokohama-packets.npz) · [IQ and MSC replay](../../iq/replay.json)

Run these commands from the repository root.

```sh
case_dir=examples/nov28/same-6140-1232
align_dir="$case_dir/diversity/alignment"
python "$align_dir/check.py" --case-dir "$case_dir" --row-map "$align_dir/row-pairs.json" > /tmp/6140-alignment.json
cmp /tmp/6140-alignment.json "$align_dir/receipt.json"
```
