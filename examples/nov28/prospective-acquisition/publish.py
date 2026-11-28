"""Publish verified acquisition segments to an orphan data branch as they finish.

Each segment whose receipt reports a verified FLAC is split into playable 300-second FLAC
parts (about 44 MB each). The parts must re-decode to the recorder's iq_pcm_sha256 before
anything is committed. The receipt, gzipped packet timing and parts.json travel with
the parts. Each published segment is its own commit and push, so a lost container costs
at most the segment in progress.
"""
import argparse
from datetime import datetime, timezone
import gzip
from hashlib import sha256
import json
from pathlib import Path
import shutil
import subprocess
import time

import soundfile as sf

PART_S = 300
RATE = 48000
HERE = Path(__file__).resolve().parent
TRAILER = ("\n\nCo-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>\n"
           "Claude-Session: https://claude.ai/code/session_01Afh4hZVLsao2D7RCTmD7Jy\n")


def git(repo, *args, check=True):
    return subprocess.run(["git", "-C", str(repo), *args], check=check, capture_output=True, text=True)


def file_digest(path):
    h = sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def split(flac, dest):
    parts, pcm, first = [], sha256(), 0
    with sf.SoundFile(str(flac)) as src:
        total = src.frames
        index = 1
        while first < total:
            n = min(PART_S * RATE, total - first)
            path = dest / f"part-{index:02d}.flac"
            with sf.SoundFile(str(path), "w", RATE, 2, "PCM_16", format="FLAC") as dst:
                left = n
                while left:
                    block = src.read(min(left, 480000), dtype="int16")
                    pcm.update(block.astype("<i2", copy=False).tobytes())
                    dst.write(block)
                    left -= len(block)
            parts.append(dict(file=path.name, first_sample_pair=first, sample_pairs=n,
                              bytes=path.stat().st_size, sha256=file_digest(path)))
            first += n
            index += 1
    return parts, pcm.hexdigest(), total


def index_readme(data):
    rows = []
    for p in sorted(data.glob("session-*/*/parts.json")):
        meta = json.loads(p.read_text(encoding="utf-8"))
        r = meta["receipt_summary"]
        rows.append(f"| `{p.parent.parent.name}/{p.parent.name}` | {r['receiver']} | {r['frequency_hz']} | "
                    f"{r['drm_offset_hz']:+d} | {r['started_utc']} | {r['sample_seconds']:.1f} | "
                    f"{len(meta['parts'])} | `{r['iq_pcm_sha256'][:16]}…` |")
    head = (HERE / "data-branch-README.md").read_text(encoding="utf-8")
    table = ("\n| recording | receiver | tuned Hz | DRM offset Hz | started (UTC) | seconds | parts | PCM SHA-256 |\n"
             "|---|---|---:|---:|---|---:|---:|---|\n" + "\n".join(rows) + "\n")
    (data / "README.md").write_text(head + table, encoding="utf-8")


def push(data, branch):
    for attempt in range(5):
        if git(data, "push", "-u", "origin", branch, check=False).returncode == 0:
            return True
        time.sleep(2 ** (attempt + 1))
    return False


def publish_once(sources, data, branch):
    done = 0
    for receipt_path in sorted(p for s in sources for p in s.glob("*.receipt.json")):
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        if not receipt.get("flac_pcm_hash_verified"):
            continue
        stem = receipt_path.name[: -len(".wav.receipt.json")]
        dest = data / receipt_path.parent.name / stem
        if (dest / "parts.json").exists():
            continue
        dest.mkdir(parents=True, exist_ok=True)
        parts, pcm, total = split(receipt_path.parent / receipt["flac"], dest)
        if pcm != receipt["iq_pcm_sha256"] or total != receipt["sample_pairs"]:
            shutil.rmtree(dest)
            print(json.dumps(dict(error="split PCM mismatch", recording=stem)), flush=True)
            continue
        shutil.copyfile(receipt_path, dest / "receipt.json")
        timing = receipt_path.parent / f"{stem}.wav.timing.csv"
        if timing.exists():
            with timing.open("rb") as f, (dest / "timing.csv.gz").open("wb") as raw, \
                    gzip.GzipFile(filename="timing.csv", mode="wb", fileobj=raw, mtime=0) as g:
                shutil.copyfileobj(f, g)
        summary = {k: receipt.get(k) for k in ("receiver", "origin", "frequency_hz", "drm_offset_hz", "started_utc",
                                               "sample_pairs", "sample_seconds", "iq_pcm_sha256", "error",
                                               "timestamp_jumps_over_one_sample")}
        (dest / "parts.json").write_text(json.dumps(dict(receipt_summary=summary, part_seconds=PART_S,
                                                         parts=parts), indent=2), encoding="utf-8")
        log = receipt_path.parent / "log.jsonl"
        if log.exists():
            shutil.copyfile(log, data / receipt_path.parent.name / "log.jsonl")
        index_readme(data)
        git(data, "add", "-A")
        git(data, "commit", "-q", "-m",
            f"Add {receipt_path.parent.name}/{stem} ({summary['sample_seconds']:.0f} s, {len(parts)} FLAC parts)" + TRAILER)
        ok = push(data, branch)
        print(json.dumps(dict(utc=datetime.now(timezone.utc).isoformat(), published=stem, parts=len(parts),
                              pushed=ok)), flush=True)
        done += 1
    return done


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data", type=Path, required=True, help="checkout of the orphan data branch")
    ap.add_argument("--branch", required=True)
    ap.add_argument("--sources", type=Path, nargs="+", required=True)
    ap.add_argument("--until", help="keep polling until this UTC ISO time")
    ap.add_argument("--interval", type=int, default=300)
    a = ap.parse_args()
    until = datetime.fromisoformat(a.until).astimezone(timezone.utc) if a.until else None
    while True:
        publish_once(a.sources, a.data, a.branch)
        if until is None or datetime.now(timezone.utc) >= until:
            break
        time.sleep(a.interval)


if __name__ == "__main__":
    main()
