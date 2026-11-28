"""Read the receiver's counter-aligned four-packet snapshots."""
from zipfile import BadZipFile

import numpy as np

from tail_fill_audit import crc


PACKET_BYTES = 179


def read_packet_snapshot(path):
    """Return ticks, 716-byte units and packet receipt flags, including all-missing rows.

    Each tick is three times the unsigned 32-bit counter plus the phase (0–2).
    The archive stores packet bodies after stripping their headers and CRCs.
    A false flag makes all 179 corresponding bytes unavailable to the caller.
    """
    names = ("ticks", "packets", "packet_ok")
    try:
        archive = np.load(path, allow_pickle=False)
        if not isinstance(archive, np.lib.npyio.NpzFile):
            raise ValueError("expected a packets.npz archive")
        with archive:
            if len(archive.files) != len(set(archive.files)):
                raise ValueError("duplicate array names in packets.npz")
            if not set(names).issubset(archive.files):
                raise ValueError("packets.npz must contain ticks, packets and packet_ok")
            ticks, packets, flags = (archive[name] for name in names)
    except (BadZipFile, EOFError) as error:
        raise ValueError("invalid packets.npz archive") from error

    if not all(isinstance(a, np.ndarray) for a in (ticks, packets, flags)):
        raise ValueError("expected NumPy arrays in packets.npz")
    if ticks.ndim != 1 or ticks.dtype.kind not in "iu":
        raise ValueError("ticks must be a one-dimensional integer array")
    if np.any(ticks < 0) or np.any(ticks > 3 * 0xffffffff + 2):
        raise ValueError("tick outside unsigned 32-bit counter and phase range")
    ticks = ticks.astype(np.int64, copy=False)
    if np.any(ticks[1:] <= ticks[:-1]):
        raise ValueError("ticks must be strictly increasing")
    if packets.dtype != np.uint8 or packets.shape != (len(ticks), 4, PACKET_BYTES):
        raise ValueError("expected four 179-byte uint8 packet bodies per tick")
    if flags.dtype != np.bool_ or flags.shape != (len(ticks), 4):
        raise ValueError("expected four boolean packet flags per tick")
    if np.any(flags.view(np.uint8) > 1):
        raise ValueError("packet flags must encode false or true as 0 or 1")

    units = packets.reshape(len(ticks), 4 * PACKET_BYTES)
    for tick, unit, present in zip(ticks, units, flags, strict=True):
        counter, phase = divmod(int(tick), 3)
        if present[0] and int(unit[1]) >> 4 != phase:
            raise ValueError(f"packet phase disagrees with tick {tick}")
        if present[3] and phase == 0 and int.from_bytes(unit[664:668], "big") != counter:
            raise ValueError(f"packet counter disagrees with tick {tick}")
        if present.all() and crc(unit[:714]) != int.from_bytes(unit[714:], "big"):
            raise ValueError(f"data-unit CRC failed at tick {tick}")
    return ticks, units, flags
