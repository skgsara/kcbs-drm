"""Build temporary TS 26.443 observers for the previous-band pulse check."""
from hashlib import sha256
import subprocess


SOURCE_HASHES = {
    "lib_com/bitstream.c": "801448e98e002c31cd6c9a626b73e4eb6e0b9bf929875725ae53a7b90200a6cc",
    "lib_enc/hq_lr_enc.c": "d52cd45cda59c41e9ec0f14e6d3cb5a2dfc4b8024589d9bae6bee0fe7266bafa",
    "lib_dec/hq_lr_dec.c": "1bd289bf0d8cc9143207c4de04fb2561ce848a3c9661306b18371dc4d8f1bd35",
}
PULSE_LOG = r'''
    {
        extern long frame;
        fprintf(stderr,"PULSE,%ld,%d,%d,%d,%d\n",frame,inner_frame,TRANSIENT,
                npulses[bands-2],npulses[bands-1]);
    }
'''
WRITE_LOG = r'''
            if (nb_bits>0 && i>=IND_HQ2_LAST_BA_MAX_BAND && i<IND_RC_START && st->core==HQ_CORE) {
                extern long frame;
                fprintf(stderr,"WRITE,%ld,%ld,%d,%u\n",frame,(long)(pt_stream-stream-2),
                        (int)nb_bits,(unsigned short)value);
            }
'''
READ_LOG = r'''
        if (i==1) {
            extern long frame;
            fprintf(stderr,"READ,%ld,%d,%d,%d\n",frame,st->next_bit_pos-2,
                    last_bitalloc_max_band[0],last_bitalloc_max_band[1]);
        }
'''


def insert(text, anchor, addition, *, after, count=1):
    if text.count(anchor) != count:
        raise ValueError(f"Unexpected number of reference source anchors for {anchor!r}")
    return text.replace(anchor, anchor + addition if after else addition + anchor)


def build_observers(source, tmp):
    for rel, digest in SOURCE_HASHES.items():
        if sha256((source / rel).read_bytes()).hexdigest() != digest:
            raise ValueError(f"Unsupported stock source revision for {rel}")

    binaries = []
    for side in ("enc", "dec"):
        work = tmp / side
        work.mkdir()
        hq = source / f"lib_{side}/hq_lr_{side}.c"
        text = hq.read_text(encoding="latin1")
        if side == "enc":
            text = insert(text, "if((inner_frame == L_FRAME8k && st->core_brate <= ACELP_13k20) || inner_frame == L_FRAME16k)",
                          PULSE_LOG.replace("TRANSIENT", "is_transient"), after=False)
            bitstream = source / "lib_com/bitstream.c"
            writer = insert(bitstream.read_text(encoding="latin1"), "nb_bits = st->ind_list[i].nb_bits;",
                            WRITE_LOG, after=True)
            (work / bitstream.name).write_text(writer, encoding="latin1")
        else:
            text = insert(text, "p2a_flags, p2a_bands, last_bitalloc_max_band, inner_frame, adjustFlag, is_transient );",
                          PULSE_LOG.replace("TRANSIENT", "*is_transient"), after=True)
            text = insert(text, "last_bitalloc_max_band[i] = (short)get_next_indice( st, 1 );",
                          READ_LOG, after=True, count=2)
        (work / hq.name).write_text(text, encoding="latin1")

        files = sorted((source / "lib_com").glob("*.c")) + sorted((source / f"lib_{side}").glob("*.c"))
        inputs = [work / p.name if (work / p.name).exists() else p for p in files]
        binary = work / f"EVS_{side}"
        subprocess.run(["gcc", "-O0", "-std=gnu99", "-fno-strict-aliasing",
                        *["-I" + str(source / d) for d in ("lib_com", "lib_enc", "lib_dec")],
                        *inputs, "-lm", "-o", binary], check=True)
        binaries.append(binary)
    return binaries
