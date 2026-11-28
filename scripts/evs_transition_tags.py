"""Infer the high two bits of p0 from the 13.2 kb/s stock SWB ACELP transition tag and reserved suffix."""
from evs_core_history import COORDINATES, received_mode


# 11.60 kb/s core. enc_tran.c writes the prefix; rom_com.c supplies its minimum trailing zero count.
TAG_ZEROS = {"1": 0, "0101": 1, "0100": 3, "011": 6, "001": 2, "0001": 6, "0000": 0}


def allowed_pairs(mode, last_octet):
    """Return possible b8:b9 values for index 12. A short tag leaves following bits free."""
    if mode is None or mode >> 3 != 12 or last_octet is None:
        return None
    result = []
    for pair in range(4):
        prefix = f"{mode & 3:02b}{pair:02b}"
        if any(prefix.startswith(tag) and last_octet & ((1 << zeros) - 1) == 0
               for tag, zeros in TAG_ZEROS.items()):
            result.append(pair)
    return result


def field(mode, last_octet):
    pairs = allowed_pairs(mode, last_octet)
    if pairs is None:
        return None
    fixed = {}
    for bit, shift in ((8, 1), (9, 0)):
        possible = {pair >> shift & 1 for pair in pairs}
        if len(possible) == 1:
            fixed[str(bit)] = possible.pop()
    outcome = "contradiction" if not pairs else "unrestricted" if len(pairs) == 4 else "restricted"
    return dict(mode=f"{mode:02X}", payload31=f"{last_octet:02X}", outcome=outcome,
                allowed_high_pairs=pairs, fixed_word_bits=fixed)


def transition_tags(slots):
    rows = []
    for slot in slots:
        mode = received_mode(slot)
        if mode is None or mode >> 3 != 12:
            continue
        token = slot["octets"].split()[32]
        if token in ("--", "??"):
            continue
        rows.append({k: slot[k] for k in COORDINATES} | field(mode, int(token, 16)))
    return dict(word_bits=[8, 10], outcome_basis="Conditional on the stock 13.2 kb/s SWB ACELP "
                "TRANSITION encoder. Some text-supported P1 and P2 labels disagree with the predicted pair.",
                fixed_bit_count=sum(len(r["fixed_word_bits"]) for r in rows), slots=rows)
