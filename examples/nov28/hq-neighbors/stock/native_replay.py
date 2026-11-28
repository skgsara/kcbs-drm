"""Generate stock tonal witnesses with pristine and detector-instrumented EVS encoders."""

import argparse
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import tempfile

from proof import check_detector_history, eligible_centers, encoder_command, g192_frames, require, tonal_input


def build_observer(source, folder):
    """Build a separate encoder in the temporary directory with an observer on detect_transient()."""
    detector = source / "lib_enc/detect_transient.c"
    original = detector.read_text(encoding="utf-8")
    gate = "    if ( IsTransient )\n    {\n        if(L == L_FRAME8k)"
    end = "    return IsTransient;"
    require(original.count(gate) == 1 and original.count(end) == 1, "unexpected TS 26.443 detector source")
    save_inputs = """    const short local_attack = IsTransient;
    const short local_incoming = st->TransientHangOver;
"""
    log_event = r'''    if (coder_type == HQ_CORE && st->bwidth == SWB && st->core_brate == 13200) {
        extern long frame;
        fprintf(stderr, "A,%ld,%d,%d,%d,%d,%d,%d,%d,%d\n",
                frame, local_attack, local_incoming, IsTransient, st->TransientHangOver,
                L, st->last_extl, st->extl, st->last_core);
    }
'''
    replacement = folder / "detect_transient.c"
    instrumented = original.replace(gate, save_inputs + gate).replace(end, log_event + end)
    replacement.write_text(instrumented, encoding="utf-8")

    libraries = ["lib_com", "lib_enc"]
    headers = ["-I" + str(source / library) for library in [*libraries, "lib_dec"]]
    sources = []
    for library in libraries:
        for path in sorted((source / library).glob("*.c")):
            sources.append(replacement if path == detector else path)
    encoder = folder / "observed-encoder"
    command = ["gcc", "-O2", "-std=gnu99", "-fno-strict-aliasing", *headers, *sources, "-lm", "-o", encoder]
    subprocess.run(command, check=True)
    return encoder, sha256(detector.read_bytes()).hexdigest()


def detector_events(log):
    by_slot = {}
    for line in log.splitlines():
        if not line.startswith(b"A,"):
            continue
        slot, attack, incoming, returned, outgoing, length, last_ext, ext, previous_core = (
            int(field) for field in line.split(b",")[1:]
        )
        require(slot not in by_slot, f"duplicate detector event at slot {slot}")
        by_slot[slot] = {
            "attack": attack,
            "incoming": incoming,
            "returned": returned,
            "outgoing": outgoing,
            "input_frame_samples": length,
            "previous_extension": last_ext,
            "extension": ext,
            "previous_core": previous_core,
        }
    return by_slot


def generate_witnesses(public_checkout, stock_encoder, evs_source):
    fixture_dir, pcm = tonal_input(public_checkout)
    expected = json.loads((fixture_dir / "native-expected.json").read_text(encoding="utf-8"))["tonal_bank"]
    pcm_hash = sha256(pcm).hexdigest()
    require(pcm_hash == expected["pcm_sha256"], "generated PCM differs from the published tonal input")

    with tempfile.TemporaryDirectory() as temporary:
        folder = Path(temporary)
        source = folder / "tonal.s16"
        source.write_bytes(pcm)
        observed_encoder, detector_hash = build_observer(evs_source.resolve(), folder)
        pristine = folder / "clean.192"
        observed = folder / "observed.192"
        subprocess.run(encoder_command(stock_encoder, source, pristine), check=True, capture_output=True)
        probe = subprocess.run(encoder_command(observed_encoder, source, observed), check=True, capture_output=True)
        raw = pristine.read_bytes()
        require(raw == observed.read_bytes(), "observer changed the encoded G.192 stream")

    encoded_hash = sha256(raw).hexdigest()
    require(encoded_hash == expected["g192_sha256"], "G.192 differs from the published stock stream")
    frames = g192_frames(raw)
    by_slot = detector_events(probe.stderr)
    triples = []
    for center in eligible_centers(frames):
        words = frames[center - 1:center + 2]
        events = [by_slot[slot] for slot in range(center - 1, center + 2)]
        check_detector_history(events, [word[1] >> 7 for word in words])
        triples.append({
            "center_zero_based_slot": center,
            "mode_hex": [f"{word[0]:02X}" for word in words],
            "center_b8": words[1][1] >> 7,
            "full_words": [word.hex() for word in words],
            "native": events,
        })
    return {
        "source": "Public hq-class/native.py:tonal_bank (32 kHz, 36 seconds), one direct encode, 1800 complete words",
        "generator_sha256": sha256((fixture_dir / "native.py").read_bytes()).hexdigest(),
        "pcm_sha256": pcm_hash,
        "g192_sha256": encoded_hash,
        "reencoded_equal_to_preexisting_public_digest": True,
        "observer_equal_to_pristine_stock": True,
        "modified_detector_original_source_sha256": detector_hash,
        "pristine_encoder_sha256": sha256(stock_encoder.read_bytes()).hexdigest(),
        "coordinate": "Zero-based, MSB-first physical word bits. b7 is the LSB of the mode, b8 the MSB of byte 1.",
        "triples": triples,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("public_checkout", type=Path, help="public checkout containing the tonal generator")
    parser.add_argument("stock_encoder", type=Path, help="pristine EVS_cod binary")
    parser.add_argument("evs_source", type=Path, help="TS 26.443 c-code directory")
    parser.add_argument("--out", type=Path, help="write generated witnesses here (default: standard output)")
    args = parser.parse_args()
    witnesses = generate_witnesses(args.public_checkout, args.stock_encoder, args.evs_source)
    data = json.dumps(witnesses, indent=2)
    if args.out is None:
        print(data)
    else:
        args.out.write_text(data + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
