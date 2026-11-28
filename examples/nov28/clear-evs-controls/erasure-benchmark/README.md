# Blind six-byte EVS erasure benchmark

Copying the preceding P1 word supplied the **six exact missing P2 bytes in 2 of 3,060 words** in the held-out official floating-point streams. It also succeeded on **2 of 3,120** words from a separate fixed-point speech encode. Neither method that copied bytes recovered all 15 P2 words in any group. All six public field checks left the target bytes tied throughout both cohorts. This experiment used known 3GPP EVS originals, with complete P1 words available even where a field receiver might lack them. [Protocol](protocol.md) · [Prediction seals](seals.json)

| Original source | Full groups | All six bytes correct, copy every P1 | All six bytes correct, copy only on exact mode match | Words withheld by mode gate | Complete 15-word groups recovered |
|---|---:|---:|---:|---:|---:|
| Nine held-out TS 26.443 floating-point coded files | 204 | 2 / 3,060 | 2 / 1,543 | 1,517 | 0 |
| TS 26.442 fixed-point encode of Annex A speech input | 208 | 2 / 3,120 | 2 / 1,511 | 1,609 | 0 |
| Nine previously examined TS 26.442 fixed-point files | 204 | 29 / 3,060 | 28 / 1,547 | 1,513 | 0 |

The numerator of each word score counts matches across all 48 erased bits. Its denominator counts guesses, so the abstentions from the mode gate are shown separately. The 29 fixed-point matches include one with different donor and target modes. Both floating-point successes occur at slot 873 in different bandwidth encodings. The two Annex successes occur at slots 2901 and 4901. A copy guess carries no confidence estimate. The six frozen field checks found zero contradictions in the visible fields and made zero target-bit calls. [Floating-point results](float.json) · [Separate speech results](annex.json) · [Earlier fixed-point comparison](fixed.json)

| Original source | Correct bytes, copy every P1 | Correct bits, copy every P1 | Correct bytes, equal modes only | Correct bits, equal modes only |
|---|---:|---:|---:|---:|
| Held-out float | 168 / 18,360 | 75,321 / 146,880 | 110 / 9,258 | 38,039 / 74,064 |
| Annex speech | 226 / 18,720 | 77,758 / 149,760 | 122 / 9,066 | 37,381 / 72,528 |
| Earlier fixed | 328 / 18,360 | 75,889 / 146,880 | 259 / 9,282 | 38,760 / 74,256 |

## What the comparison establishes

All 616 complete original 60-word groups have distinct fingerprints. The nine matching float and fixed files use the same underlying recordings. Their scores measure two implementations on those recordings. The separate Annex A input contains 30 annotated speech excerpts. Its first eight groups precede the first speech annotation and the ninth straddles its beginning. The preregistered result includes all full groups. All coded words were present in each cohort. We kept the time axis intact and omitted 240 trailing slots from each nine-file cohort and 22 from Annex A. [Source receipt and encoder settings](corpus.json)

A separate stock GSC example gives **two different correct answers to the same observations**. Its two 60-word groups have identical visible bytes and differ at one bit of P2 payload octet 24. Even revealing every other bit in all 60 words leaves both originals possible. That example establishes a specific ambiguity. The on-air service also carries transport observations and relationships between its 15 words at a position. The public codec-only test omits them. [Reproduce the two original encodings](doublet/README.md)

## Replay

Use Python 3 and NumPy. From the repository root, the source retriever verifies the archive members and regenerates the Annex stream using the TS 26.442 fixed-point reference encoder. Set `EVS_ENCODER` to the executable from that build. The output directory below is fresh. Intermediate files contain the original standards data and should remain local. [Reference codec build](../README.md) · [Source retriever](fetch_corpus.py)

```sh
case_dir=examples/nov28/clear-evs-controls/erasure-benchmark
out=$(mktemp -d)
python "$case_dir/fetch_corpus.py" "$out/input" --fixed "$EVS_ENCODER"
python "$case_dir/bench.py" prepare "$out/float" "$out/input/float/"*.COD
python "$case_dir/bench.py" predict "$out/float/visible.json" "$out/float/decisions.json"
python "$case_dir/bench.py" score "$out/float/decisions.json" \
  beea541846ce968407c3b0db1a95e056f0725d6fc0ad39ebe8ef53eec00ea8a5 \
  "$out/float/answers.json" "$out/float-result.json"
cmp "$out/float-result.json" "$case_dir/float.json"
```

For Annex A, pass the single `$out/input/annex/annex-a.192` file to `prepare`, then use the Annex seal and compare with `annex.json`. For the earlier fixed-point cohort, fetch the nine files with the [original retriever](../fetch_reference_members.py), then pass `testvec/testv/bitstreams/*/*.COD` under that output directory in shell-glob order. Use ordinary bytewise filename ordering (`LC_ALL=C`) for reproducible source indexing. The predict command takes only a projected observations file; scoring requires the previously recorded prediction digest and the separate answers file. [Method implementation](bench.py) · [All three seals](seals.json)
