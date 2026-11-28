"""Run the registered KCBS-2 IQ acquisition schedule on public UberSDR receivers.

Each session probes the DRM carriers on every receiver, assigns each receiver to the
carrier with the clearest DRM block, and records back-to-back iq48 segments with packet
timing. A finished segment is losslessly converted to FLAC; the WAV is removed only after
the FLAC decodes to the recorder's PCM SHA-256. Every decision is appended to log.jsonl.
Recordings centred at 6122 kHz place the 6140 kHz DRM channel at +18 kHz and the 6100 kHz
AM carrier at -22 kHz on one sample clock.
"""
import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import sys
import threading
import time
import wave

import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))
import record_ubersdr_iq as rec  # noqa: E402

RECEIVERS = {
    "jl1edu": dict(origin="https://ubersdr.jl1edu.freeddns.org", segment_s=3600),
    "7l4iou": dict(origin="https://7l4iou.tunnel.ubersdr.org", segment_s=3500),
}
# carrier -> (tuning centre, DRM channel offset from centre)
CARRIERS = {"3205": (3_205_000, 0), "6140": (6_122_000, 18_000)}
PROBE_S = 12
GATE_DB = 3.0
REPROBE_S = 300
LOCK = threading.Lock()


def utc():
    return datetime.now(timezone.utc)


def log(out, **event):
    event = dict(utc=utc().isoformat(), **event)
    with LOCK:
        with (out / "log.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(event) + "\n")
        print(json.dumps(event), flush=True)


def drm_excess_db(path, offset_hz):
    """In-channel (|f-offset| < 4.5 kHz) minus adjacent (5.5-9.5 kHz away, inside +-23 kHz) mean power."""
    with wave.open(str(path)) as w:
        x = np.frombuffer(w.readframes(w.getnframes()), "<i2").reshape(-1, 2).astype(np.float64)
    z = x[:, 0] + 1j * x[:, 1]
    n = 4096
    if len(z) < 4 * n:
        return None
    seg = z[: len(z) // n * n].reshape(-1, n) * np.hanning(n)
    p = 10 * np.log10(np.mean(np.abs(np.fft.fftshift(np.fft.fft(seg, axis=1), axes=1)) ** 2, axis=0) + 1e-12)
    f = (np.arange(n) - n / 2) * rec.RATE / n - offset_hz
    inside = p[np.abs(f) < 4500]
    adj = p[(np.abs(f) > 5500) & (np.abs(f) < 9500) & (np.abs(f + offset_hz) < 23000)]
    return float(inside.mean() - adj.mean())


def probe(out, name, carrier, decoder):
    centre, offset = CARRIERS[carrier]
    path = out / "probes" / f"{name}-{carrier}-{utc().strftime('%Y%m%dT%H%M%SZ')}.wav"
    path.parent.mkdir(parents=True, exist_ok=True)
    receipt = rec.record(RECEIVERS[name]["origin"], centre, PROBE_S, path, decoder)
    excess = drm_excess_db(path, offset) if receipt["sample_pairs"] else None
    path.unlink(missing_ok=True)
    log(out, kind="probe", receiver=name, carrier=carrier, centre_hz=centre,
        pairs=receipt["sample_pairs"], error=receipt.get("error"), excess_db=excess)
    return excess


def to_flac(wav, receipt):
    flac = wav.with_suffix(".flac")
    with sf.SoundFile(str(wav)) as src, sf.SoundFile(str(flac), "w", rec.RATE, 2, "PCM_16", format="FLAC") as dst:
        for block in src.blocks(blocksize=rec.RATE * 10, dtype="int16"):
            dst.write(block)
    h = sha256()
    with sf.SoundFile(str(flac)) as src:
        for block in src.blocks(blocksize=rec.RATE * 10, dtype="int16"):
            h.update(block.astype("<i2", copy=False).tobytes())
    ok = h.hexdigest() == receipt["iq_pcm_sha256"]
    if ok:
        wav.unlink()
    return flac, ok


def record_receiver(out, name, carrier, until, decoder):
    centre, offset = CARRIERS[carrier]
    while utc() < until:
        seconds = int(min(RECEIVERS[name]["segment_s"], (until - utc()).total_seconds()))
        if seconds < 60:
            return
        wav = out / f"{name}-{centre // 1000}-{utc().strftime('%Y%m%dT%H%M%SZ')}.wav"
        log(out, kind="segment_start", receiver=name, carrier=carrier, centre_hz=centre,
            drm_offset_hz=offset, seconds=seconds, file=wav.name)
        receipt = rec.record(RECEIVERS[name]["origin"], centre, seconds, wav, decoder, packet_timing=True)
        receipt.update(receiver=name, carrier=carrier, drm_offset_hz=offset)
        if receipt["sample_pairs"]:
            flac, ok = to_flac(wav, receipt)
            receipt.update(flac=flac.name, flac_bytes=flac.stat().st_size, flac_pcm_hash_verified=ok)
        else:
            wav.unlink(missing_ok=True)
        wav.with_name(wav.name + ".receipt.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
        log(out, kind="segment_end", receiver=name, file=wav.name, seconds=receipt["sample_seconds"],
            error=receipt.get("error"), flac_ok=receipt.get("flac_pcm_hash_verified"))
        if receipt.get("error"):
            time.sleep(10)


def session(out, until, carriers, decoder_source):
    out.mkdir(parents=True, exist_ok=True)
    decoder = lambda: rec.upstream_decoder(decoder_source)  # noqa: E731  one decoder per thread
    assigned = {}
    while utc() < until and len(assigned) < len(RECEIVERS):
        for name in RECEIVERS:
            if name in assigned:
                continue
            scores = {c: probe(out, name, c, decoder()) for c in carriers}
            good = {c: s for c, s in scores.items() if s is not None and s >= GATE_DB}
            if good:
                assigned[name] = max(good, key=good.get)
                log(out, kind="assign", receiver=name, carrier=assigned[name], scores=scores)
                t = threading.Thread(target=record_receiver, args=(out, name, assigned[name], until, decoder()),
                                     daemon=False)
                t.start()
        if len(assigned) < len(RECEIVERS):
            time.sleep(REPROBE_S)
    log(out, kind="probing_done", assigned=assigned)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--start", required=True, help="UTC ISO time to begin probing")
    ap.add_argument("--end", required=True, help="UTC ISO time recording stops")
    ap.add_argument("--carriers", default="3205,6140")
    ap.add_argument("--ubersdr-source", type=Path, required=True)
    a = ap.parse_args()
    start = datetime.fromisoformat(a.start).astimezone(timezone.utc)
    end = datetime.fromisoformat(a.end).astimezone(timezone.utc)
    a.out.mkdir(parents=True, exist_ok=True)
    log(a.out, kind="scheduled", start=start.isoformat(), end=end.isoformat(), carriers=a.carriers)
    while utc() < start:
        time.sleep(min(30, (start - utc()).total_seconds()))
    session(a.out, end, a.carriers.split(","), a.ubersdr_source)


if __name__ == "__main__":
    main()
