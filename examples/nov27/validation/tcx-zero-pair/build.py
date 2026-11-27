"""Build a read-bounded diagnostic decoder from the published EVS floating-point C code."""
import argparse
from hashlib import sha256
from pathlib import Path
import re
import subprocess
import tempfile

EXPECTED_SOURCE = "f8b915e8f53029629dd1bbdfd2da128fa850430459993feccce41c2b65c91acd"

# All five reference decoder bit accessors, including absolute reads and signed cursor moves.
ACCESSORS = {
    "get_next_indice": ("st->next_bit_pos", "nb_bits", False),
    "get_next_indice_1": ("st->next_bit_pos", "1", False),
    "get_next_indice_tmp": ("st->next_bit_pos", "nb_bits", True),
    "get_indice": ("pos", "nb_bits", False),
    "get_indice_1": ("pos", "1", False),
}
GUARD = """
#include <stdio.h>
#include <stdlib.h>
static int prefix_limit = 0;
static void guard_prefix(int start, int width, int cursor_move)
{
    if (prefix_limit && (start < 0 || start > prefix_limit || start + width < 0 ||
        start + width > prefix_limit || (!cursor_move && width < 0))) exit(42);
}
"""
META = """
    fprintf(stderr, "PREFIX_META,%d,%d,%d,%d,%d,%d,%d,%d\\n",
            start_bit_pos, n, nt, hm_cfg != NULL, nbbits, resQMaxBits,
            st->BER_detect, st->bfi);
    exit(45);
"""


def replace(source, old, new):
    if source.count(old) != 1:
        raise ValueError("expected one reference source anchor: " + old)
    return source.replace(old, new)


def instrument(name, source):
    if name == "bitstream.c":
        # The diagnostic marker carries 128 actual symbols at the nominal
        # 13.2 kbit/s grammar. No residual symbols or arithmetic flush bytes are added.
        source = GUARD + source
        old = "total_brate = (long)(num_bits * 50);"
        source = replace(source,old,"if (utmp != 0x7777 || num_bits != 128) exit(43); "
                         "prefix_limit = 128; total_brate = 13200;")
        source = replace(source,"for (k=0; k<8*2; ++k)","for (k=0; !prefix_limit && k<8*2; ++k)")
        for function,(start,width,is_move) in ACCESSORS.items():
            pattern = rf"(\n(?:void|unsigned short) {function}\([^{{]*\)\s*\{{)"
            source,count = re.subn(pattern,rf"\1\n    guard_prefix({start}, {width}, {int(is_move)});",source)
            if count != 1:
                raise ValueError(f"missing decoder accessor: {function}")
    elif name == "io_dec.c":
        source = replace(source,"utmp != SYNC_GOOD_FRAME && utmp != SYNC_BAD_FRAME","utmp != 0x7777")
    elif name == "ACcontextMapping_dec.c":
        anchor = "    n = get_next_indice(st, n) + 1;"
        # Exit before reading any spectrum symbol. The Python caller reads the
        # tuple field and three arithmetic bits from its own prefix copy.
        source = replace(source,anchor,META+anchor)
    elif name == "decoder.c":
        anchor = "/* convert 'float' output data to 'short' */"
        source = replace(source,anchor,"exit(44); "+anchor)
    return source


def verify_first_model(src):
    """Recompute the one-pair decision from the pinned source's own tables."""
    tables = (src / "lib_com/rom_com.c").read_text()
    lookup = tables.split("ari_lookup_s17_LC[4096] =", 1)[1].split("};", 1)[0]
    first_model = int(re.search(r"0x[0-9a-fA-F]+", lookup)[0], 16)
    models = tables.split("ari_pk_s17_LC_ext[64][18] =", 1)[1].split("};", 1)[0]
    rows = [[int(v) for v in re.findall(r"\d+", row)]
            for row in re.findall(r"\{([^{}]+)\}", models)]
    if len(rows) != 64 or first_model != 1 or rows[first_model][:2] != [16384, 8983]:
        raise ValueError("unexpected arithmetic table for the first unmapped tuple")
    # floor(65536 * cum / 16384), inclusive range for symbol zero.
    low = 4 * rows[first_model][1]
    high = 4 * rows[first_model][0] - 1
    if any(not low <= value <= high for value in range(0b101 << 13, 0b110 << 13)):
        raise ValueError("the three-bit prefix does not establish the zero symbol")
    if not (low >= 32768 and high == 65535):
        raise ValueError("expected a single high-half renormalization")
    low = 2 * (low - 32768)
    high = 2 * (high - 32768) + 1
    if not (low < 16384 and high == 65535):
        raise ValueError("canonical two-bit encoder termination is not 01")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("codec_source",type=Path)
    p.add_argument("observer",type=Path)
    args = p.parse_args()
    src = args.codec_source.resolve()
    dirs = ["lib_com","lib_dec","lib_enc"]
    files = sorted(f for sub in dirs for f in (src/sub).iterdir()
                   if f.suffix == ".h" or (f.suffix == ".c" and sub != "lib_enc"))
    tree = sha256()
    for path in files:
        tree.update(path.relative_to(src).as_posix().encode("ascii")+b"\0"+sha256(path.read_bytes()).digest())
    if tree.hexdigest() != EXPECTED_SOURCE:
        raise ValueError("requires the original-byte TS 26.443 source tree, Nov 4 2021")
    verify_first_model(src)
    observer = args.observer.resolve()
    observer.parent.mkdir(parents=True,exist_ok=True)
    intercepted = {"bitstream.c","io_dec.c","ACcontextMapping_dec.c","decoder.c"}
    with tempfile.TemporaryDirectory() as td:
        inputs = []
        for path in files:
            if path.suffix != ".c":
                continue
            if path.name in intercepted:
                copy = Path(td)/path.name
                copy.write_text(instrument(path.name,path.read_text()))
                inputs.append(copy)
            else:
                inputs.append(path)
        subprocess.run(["gcc","-O2","-std=gnu99","-fno-strict-aliasing",
                        *[f"-I{src/sub}" for sub in dirs],*inputs,"-lm","-o",observer],check=True)
    print(observer,sha256(observer.read_bytes()).hexdigest())


if __name__ == "__main__":
    main()
