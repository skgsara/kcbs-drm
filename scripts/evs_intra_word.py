"""Field constraints for ordinary 264-bit EVS words, in MSB-first wire order."""
from evs_core_history import COORDINATES, received_mode


def hq_class_restriction(mode):
    """Return the allowed high two bits of payload octet 0, or None if unrestricted."""
    if mode == 0xF9:
        return (0, 1)
    if mode in (0xFA, 0xFB):
        return (0, 1, 2)
    return None


def intra_word(slots):
    rows = []
    for slot in slots:
        mode = received_mode(slot)
        if mode is None:
            continue
        result = {name: slot[name] for name in COORDINATES}
        allowed_pairs = hq_class_restriction(mode)
        if allowed_pairs is not None:
            # TS 26.443 hq_lr_enc.c emits classes 00, 01 and 10. F9 already
            # carries the first class bit. FA/FB carry both in the payload.
            if mode == 0xF9:
                bounds, allowed = [8, 9], [0, 0]
            else:
                bounds, allowed = [8, 10], [min(allowed_pairs), max(allowed_pairs)]
            result.update(check="swb_hq_class", word_bits=bounds, allowed=allowed,
                          observed=None, outcome="conditional")
        elif mode >> 3 in (8, 14):
            # TS 26.443 gs_dec.c: noisy speech is SWB-only; maximum pitch-band index is 10.
            if mode >> 3 == 8:
                field, bounds, maximum = "wb_gsc_audio", [40, 41], 0
            else:
                field, bounds, maximum = "swb_gsc_inactive", [44, 48], 10
            octet = slot["octets"].split()[5]
            value, outcome = None, "unavailable"
            if octet not in ("??", "--"):
                byte = int(octet, 16)
                value = byte >> 7 if field == "wb_gsc_audio" else byte & 15
                outcome = "pass" if value <= maximum else "reject"
            result.update(check=field, word_bits=bounds, allowed=[0, maximum],
                          observed=value, outcome=outcome)
        else:
            continue
        rows.append(result)
    counts = {}
    for name in ("swb_hq_class", "wb_gsc_audio", "swb_gsc_inactive"):
        counts[name] = {outcome: sum(row["check"] == name and row["outcome"] == outcome for row in rows)
                        for outcome in ("conditional", "pass", "reject", "unavailable")}
    return dict(scope="Only applicable slots are listed. Word bits use half-open intervals. "
                      "The allowed value bounds are inclusive. Conditional bits have no on-air score.",
                by_check=counts, slots=rows)
