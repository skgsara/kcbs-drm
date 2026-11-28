"""Generate the offline DRM IQ fixture with 12 deliberately incorrect packet CRCs."""
import argparse
from binascii import crc_hqx
import gzip
from hashlib import sha256
import json
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import wave

import numpy as np
import soundfile as sf


HERE = Path(__file__).resolve().parent
ORIGINAL_SHA256 = "cb378996150b65393c4bd84a4ef818fc3ca790ceacf03b1ffe6c91b2f7bc0d47"
FIRST_COUNTER = 0x01020304
PACKET_HEADERS = (0x80, 0x01, 0x02, 0x43)
RATE = 48000
IQ_PAIRS = 3340800


def digest(data):
    return sha256(data).hexdigest()


def valid_crc(data):
    return (crc_hqx(data[:-2], 0xffff) ^ 0xffff) == int.from_bytes(data[-2:], "big")


def damaged_rows(original):
    if len(original) != 120 * 728 or digest(original) != ORIGINAL_SHA256:
        raise ValueError("Unexpected sender template")
    altered = bytearray(original)
    changes = []
    for row in range(120):
        start = row * 728
        group, phase = divmod(row, 3)
        packets = [original[start + q * 182:start + (q + 1) * 182] for q in range(4)]
        if tuple(packet[0] for packet in packets) != PACKET_HEADERS or not all(map(valid_crc, packets)):
            raise ValueError(f"Invalid sender packet at row {row}")
        unit = b"".join(packet[1:-2] for packet in packets)
        if not valid_crc(unit) or unit[1] >> 4 != phase:
            raise ValueError(f"Invalid sender DU at row {row}")
        if phase == 0 and int.from_bytes(unit[664:668], "big") != FIRST_COUNTER + group:
            raise ValueError(f"Unexpected phase-zero counter at row {row}")
        if 8 <= group <= 19:
            selected_phase, quarter = divmod(group - 8, 4)
            if phase == selected_phase:
                packet_start = start + quarter * 182
                offset = packet_start + 180
                altered[offset] ^= 0x80
                if valid_crc(altered[packet_start:packet_start + 182]):
                    raise ValueError("Changed checksum unexpectedly accepted")
                changes.append(dict(group_index=group, counter=FIRST_COUNTER + group, phase=phase,
                                    quarter=quarter, scored_row=row, row_byte=182 * quarter + 180,
                                    original_crc=packets[quarter][-2:].hex(),
                                    transmitted_crc=altered[offset:offset + 2].hex()))
    differences = [i for i, (before, after) in enumerate(zip(original, altered)) if before != after]
    if len(changes) != 12 or differences != [r["scored_row"] * 728 + r["row_byte"] for r in changes]:
        raise ValueError("Unexpected modified byte coordinates")
    return bytes(altered), changes


def encode_lossless(wav, flac):
    with wave.open(str(wav), "rb") as stream:
        if (stream.getnchannels(), stream.getsampwidth(), stream.getframerate(), stream.getnframes()) != (
                2, 2, RATE, IQ_PAIRS):
            raise ValueError("Unexpected generated IQ geometry")
        pcm = stream.readframes(IQ_PAIRS)
    if len(pcm) != IQ_PAIRS * 4:
        raise ValueError("Short generated PCM")
    iq = np.frombuffer(pcm, dtype="<i2").reshape(-1, 2)
    with sf.SoundFile(flac, mode="x", samplerate=RATE, channels=2, format="FLAC", subtype="PCM_16") as stream:
        stream.write(iq)
    with sf.SoundFile(flac) as stream:
        if (stream.format, stream.subtype, stream.samplerate, stream.channels, stream.frames) != (
                "FLAC", "PCM_16", RATE, 2, IQ_PAIRS):
            raise ValueError("Unexpected FLAC format")
        if stream.read(dtype="int16", always_2d=True).astype("<i2", copy=False).tobytes() != pcm:
            raise ValueError("FLAC samples differ from the modulator WAV")
    return digest(pcm)


def generate(binary, out):
    template = gzip.decompress((HERE / "fixture/sender-msc.bin.gz").read_bytes())
    modified, changes = damaged_rows(template)
    out.mkdir(exist_ok=False, parents=True)
    with TemporaryDirectory(prefix="drm-file-transmitter-") as scratch:
        source = Path(scratch) / "scored-rows.bin"
        wav = Path(scratch) / "modulated.wav"
        source.write_bytes(modified)
        subprocess.run([binary, source, wav], cwd=scratch, check=True)
        flac = out / "challenge-iq48.flac"
        pcm_hash = encode_lossless(wav, flac)
        result = dict(
            service_id="EF0201", label="DRM IQ TEST", first_counter=FIRST_COUNTER, groups=40,
            duration_seconds=69.6, scored_seconds=48, guard_rows_before=30, scored_rows=120, guard_rows_after=24,
            encoding="48 kHz stereo PCM16 IQ", sample_pairs=IQ_PAIRS, sample_sha256=pcm_hash,
            template_sha256=ORIGINAL_SHA256, modified_rows_sha256=digest(modified),
            modification="Flip the MSB of the stored CRC high octet at offset 180 of each selected 182-byte packet.",
            changes=changes, sender_packets=480, sender_packets_with_intact_crc=468,
            sender_du_payloads_with_intact_crc=120, modulator_sha256=digest(binary.read_bytes()),
            modulator_source_sha256=digest((HERE / "transmitter/msc_to_iq.cpp").read_bytes()),
            generated_wav_sha256=digest(wav.read_bytes()), flac=flac.name, flac_bytes=flac.stat().st_size,
            flac_sha256=digest(flac.read_bytes()), lossless_round_trip=True,
            libsndfile_version=sf.__libsndfile_version__,
        )
    with (out / "transmitter-receipt.json").open("x") as stream:
        print(json.dumps(result, indent=2), file=stream)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("modulator", type=Path, help="file-only msc_to_iq executable")
    parser.add_argument("out", type=Path, help="new directory for the lossless IQ and generation receipt")
    args = parser.parse_args()
    generate(args.modulator.resolve(strict=True), args.out.resolve())
