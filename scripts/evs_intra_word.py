"""Field constraints for ordinary 264-bit EVS words, in MSB-first wire order."""
from evs_core_history import COORDINATES, received_mode


def intra_word(slots):
    rows = []
    for slot in slots:
        mode = received_mode(slot)
        if mode is None:
            continue
        result = {name: slot[name] for name in COORDINATES}
        if mode == 0xF9:
            # Non-switching SWB HQ class straddles the header and first payload byte.
            # TS 26.443 hq_lr_enc.c emits 00, 01 or 10. Here its first bit is one.
            result.update(check="swb_hq_class", word_bits=[8, 9], allowed=[0, 0],
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
