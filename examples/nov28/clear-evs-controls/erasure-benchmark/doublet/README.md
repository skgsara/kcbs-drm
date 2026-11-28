# Can the other 59 words identify this GSC bit?

Two genuine stock 13.2 kbit/s SWB GSC encodes have the same 1,560 visible octets under the benchmark projection. In both streams the 60-word group spans slots 180–239. At slot 205 (P2, local slot 25), payload octet 24 is `67` in one original and `77` in the other. Only physical bit 203 differs. Revealing all 59 neighboring words and the other 263 bits of slot 205 still gives identical inputs. The original 205 preceding and 34 following encoder words also match. [Test selection](../protocol.md) · [Original synthetic inputs and sender hashes](../../../../nov27/validation/swb-gsc/sender-pairs.json)

The same observed bits therefore admit both sender labels. A deterministic predictor given these observations must return the same answer for both. This preselected example establishes ambiguity for one bit in one pair. Its frequency in other sources and the value of additional observations remain open.

## Replay

Run from the repository root with Python 3.10+, NumPy and the stock TS 26.443 floating-point encoder. The script regenerates both synthetic PCM inputs and uses the existing sender helper to verify their PCM, G.192 and EVS storage SHA-256 digests. [Reference build instructions](../../../evs-state-control/README.md)

```sh
case_dir=examples/nov28/clear-evs-controls/erasure-benchmark/doublet
python "$case_dir/check.py" --encoder work/evs_gcc_independent/EVS_cod > /tmp/evs-doublet.json
cmp /tmp/evs-doublet.json "$case_dir/expected.json"
```

Each partition is the concatenation of its selected octets in slot order, then wire order within each word. The visibility schedule retains the mode octet at every position. It supplies 33 octets at P1, 27 at P2, and 22 each at P3 and P4. The common digest for the observable octets is `7b6856eb00d7afc07d521f5323452f59c7d98161c773a8ade0db9a05476b7a5b`. The stronger comparison serializes the 15,839 remaining group bits as ASCII digits in MSB-first wire order, omitting only bit 203 of slot 205. Its common digest is `6faf0a50ece0eb0744cdc731345f80ecd9ad66cd7e9e33ed6c9bba70a34c1378`. The receipt also includes separate hashes for the two 420-octet hidden partitions and their 90-octet P2 subsets. [Exact results](expected.json)
