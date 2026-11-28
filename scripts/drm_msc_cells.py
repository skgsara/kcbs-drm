"""Read deinterleaved Dream MSC observer blocks, combine equalized cells and run the stock 16-QAM decoder."""
from dataclasses import dataclass
import struct
import subprocess

import numpy as np


HEADER = struct.Struct("<28i")


@dataclass
class Block:
    header: tuple
    cells: np.ndarray
    hard: bytes

    def geometry(self):
        # Disregard callback ordinal, current receiver frame ID and SNR.
        return self.header[1:10] + self.header[11:27]


def read_blocks(raw):
    if raw[:8] != b"MSCObs1\n":
        raise ValueError("unsupported MSC observer format")
    offset = 8
    blocks = []
    while offset < len(raw):
        if len(raw) - offset < HEADER.size:
            raise ValueError("truncated observer header")
        h = HEADER.unpack_from(raw, offset)
        offset += HEADER.size
        count, bits = h[1:3]
        if h[0] != len(blocks) or not 0 < count < 100000 or not 0 < bits < 1000000:
            raise ValueError("invalid observer block index or dimensions")
        cells = np.frombuffer(raw, dtype="<f8", count=count * 3, offset=offset).reshape(count, 3)
        offset += count * 24
        size = (bits + 7) // 8
        hard = raw[offset:offset + size]
        if len(hard) != size:
            raise ValueError("truncated observer hard decisions")
        offset += size
        blocks.append(Block(h, cells, hard))
    return blocks


def decode_batch(executable, items):
    payload = bytearray()
    for block, cells in items:
        h = block.header
        if h[5] != 1:
            raise ValueError("expected the standard 16-QAM mapping")
        params = (h[1], h[2], h[3], h[4], h[6], h[7], h[11], *h[18:26])
        payload.extend(struct.pack("<15i", *params))
        payload.extend(np.ascontiguousarray(cells, dtype="<f8").tobytes())
    raw = subprocess.run([str(executable)], input=payload, stdout=subprocess.PIPE, check=True).stdout
    offset = 0
    result = []
    for block, _ in items:
        finish = offset + len(block.hard)
        result.append(raw[offset:finish])
        offset = finish
    if offset != len(raw):
        raise ValueError("native decoder output length differs from the declared block sizes")
    return result


def decode(executable, items):
    """Limit the application and subprocess buffers for longer observations."""
    result = []
    for offset in range(0, len(items), 16):
        result.extend(decode_batch(executable, items[offset:offset + 16]))
    return result


def weighted_cells(block):
    cells = block.cells
    usable = np.isfinite(cells).all(axis=1) & (cells[:, 2] > 0) & (cells[:, 2] < 1e30)
    power = np.zeros(len(cells))
    xy = np.zeros_like(cells[:, :2])
    if np.any(usable):
        gains = cells[usable, 2] ** 2
        # The observer stores Dream's block SNR in millidecibels.
        power[usable] = 10**(block.header[27] / 10000.0) * gains / gains.mean()
        xy[usable] = cells[usable, :2]
    return power, xy


def combine(left_block, right_block, cell_shift):
    left_weights, left = weighted_cells(left_block)
    right_weights, right = weighted_cells(right_block)
    if cell_shift:
        right_weights = np.roll(right_weights, -cell_shift, axis=0)
        right = np.roll(right, -cell_shift, axis=0)
    weights = left_weights + right_weights
    usable = weights > 0
    result = np.zeros((len(weights), 3), dtype="<f8")
    numerator = left_weights[:, None] * left + right_weights[:, None] * right
    result[usable, :2] = numerator[usable] / weights[usable, None]
    result[:, 2] = 3.4e38  # Dream's ERASURE_TAG_VALUE when neither receiver supplies a usable cell.
    result[usable, 2] = np.sqrt(weights[usable])
    return result
