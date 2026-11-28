"""Replay two fixed synthetic PCM pulses through a stock TS 26.443 encoder and decoder."""
import argparse
from hashlib import sha256
import json
import math
from pathlib import Path
import shutil
import struct
import subprocess
from tempfile import TemporaryDirectory

SLOT = 5
WORDS = 12
SOURCE_RATE = 32000
SAMPLE = 3520
LEVELS = (-11296, -31936)
DIRECT = [0, *(p + 1 for p in range(32) if p % 3)]
ENC = ["-q", "-no_delay_cmp", "-max_band", "SWB", "13200", "32"]
DEC = ["-q", "-no_delay_cmp"]


def digest(data):
    return sha256(data).hexdigest()


def codec(exe, args):
    subprocess.run([exe, *args], check=True, stdout=subprocess.DEVNULL)


def words(data):
    """Return 33-byte words from a little-endian G.192 stream of good 264-bit frames."""
    if len(data) != WORDS * 532:
        raise ValueError("expected twelve G.192 frames")
    result = []
    for sync, bits, *symbols in struct.iter_unpack("<266H", data):
        if sync != 0x6b21 or bits != 264 or set(symbols) - {0x007f, 0x0081}:
            raise ValueError("invalid G.192 word")
        packed = bytearray(33)
        for index, symbol in enumerate(symbols):
            if symbol == 0x0081:
                packed[index // 8] |= 128 >> (index % 8)
        result.append(bytes(packed))
    return result


def samples(raw):
    return [v for (v,) in struct.iter_unpack("<h", raw)]


def rms(values):
    return math.sqrt(sum(v*v for v in values) / len(values))


def level(values):
    amp = rms(values)
    return dict(peak=max(map(abs, values)), rms_s16=round(amp, 6),
                rms_dbfs=round(20 * math.log10(amp / 32768), 6) if amp else None)


def decode(exe, rate, path, work):
    out = work / (path.stem + f"-{rate}.pcm")
    codec(exe, [*DEC, str(rate), path, out])
    return out.read_bytes()


def run(encoder, decoder, work):
    streams = []
    sources = []
    paths = []
    for name, amplitude in zip(("a", "b"), LEVELS):
        pcm = bytearray(2 * WORDS * (SOURCE_RATE // 50))
        struct.pack_into("<h", pcm, 2 * SAMPLE, amplitude)
        src = work / (name + "-source.pcm")
        src.write_bytes(pcm)
        path = work / (name + ".192")
        codec(encoder, [*ENC, src, path])
        sources.append(dict(pulse_value=amplitude, minimum=amplitude, maximum=0, peak=abs(amplitude),
                            input_pcm_sha256=digest(pcm), full_g192_sha256=digest(path.read_bytes())))
        streams.append(words(path.read_bytes()))
        paths.append(path)

    a, b = streams
    changed = [n for n in range(WORDS) if a[n] != b[n]]
    bit_indices = [n for n in range(264) if (a[SLOT][n // 8] ^ b[SLOT][n // 8]) & (128 >> (n % 8))]
    direct = [bytes(x[SLOT][n] for n in DIRECT) for x in streams]
    if changed[:1] != [SLOT] or bit_indices != [32] or direct[0] != direct[1]:
        raise ValueError("the registered encoded pair or its matching history did not reproduce")
    copy = work / "identical-copy.192"
    shutil.copyfile(paths[0], copy)
    if words(copy.read_bytes()) != a:
        raise ValueError("the positive-control copy changed")

    rates = {}
    for rate in (8, 16, 32, 48):
        size = rate * 20
        start, end = 2 * SLOT * size, 2 * (SLOT + 1) * size
        full = [decode(decoder, rate, p, work) for p in paths]
        if any(len(v) != 2 * WORDS * size for v in full):
            raise ValueError("unexpected sample count from the stock decoder")
        if full[0][:start] != full[1][:start]:
            raise ValueError("decoded histories differ before the target")
        copied = decode(decoder, rate, copy, work)
        if copied != full[0]:
            raise ValueError("fresh decode of the positive-control copy differs")
        for path, y in zip(paths, full):
            prefix = work / (path.stem + "-through-target.192")
            prefix.write_bytes(path.read_bytes()[:532 * (SLOT + 1)])
            if decode(decoder, rate, prefix, work) != y[:end]:
                raise ValueError("removing all following words changed decoded PCM through the target")
        target = [v[start:end] for v in full]
        x, y = map(samples, target)
        delta = [t - s for s, t in zip(x, y)]
        changed_samples = [i for i, sample in enumerate(delta) if sample != 0]
        if not changed_samples or rms(x) == 0:
            raise ValueError("no target contrast for this specified pair")
        rates[str(rate)] = dict(output_samples_per_stream=WORDS * size,
            equal_preceding_samples=SLOT * size, target_samples=size,
            signed_pcm16_target=[level(x), level(y)], signed_pcm16_difference=level(delta),
            target_rms_ratio_b_over_a_db=round(20 * math.log10(rms(y) / rms(x)), 6),
            changed_target_samples=len(changed_samples), first_changed_target_sample=changed_samples[0],
            last_changed_target_sample=changed_samples[-1], full_output_sha256=list(map(digest, full)),
            target_pcm_sha256=list(map(digest, target)), copied_a_exact_all_samples=True,
            copied_a_pcm_sha256=digest(copied), truncation_after_target_exact_both=True)

    return dict(schema="fixed-synthetic-EVS-pulse-pair-v1",
                stimulus=dict(source_rate_hz=SOURCE_RATE, sample_count=WORDS * (SOURCE_RATE // 50),
                              sample_format="signed little-endian int16 mono", pulse_sample_zero_based=SAMPLE,
                              other_samples=0, origin="Fixed pair selected in a synthetic pulse-amplitude sweep."),
                codec=dict(encoder_sha256=digest(encoder.read_bytes()), decoder_sha256=digest(decoder.read_bytes()),
                           encoder_options=ENC, decoder_options=DEC),
                inputs=sources, encoded_words_per_input=WORDS, target_slot_zero_based=SLOT,
                position_one_based=SLOT % 4 + 1, mode_hex=a[SLOT][:1].hex().upper(),
                target_words_hex=[a[SLOT].hex(), b[SLOT].hex()],
                direct_word_octet_indices=DIRECT, direct_octets_hex=direct[0].hex(),
                equal_target_bits=264-len(bit_indices), changed_word_bits_msb_first_zero_based=bit_indices,
                differing_word_octet_zero_based=4, differing_payload_octet_zero_based=3,
                changed_encoded_slots=changed, equal_preceding_encoded_slots=SLOT,
                equal_following_encoded_slots=[i for i in range(SLOT+1, WORDS) if i not in changed],
                measured_output_by_khz=rates,
                scope="A synthetic impulse-amplitude comparison with a shared decoder history. The source PCM "
                      "and decoded PCM have different scales. The measurements report output differences; human "
                      "audibility and comparisons with music were not evaluated.")


def measurements(report):
    # Distinct reference builds can emit the same streams and PCM.
    settings = {k: v for k, v in report["codec"].items() if not k.endswith("_sha256")}
    primary = {k: v for k, v in report.items() if k != "second_build"}
    return {**primary, "codec": settings}


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--encoder", type=Path, required=True)
    cli.add_argument("--decoder", type=Path, required=True)
    cli.add_argument("--also-encoder", type=Path, help="optional second stock encoder build")
    cli.add_argument("--also-decoder", type=Path, help="decoder paired with the second encoder")
    cli.add_argument("--out", type=Path, help="write JSON here, otherwise use stdout")
    cli.add_argument("--expect", type=Path, help="check all registered non-executable measurements")
    args = cli.parse_args()
    with TemporaryDirectory(prefix="evs-pulse-") as tmp:
        result = run(args.encoder.resolve(), args.decoder.resolve(), Path(tmp))
    if bool(args.also_encoder) != bool(args.also_decoder):
        cli.error("supply both executables for the second build")
    if args.also_encoder:
        with TemporaryDirectory(prefix="evs-pulse-second-") as tmp:
            other = run(args.also_encoder.resolve(), args.also_decoder.resolve(), Path(tmp))
        if measurements(result) != measurements(other):
            raise ValueError("second stock build produced different encoded words or decoded measurements")
        result["second_build"] = dict(encoder_sha256=other["codec"]["encoder_sha256"],
                                      decoder_sha256=other["codec"]["decoder_sha256"],
                                      identical_complete_g192_and_pcm_at_all_four_rates=True)
    if args.expect:
        expected = json.loads(args.expect.read_bytes())
        if measurements(result) != measurements(expected):
            raise ValueError("registered codec or waveform measurements changed")
    report = json.dumps(result, indent=2) + "\n"
    if args.out:
        args.out.write_text(report, encoding="utf-8")
    else:
        print(report, end="")


if __name__ == "__main__":
    main()
