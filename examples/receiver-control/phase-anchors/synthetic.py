"""Compare the transported clear words to the independent stock encoder on its 40-group fixture."""
from argparse import ArgumentParser
import gzip
from hashlib import sha256
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

HERE = Path(__file__).resolve().parent
CASE = HERE.parent
sys.path.insert(0, str(CASE))
from phase_anchors import run
from receive import unpack_fixture
from verify import compare, read_g192, receipt, word_digest, FIRST, GROUPS


def checked(path, expected):
    data = path.read_bytes()
    if sha256(data).hexdigest() != expected:
        raise ValueError(f"SHA-256 mismatch for {path.name}")
    return data


def evaluate(path):
    stock_seal = json.loads((CASE / "result/receiver.json").read_bytes())
    sender_seal = json.loads((CASE / "fixture/sender.json").read_bytes())["files"]["sender.192.gz"]
    with TemporaryDirectory() as tmp:
        output = Path(tmp) / "out"
        native = Path(tmp) / "native.msc.bin"
        native.write_bytes(gzip.decompress(path.read_bytes()) if path.suffix == ".gz" else path.read_bytes())
        receiver_hashes = stock_seal["source_and_receiver_sha256"]
        checked(native, receiver_hashes["msc"])
        report = run(native, output)
        if report["stock"]["packets_sha256"] != receiver_hashes["packets"]:
            raise ValueError("stock packet snapshot differs from the original receiver seal")
        sender_gzip = checked(CASE / "fixture/sender.192.gz", sender_seal["gzip_sha256"])
        sender_raw = gzip.decompress(sender_gzip)
        if sha256(sender_raw).hexdigest() != sender_seal["uncompressed_sha256"]:
            raise ValueError("sender encoder output differs from its seal")
        sender = read_g192(sender_raw)
        original = gzip.decompress(checked(CASE / "result/received.192.gz",
                                            stock_seal["output_sha256"]["received.192.gz"]))
        if sha256(original).hexdigest() != receiver_hashes["receiver_g192"]:
            raise ValueError("previous receiver G.192 differs from its seal")
        expected = [receipt(i, {}) for i in range(60 * GROUPS)]
        result = {}
        for name in ("stock", "extended"):
            words, known, _, transport, _ = unpack_fixture(output / name / "packets.npz", FIRST, GROUPS)
            actual = [word.tobytes() if valid else None for word, valid in zip(words, known.all(axis=1), strict=True)]
            if name == "stock" and actual != read_g192(original):
                raise ValueError("stock word/erasure timeline differs from sealed receiver")
            scores = compare(actual, sender, expected)
            result[name] = dict(packets=transport["packets_received"], complete_dus=transport["complete_data_units"],
                                totals=scores["total"],
                                exact_by_position=[v["exact_supplied"] for v in scores["by_position"].values()],
                                word_and_erasure_sha256=word_digest(actual))
        return dict(first_counter=FIRST, groups=GROUPS, native_msc_sha256=report["native_msc_sha256"],
                    stock_packet_sha256=receiver_hashes["packets"], sender_g192_sha256=sender_seal["uncompressed_sha256"],
                    additions=report["extra_rows"], overlay_quarantine=report["extended_quarantine"], **result)


if __name__ == "__main__":
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--native", type=Path, default=HERE / "synthetic-native.msc.bin.gz")
    parser.add_argument("--check", type=Path, help="compare every result to the saved JSON")
    args = parser.parse_args()
    evaluation = evaluate(args.native)
    if args.check and json.loads(args.check.read_bytes()) != evaluation:
        raise SystemExit("synthetic result differs from the saved file")
    print(json.dumps(evaluation, indent=2))
