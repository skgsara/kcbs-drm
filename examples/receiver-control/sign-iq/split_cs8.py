"""Retain one absolute parity of raw 912 ksample/s signed I,Q pairs, without filtering."""
import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory


RATE = 912000
BLOCK_PAIRS = 262144


def split(source, output, start, count, parity, file_start=0):
    """Select from the half-open absolute window [start, start + count)."""
    if parity not in ('even', 'odd') or file_start < 0 or start < file_start or count <= 0:
        raise ValueError('invalid parity or source sample range')
    if output.suffix.lower() != '.cs8':
        raise ValueError('the Dream input must have a .cs8 extension')
    if os.path.lexists(output):
        raise FileExistsError(f'output exists: {output}')

    first = start + ((int(parity == 'odd') - start) % 2)
    end = start + count
    if first >= end:
        raise ValueError('no sample pairs of the selected parity in this window')
    window_hash, output_hash = sha256(), sha256()
    with source.open('rb', buffering=0) as src, TemporaryDirectory(dir=output.parent) as directory:
        before = os.fstat(src.fileno())
        if before.st_size % 2 or end - file_start > before.st_size // 2:
            raise ValueError('incomplete CS8 pair or window outside source')
        src.seek(2 * (start - file_start))
        staging = Path(directory) / 'part.cs8'
        with staging.open('wb') as dst:
            for i in range(start, end, BLOCK_PAIRS):
                n = min(BLOCK_PAIRS, end - i)
                chunk = src.read(2 * n)
                if len(chunk) != 2 * n:
                    raise ValueError('short read in selected CS8 window')
                # Slice complete two-byte units. Cast and tobytes retain the original I,Q bytes.
                kept = memoryview(chunk).cast('H')[(first - i) % 2::2].tobytes()
                window_hash.update(chunk)
                output_hash.update(kept)
                dst.write(kept)
            written = dst.tell() // 2
        after = os.fstat(src.fileno())
        if (after.st_size, after.st_mtime_ns) != (before.st_size, before.st_mtime_ns):
            raise ValueError('source changed during the bounded read')
        if written != (end - first + 1) // 2:
            raise ValueError('output pair count differs from window geometry')
        os.link(staging, output)

    return dict(source=source.name, source_rate_hz=RATE, file_start_sample=file_start,
                absolute_input_range=[start, end], read_byte_range_in_file=[2*(start-file_start), 2*(end-file_start)],
                source_window_sha256=window_hash.hexdigest(), parity=parity, selected_stride_pairs=2,
                output=output.name, output_rate_hz=RATE//2, output_sample_pairs=written,
                first_absolute_pair=first, last_absolute_pair=first + 2*(written-1),
                output_sha256=output_hash.hexdigest(),
                sampling='literal alternate signed I,Q pairs; no anti-alias filter')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--start-sample', required=True, type=int, help='first absolute input pair index')
    parser.add_argument('--sample-count', required=True, type=int, help='number of original 912 kHz pairs')
    parser.add_argument('--parity', choices=['even', 'odd'], required=True)
    parser.add_argument('--file-start-sample', default=0, type=int,
                        help='absolute index of file pair zero when a source range was downloaded')
    args = parser.parse_args()
    try:
        receipt = split(args.source, args.output, args.start_sample, args.sample_count,
                        args.parity, args.file_start_sample)
    except (ValueError, OSError) as exc:
        parser.exit(1, f'{parser.prog}: {exc}\n')
    print(json.dumps(receipt, indent=2))
