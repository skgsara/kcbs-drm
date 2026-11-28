"""Compare clock-matched excerpts of two existing, public KCBS-2 AAC recordings."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
from urllib.request import Request, urlopen

import numpy as np
from scipy import signal


RATE = 8000
RANGES = ((0, 8000000), (8000000, 10500001), (24000000, 32000001))
SOURCES = {
    "19": ("04_17_21", 541700594, "4d8dc603db2708d0837af24624702aeff22770c6", (
        "e5e99132b3ea10683a201453460560ca0db42874878afce3c56fcb96f78a1f35",
        "48495af3dce3a4debb7ecf7db999b2f9d53a4240331b30aef9e34599cd3f126f",
        "9c7a44539829b9e885a2a18d01c3946f5460cd18319bfacd5637793ebe190b9a")),
    "20": ("04_17_32", 593347432, "2fd9c25de703d03f4b40675ebc5ea29f9d945295", (
        "849cd6f04c8b6a3648f3624bdf919fe704df03fbac0c9002b02616d35799d68c",
        "2740367d7688312651c5670c4707424d60550dabeee8f79ad7029fb463763c53",
        "7d5c7da8aa732a688674a2a9202d895a95a330d8b23a100fd9c9fb9993a5d1b5")),
}


def get_source(day, directory, fetch):
    start, full_size, archive_sha1, hashes = SOURCES[day]
    item = f"kcbs2.2026-11-{day}"
    name = f"{item}.{start}.m4a"
    url = f"https://archive.org/download/{item}/{name}"
    path = directory / name
    if fetch and not path.exists():
        with TemporaryDirectory(dir=directory) as staging:
            temp = Path(staging) / name
            with temp.open("xb") as out:
                for (a, b), expected in zip(RANGES, hashes, strict=True):
                    request = Request(url, headers={"Range": f"bytes={a}-{b-1}"})
                    with urlopen(request, timeout=45) as response:
                        if response.status != 206 or response.headers.get("Content-Range") != f"bytes {a}-{b-1}/{full_size}":
                            raise ValueError("archive did not return the requested range")
                        raw = response.read(b - a + 1)
                    if len(raw) != b - a or sha256(raw).hexdigest() != expected:
                        raise ValueError("downloaded range differs from the original receipt")
                    out.seek(a)
                    out.write(raw)
                out.truncate(full_size)
            temp.replace(path)
    if path.stat().st_size != full_size:
        raise ValueError(f"unexpected archive extent for {name}")
    with path.open("rb") as stream:
        for (a, b), expected in zip(RANGES, hashes, strict=True):
            stream.seek(a)
            if sha256(stream.read(b - a)).hexdigest() != expected:
                raise ValueError(f"source range {a}:{b} differs for {name}")
    return path, dict(metadata=f"https://archive.org/metadata/{item}", media=url, clock_in_filename=start,
                      full_size=full_size, archive_listed_full_sha1=archive_sha1, range_sha256=hashes)


def band(x, lo, hi):
    return signal.sosfiltfilt(signal.butter(4, [lo, hi], btype="bandpass", fs=RATE, output="sos"), x)


def decode(path, start, duration):
    origin, extent = start - 12, duration + 114  # accommodate lag fit and +90 s negative control
    cmd = ["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries", "packet=pts_time,pos,size",
           "-read_intervals", f"{origin-2}%+{extent+4}", "-of", "json", str(path)]
    packets = json.loads(subprocess.check_output(cmd))["packets"]
    offsets = [(int(p["pos"]), int(p["pos"]) + int(p["size"])) for p in packets]
    if not all(any(a <= lo <= hi <= b for a,b in ((0, 10500001), RANGES[2])) for lo, hi in offsets):
        raise ValueError("AAC packet extends outside the verified source bytes")
    pts = [float(p["pts_time"]) for p in packets]
    if min(pts) > origin or max(pts) < origin + extent:
        raise ValueError("incomplete AAC packet timeline")
    raw = subprocess.check_output(["ffmpeg", "-nostdin", "-v", "error", "-xerror", "-ss", str(origin),
                                   "-i", str(path), "-t", str(extent), "-vn", "-ac", "1", "-ar", str(RATE),
                                   "-f", "s16le", "-"])
    if len(raw) != extent * RATE * 2:
        raise ValueError("incomplete PCM timeline")
    return band(np.frombuffer(raw, "<i2").astype(float) / 32768, 300, 3000), dict(
        origin_seconds=origin, decoded_seconds=extent, mono_s16le_sha256=sha256(raw).hexdigest(),
        aac_packets_checked=len(packets), aac_byte_extent=[min(a for a,b in offsets), max(b for a,b in offsets)])


def window(x, t, length):
    i = round((12 + t) * RATE)
    return x[i:i + length * RATE]


def fit(x, y, start, base):
    a, b = window(x, start, 20), window(y, start + base - 10, 40)
    products = signal.correlate(b, a, mode="valid", method="fft")
    power = np.r_[0.0, np.cumsum(b * b)]
    energies = (power[len(a):] - power[:-len(a)]) * (a @ a)
    corr = np.divide(products, np.sqrt(np.maximum(0, energies)), where=energies > 1e-16,
                     out=np.full_like(products, -np.inf))
    if not np.any(np.isfinite(corr)):
        raise ValueError("insufficient energy to fit timing")
    i = int(np.argmax(corr))
    return i / RATE - 10, float(np.clip(corr[i], -1, 1))


def correlation(a, b):
    norm = np.sqrt((a @ a) * (b @ b))
    return round(float(np.clip((a @ b) / norm, -1, 1)), 6) if norm else None


def levels(x):
    power = x @ x / len(x)
    if power == 0:
        return [None, None]
    _, spectrum = signal.welch(x, fs=RATE, nperseg=2048)
    fraction = np.convolve(spectrum, np.ones(7), "valid").max() / spectrum.sum()
    return [round(float(10 * np.log10(power)), 2), round(float(fraction), 4)]


def compare(x, y, duration, start=0, base=0, bands=False):
    lag, peak = fit(x, y, start, base)
    rows = []
    for t in range(start + 20, duration, 10):
        a, b = window(x, t, 10), window(y, t + base + lag, 10)
        row = dict(start_s=t, r=correlation(a, b), nov19=levels(a), nov20=levels(b))
        if bands:
            row["band_r"] = [correlation(band(a, lo, hi), band(b, lo, hi))
                             for lo, hi in ((300, 900), (900, 1600), (1600, 3000))]
        rows.append(row)
    return dict(fit_start_s=start, fixed_clock_offset_s=base, fitted_lag_s=round(lag, 6),
                fit_r=round(peak, 6), evaluation=rows)


def run(directory, fetch):
    directory.mkdir(exist_ok=True, parents=True)
    sources, paths = {}, {}
    for day in SOURCES:
        paths[day], sources[day] = get_source(day, directory, fetch)
    result = dict(sources=sources, source_ranges_half_open=RANGES, decoded_mono_rate_hz=RATE,
                  lag_definition="Nov 20 clock = Nov 19 clock + fixed offset + fitted lag",
                  levels_columns=["300–3000 Hz dBFS", "largest 7-bin Welch power fraction (27.34 Hz)"],
                  band_hz=[[300,900],[900,1600],[1600,3000]], windows={})
    for clock, duration, start_19 in (("04:20:00", 60, 159), ("05:00:00", 300, 2559)):
        a, source_a = decode(paths["19"], start_19, duration)
        b, source_b = decode(paths["20"], start_19 - 11, duration)
        shift = int(3.25 * RATE)
        shifted = np.concatenate([np.zeros(shift), a[:-shift]])
        rows = dict(duration_s=duration, decoded_sources={"19":source_a,"20":source_b},
                    primary=compare(a,b,duration), wrong_time=compare(a,b,duration,base=90),
                    same_file_plus_3_25_s=compare(a,shifted,duration))
        if clock == "05:00:00":
            rows.update(exploratory_audible_fit=compare(a,b,duration,start=40,bands=True),
                        exploratory_wrong_time=compare(a,b,duration,start=40,base=90,bands=True))
        result["windows"][clock] = rows
    return result


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("media_dir", type=Path)
    cli.add_argument("--fetch", action="store_true", help="fetch only the documented public ranges into a new sparse source file")
    args = cli.parse_args()
    print(json.dumps(run(args.media_dir, args.fetch), indent=2, allow_nan=False))
