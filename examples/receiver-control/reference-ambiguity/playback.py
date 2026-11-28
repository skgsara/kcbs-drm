"""Compare decoded audio when one complete official EVS word replaces its aligned counterpart."""
import argparse
from collections import Counter
from itertools import combinations
import json
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory

import numpy as np

from official import CODEC, HERE, digest, load_vectors, member_path, project


RECORD_BYTES = 4 + 2 * 264  # Two G.192 header symbols followed by the 264 bit symbols.


def replace_records(original, alternate, slots):
    data = bytearray(original)
    for slot in slots:
        start = slot * RECORD_BYTES
        end = start + RECORD_BYTES
        if end > len(original) or end > len(alternate) or original[start:end] == alternate[start:end]:
            raise ValueError(f"expected distinct, complete records at slot {slot}")
        data[start:end] = alternate[start:end]
    return data


def decode(decoder, rate, coded, expected_frames, directory):
    source, output = directory / "stream.192", directory / "decoded.pcm"
    source.write_bytes(coded)
    output.unlink(missing_ok=True)
    subprocess.run([decoder, str(rate), source, output], stdout=subprocess.DEVNULL,
                   stderr=subprocess.PIPE, check=True)
    data = output.read_bytes()
    if len(data) != 2 * 20 * rate * expected_frames:
        raise ValueError("incomplete decoded PCM timeline")
    return data


def compare_audio(baseline, observed):
    a = np.frombuffer(baseline, dtype="<i2")
    b = np.frombuffer(observed, dtype="<i2")
    if a.shape != b.shape:
        raise ValueError("decoded sample lengths differ")
    changed = np.flatnonzero(a != b)
    return dict(differing_samples=int(changed.size),
                first_changed_sample=int(changed[0]) if changed.size else None,
                last_changed_sample=int(changed[-1]) if changed.size else None,
                observed_pcm_sha256=digest(observed))


def evaluate(cache, fixed_decoder, float_decoder, fetch):
    official = json.loads((HERE / "official.json").read_bytes())
    streams, files = load_vectors(cache, official["pcm_sources"], fetch)
    if files != official["sources"]:
        raise ValueError("source identity differs from the official-vector comparison")
    archive = json.loads((CODEC / "reference-members.json").read_bytes())
    references = {m["name"]: m for m in archive["members"]}
    swaps = []
    cases = {}
    with TemporaryDirectory() as tmp:
        work = Path(tmp)
        for case, entry in files.items():
            fixed, floating = streams["fixed", case], streams["float", case]
            slots = [i for i, (a, b) in enumerate(zip(fixed, floating, strict=True))
                     if a != b and project(a) == project(b)]
            if not slots:
                continue
            name = entry["cod"]
            native_rate = int(Path(name).stem.rsplit("_", 1)[1].removesuffix("kHz"))
            original = (cache / "fixed" / name).read_bytes()
            alternate = (cache / "float" / name).read_bytes()
            if len(original) != len(alternate) or len(original) != len(fixed) * RECORD_BYTES:
                raise ValueError("unexpected G.192 record geometry")
            out_name = name.replace("/bitstreams/", "/decoded/").replace(".COD", ".OUT")
            reference = member_path(cache, "fixed", archive, references[out_name], fetch).read_bytes()
            if decode(fixed_decoder, native_rate, original, len(fixed), work) != reference:
                raise ValueError(f"{case}: baseline differs from 3GPP reference PCM")
            cases[case] = dict(native_rate_khz=native_rate, slots=len(fixed), samples=len(reference) // 2,
                               published_pcm_sha256=digest(reference))
            for slot in slots:
                replaced = replace_records(original, alternate, [slot])
                observed = decode(fixed_decoder, native_rate, replaced, len(fixed), work)
                swaps.append(dict(case=case, slot=slot, word_mode_hex=f"{fixed[slot][0]:02X}",
                                  changed_stream_sha256=digest(replaced), **compare_audio(reference, observed)))

        # All four were identified in the single-replacement comparison above.
        identical_pcm = [(row["case"], row["slot"]) for row in swaps if row["differing_samples"] == 0]
        nb = "nb_c"
        if Counter(case for case, _ in identical_pcm) != {nb: 4}:
            raise ValueError(f"unexpected number of reference-identical substitutions: {identical_pcm}")
        slots = [i for _, i in identical_pcm]
        count = cases[nb]["slots"]
        cod = files[nb]["cod"]
        original = (cache / "fixed" / cod).read_bytes()
        alternate = (cache / "float" / cod).read_bytes()
        reference = (cache / "fixed" / cod.replace("/bitstreams/", "/decoded/")).with_suffix(".OUT").read_bytes()
        combinations_tested = []
        for n in range(len(slots) + 1):
            for selected in combinations(slots, n):
                coded = replace_records(original, alternate, selected)
                samples = decode(fixed_decoder, 8, coded, count, work)
                combinations_tested.append(dict(replaced_slots=list(selected), stream_sha256=digest(coded),
                                                pcm_matches_published=samples == reference, pcm_sha256=digest(samples)))
        if len({x["stream_sha256"] for x in combinations_tested}) != len(combinations_tested):
            raise ValueError("combination produced a duplicate bitstream")
        positive = next(row["slot"] for row in swaps if row["case"] == nb and row["differing_samples"])
        other_runs = []
        for kind, decoder, rate in (("fixed", fixed_decoder, 48), ("float", float_decoder, 8),
                                    ("float", float_decoder, 48)):
            baseline = decode(decoder, rate, original, count, work)
            selections = [[slot] for slot in (*slots, positive)] + [slots]
            for selected in selections:
                samples = decode(decoder, rate, replace_records(original, alternate, selected), count, work)
                other_runs.append(dict(decoder=kind, rate_khz=rate, replaced_slots=selected,
                                       baseline_pcm_sha256=digest(baseline), **compare_audio(baseline, samples)))
    return dict(source_cases=cases, single_swaps=swaps, matched_entire_published_pcm=identical_pcm,
                native_narrowband_combinations=combinations_tested, additional_decoder_checks=other_runs)


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("cache", type=Path)
    cli.add_argument("--fixed-decoder", type=Path, required=True)
    cli.add_argument("--float-decoder", type=Path, required=True)
    cli.add_argument("--fetch", action="store_true", help="retrieve missing original 3GPP members")
    cli.add_argument("--check", action="store_true", help="compare output with playback.json")
    args = cli.parse_args()
    result = evaluate(args.cache, args.fixed_decoder.resolve(), args.float_decoder.resolve(), args.fetch)
    content = json.dumps(result, indent=2) + "\n"
    if args.check and json.loads(content) != json.loads((HERE / "playback.json").read_bytes()):
        raise SystemExit("result differs from playback.json")
    print(content, end="")
