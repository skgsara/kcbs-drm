"""Record a granted UberSDR iq48 stream to a new stereo I/Q WAV; print its receipt."""
import argparse
from contextlib import ExitStack
import csv
from datetime import datetime, timezone
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import ssl
import sys
import time
from urllib.parse import urlencode, urlsplit
from urllib.request import build_opener, HTTPRedirectHandler, HTTPSHandler, Request
from uuid import uuid4
import wave


RATE = 48_000
AGENT = "KCBS public IQ recorder"


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def https_origin(value):
    parts = urlsplit(value)
    if (parts.scheme != "https" or not parts.hostname or parts.username is not None
            or parts.password is not None or parts.path not in ("", "/") or parts.query or parts.fragment):
        raise ValueError("expected an HTTPS origin with a hostname and no credentials, path, query or fragment")
    return f"https://{parts.netloc}"


def upstream_decoder(source):
    path = source / "clients/python/pcm_v4.py"
    spec = importlib.util.spec_from_file_location("ubersdr_pcm_v4", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.PCMv4Decoder()


def grant(origin, session, tls):
    request = Request(origin + "/connection", method="POST",
                      data=json.dumps({"user_session_id": session}).encode(),
                      headers={"Accept": "application/json", "Content-Type": "application/json", "User-Agent": AGENT})
    opener = build_opener(HTTPSHandler(context=tls), NoRedirect())
    with opener.open(request, timeout=10) as response:
        if response.status != 200 or response.headers.get_content_type() != "application/json":
            raise ValueError("receiver did not return an HTTP 200 JSON grant")
        body = json.loads(response.read(64 * 1024))
    modes = body.get("allowed_iq_modes") if isinstance(body, dict) else None
    if not isinstance(modes, list) or "iq48" not in modes or body.get("allowed") is not True:
        raise ValueError("receiver did not grant iq48")


def copy_packets(ws, decoder, out, target, receipt, timing=None):
    deadline = time.monotonic() + target / RATE + 15
    idle_deadline = time.monotonic() + 15
    pcm_hash = sha256()
    previous_anchor = None
    try:
        while receipt["sample_pairs"] < target:
            remaining = min(deadline, idle_deadline) - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("time limit reached before the requested samples arrived")
            packet = ws.recv(timeout=remaining)
            if isinstance(packet, str):
                control = json.loads(packet)
                if isinstance(control, dict) and control.get("type") in ("error", "denied", "rejected", "disconnect"):
                    raise ValueError("receiver ended the IQ session")
                continue
            data, header = decoder.decode_packet_le(packet)
            if (header.sample_rate != RATE or header.channels != 2 or header.shift != 0 or header.sample_count <= 0
                    or header.sample_count % 2 or len(data) != header.sample_count * 2):
                raise ValueError("expected lossless interleaved IQ at 48000 Hz")
            offset = receipt["sample_pairs"]
            if header.timestamp_nanos:
                anchor = [offset, header.timestamp_nanos]
                if previous_anchor is None:
                    receipt["first_timestamp_sample_and_unix_ns"] = anchor
                else:
                    expected_ns = previous_anchor[1] + round((offset - previous_anchor[0]) * 1_000_000_000 / RATE)
                    jump = abs(anchor[1] - expected_ns)
                    receipt["max_abs_timestamp_jump_ns"] = max(receipt["max_abs_timestamp_jump_ns"], jump)
                    receipt["timestamp_jumps_over_one_sample"] += int(jump * RATE > 1_000_000_000)
                receipt["timestamped_packets"] += 1
                receipt["last_timestamp_sample_and_unix_ns"] = previous_anchor = anchor
            chunk = data[:4 * (target - offset)]
            out.writeframes(chunk)  # Keep the WAV size fields current during recording.
            pcm_hash.update(chunk)
            written_pairs = len(chunk) // 4
            receipt["sample_pairs"] += written_pairs
            receipt["packets"] += 1
            if timing is not None:
                timing.writerow((offset, written_pairs, header.timestamp_nanos or ""))
            idle_deadline = time.monotonic() + 15
    finally:
        receipt["iq_pcm_sha256"] = pcm_hash.hexdigest()


def open_stream(origin, frequency_hz):
    from websockets.sync.client import connect

    session = str(uuid4())
    tls = ssl.create_default_context()
    grant(origin, session, tls)
    params = urlencode(dict(user_session_id=session, frequency=frequency_hz, mode="iq48", format="pcm-zstd", version=4))
    return connect(f"wss://{urlsplit(origin).netloc}/ws?{params}", ssl=tls, open_timeout=12,
                   close_timeout=2, compression=None, user_agent_header=AGENT)


def record(origin, frequency_hz, seconds, output, decoder, packet_timing=False):
    target = seconds * RATE
    receipt = dict(origin=origin, frequency_hz=frequency_hz, mode="iq48", sample_rate_hz=RATE,
                   started_utc=datetime.now(timezone.utc).isoformat(), requested_seconds=seconds,
                   sample_pairs=0, packets=0, timestamped_packets=0, timestamp_jumps_over_one_sample=0,
                   max_abs_timestamp_jump_ns=0, first_timestamp_sample_and_unix_ns=None,
                   last_timestamp_sample_and_unix_ns=None, iq_pcm_sha256=sha256(b"").hexdigest())
    started = time.monotonic()
    timing_path = output.with_name(output.name + ".timing.csv")
    if packet_timing and timing_path.exists():
        raise FileExistsError(f"Packet timing file already exists: {timing_path}")
    with ExitStack() as files:
        file = files.enter_context(output.open("xb"))
        out = files.enter_context(wave.open(file, "wb"))
        out.setparams((2, 2, RATE, 0, "NONE", "not compressed"))
        out.writeframes(b"")
        timing = None
        if packet_timing:
            timing_file = files.enter_context(timing_path.open("x", newline="", encoding="ascii"))
            timing = csv.writer(timing_file, lineterminator="\n")
            timing.writerow(("sample_offset", "sample_pairs", "receiver_unix_ns"))
            receipt["packet_timing_file"] = timing_path.name
        try:
            with open_stream(origin, frequency_hz) as ws:
                copy_packets(ws, decoder, out, target, receipt, timing)
        except (Exception, KeyboardInterrupt) as error:
            receipt["error"] = f"{type(error).__name__}: {error}"
    receipt["wall_seconds"] = round(time.monotonic() - started, 3)
    receipt["sample_seconds"] = receipt["sample_pairs"] / RATE
    receipt["sample_target_reached"] = receipt["sample_pairs"] == target
    return receipt


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("origin", help="public UberSDR HTTPS origin")
    parser.add_argument("--frequency-hz", type=int, required=True)
    parser.add_argument("--seconds", type=int, required=True, help="requested sample duration in whole seconds")
    parser.add_argument("--ubersdr-source", required=True, type=Path, help="local ka9q_ubersdr checkout")
    parser.add_argument("--out", required=True, type=Path, help="new WAV file")
    parser.add_argument("--packet-timing", action="store_true",
                        help="write packet sample ranges and station timestamps to <WAV>.timing.csv")
    args = parser.parse_args(argv)
    if args.seconds <= 0 or args.seconds * RATE * 4 > 0xffffffff - 36 or args.frequency_hz <= 0:
        parser.error("positive Hz and duration fitting a standard RIFF WAV are required")
    try:
        result = record(https_origin(args.origin), args.frequency_hz, args.seconds, args.out,
                        upstream_decoder(args.ubersdr_source), args.packet_timing)
    except (OSError, ValueError, ImportError) as error:
        print(json.dumps({"error": str(error)}), file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2))
    return int(not result["sample_target_reached"] or "error" in result or result["timestamp_jumps_over_one_sample"] > 0)


if __name__ == "__main__":
    sys.exit(main())
