"""Check conditional 13.2 kb/s EVS core-switch signalling using adjacent received mode octets."""
from string import hexdigits


COORDINATES = ("slot", "counter", "phase", "cycle", "position")
OUTCOMES = ("abstain", "hq_match", "hq_mismatch", "tcx_conditional")


def received_mode(row):
    if row["receipt"] != "received_du":
        return None
    token = row["octets"].partition(" ")[0]
    if len(token) == 2 and all(char in hexdigits for char in token):
        return int(token, 16)
    return None


def previous_core(mode):
    if mode is None:
        return None
    index = mode >> 3
    if index <= 20:
        return "ACELP"
    if index >= 29:
        return "MDCT"
    return None


def core_history(slots):
    """Score one ordered projector group. A gap or group boundary interrupts adjacency."""
    rows = []
    total = dict.fromkeys(("slots", *OUTCOMES), 0)
    by_position = {str(p): total.copy() for p in range(1, 5)}
    last_row = None
    last_mode = None
    for row in slots:
        mode = received_mode(row)
        result = {name: row[name] for name in COORDINATES}
        result.update(outcome="abstain", reason=None, target_word_bit=None, predicted=None, observed=None)
        prior = previous_core(last_mode)
        adjacent = (last_row is not None and last_row["counter"] == row["counter"]
                    and last_row["slot"] + 1 == row["slot"])
        if mode is None:
            result["reason"] = "current_mode_unavailable"
        elif not adjacent:
            result["reason"] = "no_adjacent_predecessor"
        elif last_mode is None:
            result["reason"] = "previous_mode_unavailable"
        elif prior is None:
            result["reason"] = "previous_signalling_index_outside_scope"
        elif (mode >> 3) < 29:
            result["reason"] = "current_signalling_index_outside_scope"
        elif mode & 0x04:  # TCX20: enc_prm.c writes last_core != ACELP_CORE.
            result.update(outcome="tcx_conditional", target_word_bit=8, predicted=int(prior == "MDCT"))
        else:  # HQ: the lower two current mode bits played no part in choosing this branch.
            predicted = int(prior == "ACELP")
            observed = (mode >> 1) & 1
            result.update(outcome="hq_match" if predicted == observed else "hq_mismatch",
                          target_word_bit=6, predicted=predicted, observed=observed)
        for counts in (total, by_position[str(row["position"])]):
            counts["slots"] += 1
            counts[result["outcome"]] += 1
        rows.append(result)
        last_row, last_mode = row, mode
    return dict(scope="For 13.2 kb/s EVS, word bit 0 is the mode MSB. HQ bit 6 is directly received. "
                      "TCX20 bit 8 is a conditional expectation from the preceding core. "
                      "Only adjacent received modes within the same group enter the check.",
                total=total, by_position=by_position, slots=rows)
