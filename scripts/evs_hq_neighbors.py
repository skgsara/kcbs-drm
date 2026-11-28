"""Test a central SWB HQ class hypothesis against an independently carried successor bit."""
from evs_core_history import COORDINATES, received_mode


def eligible(previous_mode, current_mode, successor_top_seven):
    # The third word's b7 is held out during selection of every eligible triple.
    return previous_mode == 0xF9 and current_mode == 0xF8 and successor_top_seven == 0x7C


def check_successor(observed_bit):
    # A new central transient after a nontransient word also forces the next
    # word to be transient in the stock sender's uninterrupted SWB HQ branch.
    return dict(successor_b7=observed_bit, expected_if_central_transient=0,
                allowed_central_b8=[0] if observed_bit else [0, 1],
                outcome="transient_excluded" if observed_bit else "inconclusive")


def hq_neighbors(slots):
    cases = []
    for previous, current, successor in zip(slots, slots[1:], slots[2:]):
        if (previous["counter"] != current["counter"] or current["counter"] != successor["counter"]
                or current["slot"] != previous["slot"] + 1 or successor["slot"] != current["slot"] + 1):
            continue
        future = received_mode(successor)
        if future is not None and eligible(received_mode(previous), received_mode(current), future >> 1):
            cases.append({key: current[key] for key in COORDINATES} | check_successor(future & 1))
    return dict(eligible=len(cases), transient_excluded=sum(r["successor_b7"] for r in cases),
                target_word_bit=8, withheld_successor_word_bit=7,
                basis="Continuous ordinary 13.2 kb/s SWB HQ coding across three adjacent words in one group.",
                slots=cases)
