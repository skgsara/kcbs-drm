"""Build a read-only b255 observer in a temporary copy of two floating-point TS 26.443 sources."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from pathlib import Path
import subprocess
import tempfile

HASHES = {
    "ACcontextMapping_dec.c": "cbe06ad7b27179344c69a15306d94794e6fe245e5e6134ac6703a10c13eae524",
    "tcx_utils_dec.c": "d9a4cdebd8b97fb7c94a7ebbd5977d2c85da2a9d7cc106760000d492e1e8cea0",
}


def replace_once(text, old, new):
    if text.count(old) != 1:
        raise ValueError(f"unexpected stock source around {old!r}")
    return text.replace(old, new)


def observe_reader(text):
    text = replace_once(text, '#include "prot.h"', '''#include "prot.h"
#include <stdio.h>
extern long frame;
int watched_residual = -1;
long watched_frame = -1;''')
    text = replace_once(text, "    /* Decode signs */",
                        "    int sign_start = st->next_bit_pos;\n    /* Decode signs */")
    anchor = "            x[k] *= 1-2*get_next_indice_1(st);"
    text = replace_once(text, anchor, '''            int position = st->next_bit_pos, magnitude = x[k];
''' + anchor + r'''
            if (position == 255)
                fprintf(stderr, "B255_ROLE,%ld,sign,%d,%d,%d\n", frame, k, magnitude, x[k]);''')
    text = replace_once(text, "    /*Decode Residual Q*/", '''    int sign_end = st->next_bit_pos;
    watched_residual = -1;
    watched_frame = frame;
    /*Decode Residual Q*/''')
    anchor = "        x[nt+k] = get_indice_1(st, lsbs_bit_pos - k);"
    text = replace_once(text, anchor, anchor + r'''
        if (lsbs_bit_pos - k == 255) {
            watched_residual = k;
            fprintf(stderr, "B255_ROLE,%ld,residual,%d,%d,%d\n", frame, k, resQBits, x[nt+k]);
        }''')
    return replace_once(text, "    return resQBits;", r'''    fprintf(stderr,
        "B255_RANGES,%ld,%d,%d,%d,%d,%d,%d\n", frame,
        start_bit_pos, start_bit_pos + nbbits, sign_start, sign_end,
        lsbs_bit_pos + 1 - resQBits, lsbs_bit_pos + 1);
    return resQBits;''')


def observe_consumer(text):
    text = replace_once(text, '#include "prot.h"', r'''#include "prot.h"
#include <stdio.h>
extern int watched_residual;
extern long watched_frame, frame;
static void observe_residual(const char *operation, int index, int bin, int value)
{
    if (frame == watched_frame && index == watched_residual)
        fprintf(stderr, "B255_USE,%ld,%s,%d,%d,%d\n", frame, operation, index, bin, value);
}''')
    gain = "if(prm[bits]==0)"
    text = replace_once(text, gain, 'observe_residual("gain", bits, -1, prm[bits]);\n        ' + gain)
    before, spectrum = text.split("int tcx_res_invQ_spec(", 1)
    # Each inverse-quantizer branch advances its own bit index. Observe before incrementing.
    consumers = [
        ("if (prm[bits++] == 0)", "refine_nonzero"),
        ("if(prm[bits++]==0)", "refine_nonzero"),
        ("if (prm[bits++] != 0)", "activate_zero"),
        ("if(prm[bits++]==1)", "activate_zero"),
        ("x[i] = (prm[bits++] * 2.64f - 1.32f) * fac_p;", "sign_of_activated_zero"),
        ("x[i]=(prm[bits++]*2.f-1.f)*thres;", "sign_of_activated_zero"),
    ]
    for anchor, operation in consumers:
        observation = f'observe_residual("{operation}", bits, i, prm[bits]);\n                '
        spectrum = replace_once(spectrum, anchor, observation + anchor)
    return before + "int tcx_res_invQ_spec(" + spectrum


def build(source, output):
    if output.exists():
        raise ValueError(f"output already exists: {output}")
    with tempfile.TemporaryDirectory() as temp:
        directory = Path(temp)
        for name, observe in zip(HASHES, (observe_reader, observe_consumer), strict=True):
            path = source / "lib_dec" / name
            if sha256(path.read_bytes()).hexdigest() != HASHES[name]:
                raise ValueError(f"unexpected source digest for {name}")
            (directory / name).write_text(observe(path.read_text()))
        sources = sorted((source / "lib_com").glob("*.c")) + sorted((source / "lib_dec").glob("*.c"))
        includes = [f"-I{source / part}" for part in ("lib_com", "lib_dec", "lib_enc")]

        def compile_one(indexed_source):
            i, original = indexed_source
            instrumented = directory / original.name
            unit = instrumented if instrumented.exists() else original
            obj = directory / f"{i}.o"
            subprocess.run(["cc", "-std=gnu99", "-O1", "-fno-strict-aliasing", *includes,
                            "-c", unit, "-o", obj], check=True)
            return obj

        with ThreadPoolExecutor(max_workers=3) as workers:
            objects = list(workers.map(compile_one, enumerate(sources)))
        subprocess.run(["cc", *objects, "-lm", "-o", output], check=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True, help="November 4, 2021 floating c-code directory")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    build(args.source.resolve(), args.out.resolve())
