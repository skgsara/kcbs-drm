"""Trace four specified previous-band flags in the official 13.2 kb/s clean narrowband pair."""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import subprocess
from tempfile import TemporaryDirectory


HERE = Path(__file__).resolve().parent
COD = Path("testvec/testv/bitstreams/nb/stv8c_13200_8kHz.COD")
INPUTS = {
    "fixed": "78a5c3ef2c1dc172e203c560744dd386138808c6be51863b6ad9e54b453407bb",
    "float": "e561715e12f3a8836de12d07c3effd00b982bca001dfabe00547b5f870aa0567",
}
SOURCE = {
    "lib_dec/hq_lr_dec.c": "1bd289bf0d8cc9143207c4de04fb2561ce848a3c9661306b18371dc4d8f1bd35",
    "lib_dec/tcq_core_dec.c": "62554e8dd050e212ad84a799d9bfc169004d368cee6f023e50f8df161b5f3818",
    "lib_com/hq2_core_com.c": "6c778752906cde1c5737aa9969d4c6292d6d55891f49f65cd379c5e146f40a20",
}
FLOAT_PCM = "f6448c4463b3e595082cae2659ca31fc28fa0468c63fb6c67e531081c7ae2fa6"
SLOTS = (1648, 1664, 1702, 1743)
RECORD = 532
LOG = r'''
#include <stdio.h>
extern long frame;
#define OBSERVED (frame==1648 || frame==1664 || frame==1702 || frame==1743)
#define SHOW(tag, a, n) do { if (OBSERVED) { fprintf(stderr,"\nFIELD %ld %s",frame,tag); \
    for (int t=0;t<(n);t++) fprintf(stderr," %d",(int)(a)[t]); fputc('\n',stderr); } } while (0)
'''


def digest(data):
    return hashlib.sha256(data).hexdigest()


def checked(path, expected):
    raw = path.read_bytes()
    if digest(raw) != expected:
        raise ValueError(f"Unexpected SHA-256 for {path}")
    return raw


def instrument(text, anchor, extra, count=1, before=False):
    if text.count(anchor) != count:
        raise ValueError(f"Unexpected source at {anchor}")
    return text.replace(anchor, extra + "\n" + anchor if before else anchor + "\n" + extra)


def build(source, tmp):
    raw = {p: checked(source / p, sha).decode("latin1") for p, sha in SOURCE.items()}
    hq = raw["lib_dec/hq_lr_dec.c"]
    hq = instrument(hq, "last_bitalloc_max_band[i] = (short)get_next_indice( st, 1 );",
                    'if (i==1) {int fields[]={st->next_bit_pos-2,last_bitalloc_max_band[0],'
                    'last_bitalloc_max_band[1]}; SHOW("history",fields,3);}', count=2)
    hq = instrument(hq, "L_band_energy_tmp[i] = L_shl(L_tmp,1);/*Q(Q_band_energy+14-15 +1= Q_band_energy) */",
                    '{int top[]={i,alpha_fx,L_band_energy_tmp[i]}; SHOW("top_energy",top,3);}')
    hq = instrument(hq, "tcq_core_LR_dec( st, inp_vector, bit_budget, bands, band_start, band_width, Rk_fx, npulses, k_sort,",
                    '{int config[]={inner_frame,*is_transient,bit_budget,bands,adjustFlag}; SHOW("config",config,5);}'
                    '\nSHOW("allocation",Rk_fx,bands);', before=True)
    hq = instrument(hq, "/* Prepare floating Rk for next modules */",
                    'SHOW("pulse_counts",npulses,bands); SHOW("spectrum",inp_vector,inner_frame);', before=True)
    tcq = instrument(raw["lib_dec/tcq_core_dec.c"],
                     "k_sort, k_num, p2a_flags, p2a_bands, last_bitalloc, input_frame);",
                     'SHOW("secondary",k_num,2);')
    (tmp / "hq_lr_dec.c").write_text(LOG + hq, encoding="latin1")
    (tmp / "tcq_core_dec.c").write_text(LOG + tcq, encoding="latin1")
    originals = sorted((source / "lib_com").glob("*.c")) + sorted((source / "lib_dec").glob("*.c"))
    files = [tmp / p.name if p.name in ("hq_lr_dec.c", "tcq_core_dec.c") else p for p in originals]
    exe = tmp / "observer"
    subprocess.run(["gcc", "-O0", "-std=gnu99", "-fno-strict-aliasing",
                    *["-I" + str(source / d) for d in ("lib_com", "lib_enc", "lib_dec")],
                    *files, "-lm", "-o", exe], check=True)
    return exe


def decode(exe, coded, tmp):
    path, output = tmp / "selected.192", tmp / "decoded.pcm"
    path.write_bytes(coded)
    proc = subprocess.run([exe, "-q", "8", path, output], check=True, capture_output=True)
    pcm = output.read_bytes()
    if len(pcm) != 883200 or digest(pcm) != FLOAT_PCM:
        raise ValueError("Unexpected floating decoder output")
    trace = {slot: {} for slot in SLOTS}
    for line in proc.stderr.splitlines():
        if line.startswith(b"FIELD "):
            _, slot, key, *items = line.decode().split()
            trace[int(slot)].setdefault(key, []).append(list(map(int, items)))
    return trace


def summarize(fixed, alternate, left, right, slot):
    start = slot * RECORD
    original, variant = (struct.unpack_from("<266H", raw, start) for raw in (fixed, alternate))
    if original[:2] != (0x6B21, 264) or variant[:2] != original[:2]:
        raise ValueError("Expected good 264-bit G.192 words")
    bits = [i for i, pair in enumerate(zip(original[2:], variant[2:], strict=True)) if pair[0] != pair[1]]
    first = bits[0]
    if bits != [first, first+1] or left["history"] != [[first, 0, 0]] or right["history"] != [[first, 1, 1]]:
        raise ValueError("Differing bits do not equal the two transmitted history flags")
    if left["config"] != right["config"] or left["config"][0][:2] != [160, 0]:
        raise ValueError("Expected narrowband nontransient HQ")
    arrays = {}
    for key, length in (("allocation", 17), ("secondary", 2), ("pulse_counts", 17), ("spectrum", 160)):
        a, = left[key]
        b, = right[key]
        if a != b or len(a) != length:
            raise ValueError(f"{key} differs or has unexpected dimensions")
        arrays[key] = digest(struct.pack(f"<{length}i", *a))
    if left["top_energy"] == right["top_energy"] or left["allocation"][0][-2:] != [0, 0]:
        raise ValueError("Expected distinct top-band energy weights and zero top-band allocations")
    packed = []
    for record in (original, variant):
        if set(record[2:]) - {0x7f, 0x81}:
            raise ValueError("Invalid G.192 bit symbol")
        word = bytes(sum((record[2 + i + j] == 0x81) << (7 - j) for j in range(8))
                     for i in range(0, 264, 8))
        if word[0] != 0xe8:
            raise ValueError("Expected E8 signalling")
        packed.append(digest(word))
    return dict(slot=slot, physical_history_bits=bits, fixed_float_history_pairs=["00", "11"],
                packed_word_sha256=packed,
                tcq_budget_bits=left["config"][0][2],
                top_energy_tuples_band_weightQ14_weightedenergy=[left["top_energy"], right["top_energy"]],
                upper_two_band_allocation_Q16=left["allocation"][0][-2:],
                upper_two_band_pulse_counts=left["pulse_counts"][0][-2:],
                secondary_allocation_indices=left["secondary"][0], equal_array_sha256_le_int32=arrays)


def run(cache, source):
    streams = {k: checked(cache / k / COD, sha) for k, sha in INPUTS.items()}
    fixed, alternate = streams["fixed"], streams["float"]
    with TemporaryDirectory() as directory:
        tmp = Path(directory)
        exe = build(source, tmp)
        baseline = decode(exe, fixed, tmp)
        rows = []
        for slot in SLOTS:
            start = slot * RECORD
            replaced = fixed[:start] + alternate[start:start+RECORD] + fixed[start+RECORD:]
            observed = decode(exe, replaced, tmp)
            rows.append(summarize(fixed, alternate, baseline[slot], observed[slot], slot))
    return dict(input_sha256=INPUTS, source_sha256=SOURCE, output_rate_hz=8000, samples_per_run=441600,
                floating_baseline_and_four_individual_replacements_pcm_sha256=FLOAT_PCM, rows=rows)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cache", type=Path, help="original fixed/ and float/ vector cache used by ../official.py")
    parser.add_argument("source", type=Path, help="pristine Nov 4, 2021 TS 26.443 c-code directory")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    result = run(args.cache.resolve(), args.source.resolve())
    if args.check and result != json.loads((HERE / "expected.json").read_bytes()):
        raise SystemExit("field evidence differs from expected.json")
    print(json.dumps(result, indent=2))
