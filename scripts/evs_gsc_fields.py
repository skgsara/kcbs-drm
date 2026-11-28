"""Predict and check directly transmitted super-wideband GSC fields at 13.2 kb/s."""
from collections import Counter

from evs_core_history import COORDINATES, received_mode


FIELD_DEFINITIONS = {
    "audio_noisy": {
        "word_bits": [40, 41], "inputs": ["mode octet"],
        "basis": "Stock encoder's ordinary AUDIO bandwidth-extension choice.",
    },
    "inactive_nibble": {
        "word_bits": [40, 44], "inputs": ["mode octet"],
        "basis": "Empirical INACTIVE/BWE pattern from the labelled broadcast archive.",
    },
    "noisy_pitch_fill": {
        "word_bits": [223, 224], "inputs": ["mode octet", "word bits [40,45)"],
        "basis": "Stock noisy AUDIO/TBE positive-pitch pulse codebook and range-coder padding.",
    },
}


def mode_predictions(mode):
    if mode >> 3 == 13:
        yield "audio_noisy", int((mode & 4) == 0)
    elif 0x74 <= mode <= 0x77:  # INACTIVE with frequency-domain extension
        yield "inactive_nibble", 12


def has_noisy_pitch(mode, p4):
    return (0x68 <= mode <= 0x6B and p4 is not None and p4 & 0x80 != 0
            and 1 <= ((p4 >> 3) & 15) <= 10)


def observed_field(name, octet):
    if octet is None:
        return None
    if name == "audio_noisy":
        return octet >> 7
    if name == "inactive_nibble":
        return octet >> 4
    if name == "noisy_pitch_fill":
        return octet & 1
    raise ValueError(f"unknown GSC field {name!r}")


def projected_payload(tokens, offset):
    token = tokens[1 + offset]
    return None if token in ("??", "--") else int(token, 16)


def gsc_fields(slots):
    cases = []
    totals = {name: Counter(match=0, mismatch=0, unavailable=0)
              for name in FIELD_DEFINITIONS}
    for row in slots:
        mode = received_mode(row)
        if mode is None:
            continue
        predictions = list(mode_predictions(mode))
        if not predictions:
            continue
        tokens = row["octets"].split()
        p4 = projected_payload(tokens, 4)
        if has_noisy_pitch(mode, p4):
            predictions.append(("noisy_pitch_fill", 0))
        for name, expected in predictions:
            target = projected_payload(tokens, 26) if name == "noisy_pitch_fill" else p4
            observed = observed_field(name, target)
            if observed is None:
                outcome = "unavailable"
            else:
                outcome = "match" if observed == expected else "mismatch"
            totals[name][outcome] += 1
            case = {key: row[key] for key in COORDINATES}
            case.update(check=name, mode=mode, predicted=expected, observed=observed, outcome=outcome)
            if name == "noisy_pitch_fill":
                case["pitch_band_index"] = (p4 >> 3) & 15
            cases.append(case)
    return {
        "scope": "Half-open MSB-first word bit ranges. Each prediction excludes all other field values. "
                 "Direct observations and received-word erasures are retained even on a mismatch. "
                 "A slot may support multiple checks. Ineligible slots are omitted.",
        "fields": FIELD_DEFINITIONS, "by_check": totals, "slots": cases,
    }
