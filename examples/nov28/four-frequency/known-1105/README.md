# November 27, 11:05 UTC programme comparison

The receiver handoff for counter `43869343` contains a full-length, demodulated **3250 kHz AM** track and a **3205 kHz DRM** first-position stream from the same 240-second RF reception. The frozen comparison reproduced their programme alignment at **−3.12 s** on a 10 ms grid. The AM feature center occurs 3.12 s earlier in its file than the corresponding DRM feature center does in its replay. This result applies to this recording. The separate 06:17 UTC recording used 3205 and 6140 kHz DRM.

Run with Python 3, NumPy, SciPy, a stock floating-point TS 26.443 `EVS_dec` executable and the locally extracted `kcbs2-3205-3250-handoff` directory. The script checks SHA-256 pins for `capture.json`, `replay/known-first-position.192.gz` and `audio/3250-AM-12k-mono.wav`. It writes JSON to standard output. Exit codes are 0 for a passing programme comparison, 1 for a completed comparison below threshold, and 2 for input or execution errors. [Checker](check.py) · [Reference output](expected.json)

```sh
python examples/nov28/four-frequency/known-1105/check.py \
  /path/to/kcbs2-3205-3250-handoff --decoder /path/to/EVS_dec > result.json
```

The decoder runs once from reset at 16 kHz on the entire archived G.192. All 1,545 supplied words occupy position 1. In a prior receiver audit, each matched the received packet bytes and frozen text-CRC-supported prefix. A separate instrumented run recorded normal decoder calls with no bad-frame or bit-error indication on all 1,545. This portable check verifies the pinned archive identity and G.192 layout, redecodes it and reports whether the stock PCM hash matches that audited run. It scores 16 ms windows centered inside supplied words. All 10,155 explicit erasure slots are excluded from the score. Decoder memory on a supplied slot still reflects the preceding erasures.

The metric averages per-band Pearson correlation across nine log-energy bands between 200 and 3,400 Hz. The first 45% of elapsed DRM time selects a lag and a drift from 0, ±100 and ±200 ppm. The last 45% tests that setting, with a 10% gap. A pass requires training and test scores of at least 0.28, each test half at least 0.15, and the test score at least 0.03 above the 99th percentile of 199 cyclic displacements of the held-out AM observations.

| Measurement | Observations | Result |
| --- | ---: | ---: |
| Training at the fitted lag, 0 ppm | 752 paired out of 791 eligible | 0.504 |
| Held-out comparison | 521 | 0.401 |
| First and second test halves | 260 and 261 | 0.448 and 0.359 |
| Held-out timing controls | 199 displacements | 0.051 at the 99th percentile, 0.058 maximum |
| Counter `43869343`, excluded from calibration | 15 P1 words | 0.653 |

Removing all 15 target words before fitting retained the same lag and drift with 737 paired training observations. The target score describes that group. Programme agreement and decoder status do not identify any unknown second-position payload bits. Scores from another floating-point build can vary; the reference output includes the raw PCM SHA-256.
