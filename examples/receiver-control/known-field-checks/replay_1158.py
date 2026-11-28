"""Replay the 11:58:16 UTC 6140 kHz WAV and seal transport selections before checking fields."""
import argparse
from contextlib import redirect_stdout
from hashlib import sha256
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import wave

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SIGN = HERE.parent / "sign-iq"
sys.path.insert(0, str(SIGN))
from evaluate import checked_arm, registry, salvage, selected_projection

WAV_HASH = "5bdd069ccf70ac8551ac7fa054983db0dda03fbc7140e6938079b88f27951809"
DREAM_HASH = "1e398433affbe71e3bdbc30171e9c770ddd3a622c0fe1577b3f3837c3fa07a26"
HISTORY_HASH = "dc84cab40743c59898bab86dd960617df258d287eaddd836d2b2502ace33c7d8"
SAMPLE_PAIRS = 1464832


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def write(path, data):
    with path.open("x") as output:
        print(json.dumps(data, indent=2, allow_nan=False), file=output)


def frozen_history():
    seen, _ = registry()
    metadata = json.loads((SIGN / "field/inputs-and-exposure.json").read_bytes())
    seen.update(metadata["additional_development_ids"])
    seen.update(metadata["new_field_ids"])
    actual = sha256(",".join(map(str, sorted(seen))).encode("ascii")).hexdigest()
    if len(seen) != 15511 or actual != HISTORY_HASH:
        raise ValueError("pre-field assigned-counter inventory differs")
    return seen


def run(script, arguments, output, env=None):
    with output.open("xb") as stream:
        subprocess.run([sys.executable, "-B", str(script), *map(str, arguments)],
                       stdout=stream, check=True, env=env)


def groups(msc, packets):
    seen = frozen_history()
    arm, receipts, _, partial = checked_arm(msc, packets)
    # checked_arm includes a historical intersection from its original 15,274-ID study.
    # This study recomputes membership for every assignment and every selection.
    assigned = set(arm["assigned_counters"])
    arm["prior_assigned_intersection"] = sorted(seen & assigned)
    selections = dict(primary=next(iter(receipts), None),
                      first_unregistered=next((row for row in receipts if row["counter"] not in seen), None),
                      partial_control=partial)
    return dict(inventory_count=len(seen), inventory_sha256=HISTORY_HASH, receiver=arm,
                all_new_assigned=sorted(assigned - seen), selections=selections)


def receive(wav, dream, out):
    if digest(wav) != WAV_HASH or digest(dream) != DREAM_HASH:
        raise ValueError("original WAV or finite-input receiver SHA-256 differs")
    with wave.open(str(wav), "rb") as source:
        if (source.getframerate(), source.getnchannels(), source.getsampwidth(), source.getnframes()) != (
                12000, 2, 2, SAMPLE_PAIRS):
            raise ValueError("source WAV geometry differs")
    frozen_history()
    out.mkdir(parents=True, exist_ok=False)
    rf = out / "receiver"
    run(ROOT / "scripts/demod_iq_window.py",
        [wav, rf, "--start", "0", "--seconds", str(SAMPLE_PAIRS / 12000),
         "--reception-profile", "wiener", "--mlc-iterations", "1"],
        out / "demod.json", {**os.environ, "KCBS_DREAM": str(dream.resolve())})
    manifest = json.loads((out / "demod.json").read_bytes())
    if (manifest["returncode"] != 0 or manifest["start_sample"] != 0 or manifest["sample_count"] != SAMPLE_PAIRS
            or "Reached end of input in offline mode." not in (rf / "dream.log").read_text(errors="replace")):
        raise ValueError("demodulator did not complete the declared source interval")
    msc = rf / "msc.bin"
    emitted = msc.is_file()
    if not emitted:
        if manifest["status"] != "no_msc_output":
            raise ValueError("missing native stream without a no-output manifest")
        msc = out / "empty-native.msc"
        msc.touch(exist_ok=False)
    transport = out / "transport"
    with redirect_stdout(io.StringIO()):
        salvage([msc], transport, transport_only=True, save_packets=True)
    group_file = out / "group-seal.json"
    boundary_file = out / "boundary-plan.json"
    write(group_file, groups(msc, transport / "packets.npz"))
    run(HERE / "native_boundary.py", ["seal", msc], boundary_file)
    result = dict(source_sha256=WAV_HASH, source_bytes=wav.stat().st_size, source_rate_hz=12000,
                  sample_range=[0, SAMPLE_PAIRS], dream_sha256=DREAM_HASH, native_file=str(msc.relative_to(out)),
                  dream_emitted_native=emitted, msc_sha256=digest(msc),
                  group_sha256=digest(group_file), boundary_sha256=digest(boundary_file))
    write(out / "reception.json", result)
    return result


def score(out, group_hash, boundary_hash):
    group_file = out / "group-seal.json"
    boundary_file = out / "boundary-plan.json"
    if digest(group_file) != group_hash or digest(boundary_file) != boundary_hash:
        raise ValueError("selection or boundary forecast differs from the supplied seal")
    reception = json.loads((out / "reception.json").read_bytes())
    selected = json.loads(group_file.read_bytes())
    msc = out / reception["native_file"]
    packets = out / "transport/packets.npz"
    if (digest(msc) != selected["receiver"]["msc_sha256"]
            or digest(packets) != selected["receiver"]["packets_sha256"]):
        raise ValueError("receiver or packet archive differs from the selection seal")
    seen = frozen_history()
    detailed = {}
    for name, row in selected["selections"].items():
        detailed[name] = None if row is None else dict(selection=row, in_registry=row["counter"] in seen,
            fields=selected_projection(packets, row["counter"], evidence_version=2))
    write(out / "group-fields.json", detailed)
    run(HERE / "native_boundary.py", ["score", boundary_file, boundary_hash, msc], out / "boundary-score.json")
    return dict(group_fields_sha256=digest(out / "group-fields.json"),
                boundary_score_sha256=digest(out / "boundary-score.json"))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    acquire = commands.add_parser("receive", help="demodulate once and write forecast seals")
    acquire.add_argument("wav", type=Path)
    acquire.add_argument("dream", type=Path)
    acquire.add_argument("out", type=Path, help="new output directory")
    evaluate = commands.add_parser("score", help="verify separately supplied seal hashes and check fields")
    evaluate.add_argument("out", type=Path)
    evaluate.add_argument("group_sha256")
    evaluate.add_argument("boundary_sha256")
    args = parser.parse_args()
    result = (receive(args.wav, args.dream, args.out) if args.action == "receive" else
              score(args.out, args.group_sha256, args.boundary_sha256))
    print(json.dumps(result, indent=2))
