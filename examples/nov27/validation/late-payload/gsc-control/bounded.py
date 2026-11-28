"""Build a guarded PVQ allocation observer around a pristine TS 26.443 source tree."""

import hashlib
import subprocess


def once(text, old, new):
    if text.count(old) != 1:
        raise ValueError(f"Unexpected stock source anchor {old!r}")
    return text.replace(old, new)


HEADER = '''
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <setjmp.h>
extern long frame;
extern int walking;
extern unsigned read_max;
extern unsigned int upper_low;
extern jmp_buf stop_walk;
void before_read(int pos,int count);
void walk_prefix(Decoder_State *st,short budget,short nb,short *R);
'''
CBODY=r'''
#include <assert.h>
#include <string.h>
#include "prot.h"
HEADER
int walking;
unsigned read_max;
unsigned int upper_low;
jmp_buf stop_walk;
void before_read(int pos, int count) {
    static long last = -1;
    if (last != frame) {
        last = frame;
        read_max = 0;
    }
    if (walking) {
        if (pos < 0 || pos + count > 128) longjmp(stop_walk, 1);
        return;
    }
    if ((unsigned)(pos + count) > read_max) read_max = pos + count;
}
/* Only the first 128 actual bits are copied. Stock range and allocation
 * routines initialize the other arithmetic members. The pulse vector and
 * quantized coefficients play no role in future pulse allocations. */
void walk_prefix(Decoder_State *st, short budget, short nb, short *R) {
    if (read_max > 128) return;
    static Decoder_State scratch;
    memset(&scratch,0,sizeof(scratch));
    memcpy(scratch.bit_stream,st->bit_stream,128*sizeof(st->bit_stream[0]));
    scratch.next_bit_pos=st->next_bit_pos;
    scratch.total_brate=st->total_brate;
    short alloc[NB_SFM_MAX]={0}, pulses[NB_SFM_MAX]={0}, maxpulse[NB_SFM_MAX]={0};
    float out[L_FRAME48k];
    memcpy(alloc,R,nb*sizeof(*R));
    walking=1;
    upper_low=0;
    fprintf(stderr,"P,%ld,%u,%d\n",frame,read_max,st->next_bit_pos);
    if (!setjmp(stop_walk)) {
        pvq_core_dec(&scratch,gsc_sfm_start,gsc_sfm_end,gsc_sfm_size,out,budget,nb,alloc,NULL,pulses,maxpulse,ACELP_CORE);
    }
    walking=0;
}
'''
READ=r'''
    if (walking) {
        short width=bits<8?bits:8;
        unsigned int lo=0,hi=0;
        for(int i=0;i<width;i++){
            int p=st->next_bit_pos+i;
            lo <<= 1;
            hi <<= 1;
            if (p < 128) {
                unsigned int value=get_indice_1(st,p);
                lo += value;
                hi += value;
            } else {
                hi++;
            }
        }
        st->next_bit_pos+=width;
        assert(upper_low<(1u<<24));
        upper_low=(upper_low<<8)+(hi<<(8-width));
        return lo<<(8-width);
    }'''
INDEX=r'''
        if (walking) {
            unsigned int high=value;
            st->rc_offset -= n;
            st->rc_num_bits += n;
            fprintf(stderr,"N,%ld,%u,%u,%d,%d\n",frame,tot,high,n,st->rc_offset);
            return 0; /* consumer of this scalar is disabled in the allocation walk */
        }
'''

PINS = {'lib_com/bitstream.c': '801448e98e002c31cd6c9a626b73e4eb6e0b9bf929875725ae53a7b90200a6cc',
 'lib_com/gs_bitallocation.c': '6eade62da494891381cc77f9d71498473c369b99c894244f8ff158fb50195a9b',
 'lib_dec/gs_dec.c': '892fdd76211f27220ff4684f251f3326b40eaa18f78034626b44c63303ecc29c',
 'lib_dec/pvq_core_dec.c': '67f17f4346671af8c6110bbe3abf658d71e602fc38405b064491b0a9d1d0fd7b',
 'lib_dec/pvq_decode.c': 'a4890f1f1062688c7dfe49a6f43406dba878391f5acaa22b82cc4d2188d850b9',
 'lib_dec/range_dec.c': '5a004f5147ad5c5d3f6f268956b5b16a6447e5277e499fab51efa456dd0e3677',
 'lib_enc/pvq_encode.c': 'f9dc607a634b688353eb6902a2cf87d6419c6ac4616d5b2ddd6cc4ff283486fd',
 'lib_enc/range_enc.c': 'b82a4cf45976dbb83150e8c017cfed6ceaaed68653b0296248011e4d884e5062'}


def patch_bit_readers(text):
    # The value accessors cover sequential and absolute reads at either width.
    for address in ("st->next_bit_pos", "pos"):
        loop = (
            "    value = 0;\n    for (i = 0; i < nb_bits; i++)\n"
            "    {\n        value <<= 1;\n"
            f"        value += st->bit_stream[{address}+i];"
        )
        text = once(text, loop, f"    before_read({address}, nb_bits);\n" + loop)
        expression = "st->next_bit_pos++" if address == "st->next_bit_pos" else "pos"
        result = f"    return st->bit_stream[{expression}];"
        text = once(text, result, f"    before_read({address}, 1);\n" + result)
    return text


def patch_gsc(text):
    call, = [line for line in text.splitlines() if "pvq_core_dec( st, gsc_sfm_start," in line]
    return once(text, call, "        walk_prefix(st, bit, nb_subbands, bits_per_bands);\n" + call)


def patch_vector(text):
    # Observe the actual stock validity branch for separate single-word controls.
    condition = "entry.size == 142544 && st->rc_offset == 230 && getenv(\"GSC_CONTROL_CHECK\")"
    check = "        if( entry.index >= entry.size || st->ber_occured_in_pvq != 0 )"
    text = once(text, check, f"""
        if ({condition})
            fprintf(stderr, "I,%u,%u,%d\\n", entry.size, entry.index, st->ber_occured_in_pvq);
""" + check)
    fallback = "            st->ber_occured_in_pvq = 1;"
    text = once(text, fallback, f"""
            if ({condition})
                fprintf(stderr, "F,%u\\n", entry.index);
""" + fallback)
    size, = [line for line in text.splitlines() if "entry = get_size_mpvq_calc_offset" in line]
    return once(text, size, size + """
    if (walking) {
        st->rc_offset--;
        st->rc_num_bits++;  /* A leading sign costs one bit. */
        if (dim != 1) (void)rc_dec_uniform(st, entry.size);
        return;
    }""")


def patch_core(text):
    finish = "    if( Rs != NULL )"
    return once(text, finish, "    if (walking) return bits_tot;\n" + finish)


def patch_range(text):
    read = "    bits = st->rc_end - st->next_bit_pos;"
    text = once(text, read, read + READ)
    decode = "    val = st->rc_low/st->rc_help;"
    text = once(text, decode, decode + """
    if (walking) {
        unsigned int highfreq = upper_low / st->rc_help;
        if (val != highfreq || val >= tot) longjmp(stop_walk, 1);
        return val;
    }""")
    update = "    st->rc_low = st->rc_low - cum_freq*st->rc_help;"
    text = once(text, update, update + """
    if (walking) {
        assert(upper_low >= cum_freq * st->rc_help);
        upper_low -= cum_freq * st->rc_help;
        assert(upper_low < sym_freq * st->rc_help && st->rc_low <= upper_low);
    }""")
    raw = "        value <<= n;"
    return once(text, raw, INDEX + raw)


def build(work, source_root):
    for name, expected in PINS.items():
        if hashlib.sha256((source_root / name).read_bytes()).hexdigest() != expected:
            raise ValueError(f"TS 26.443 source hash differs for {name}")
    patches = {
        "lib_com/bitstream.c": patch_bit_readers,
        "lib_dec/gs_dec.c": patch_gsc,
        "lib_dec/pvq_decode.c": patch_vector,
        "lib_dec/pvq_core_dec.c": patch_core,
        "lib_dec/range_dec.c": patch_range,
    }
    modified = {}
    for name, apply in patches.items():
        original = source_root / name
        text = original.read_text()
        if name == "lib_com/bitstream.c":
            header = '#include "options.h"'
            text = once(text, header, header + "\nextern void before_read(int, int);")
        else:
            header = '#include "prot.h"'
            text = once(text, header, header + HEADER)
        edited = work / original.name
        edited.write_text(apply(text))
        modified[original] = edited
    hook = work / "hook.c"
    hook.write_text('#include "rom_com.h"\n' + CBODY.replace("HEADER", HEADER))
    sources = []
    for folder in ("lib_com", "lib_dec"):
        for original in sorted((source_root / folder).glob("*.c")):
            sources.append(modified.get(original, original))
    binary = work / "native"
    includes = ["-I" + str(source_root / name) for name in ("lib_com", "lib_dec", "lib_enc")]
    subprocess.run(
        ["gcc", "-O2", "-std=gnu99", "-fno-strict-aliasing", *includes, *sources, hook, "-lm", "-o", binary],
        check=True,
    )
    return binary
