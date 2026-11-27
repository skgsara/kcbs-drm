"""Count SWB-TBE LSF range-check rejections with the floating-point TS 26.443 reference.

Pass --source /path/to/c-code from ETSI TS 126 443 V19.0.0 and a C99 compiler
on PATH. --contexts includes all 8192 counts. --projection accepts one JSON
group from scripts/project_evs_group.py. Only word octets 0, 30, 32 are used.
"""
import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import re
import subprocess
import tempfile


SOURCE_HASHES = {
    "lib_com/cnst.h": "d1dcb84298c78e85c41df0ee4d549a00af615516c132c2cc066c57a6671b5caa",
    "lib_com/rom_com.c": "fa30b288027e5172242c1fff5a743383bcdb544e4571ef3815352db54a0b27e5",
    "lib_dec/swb_tbe_dec.c": "849ec1dd824c6b04422df5e66215cc54807289c742016b9c8507c22dda7bdaba",
}

# Within each 21-bit tuple, bits [243,248) and [256,264) identify the context.
# The middle eight bits [248,256) enumerate an artificial word octet 31.
PROBE = r"""
int main(void)
{
    unsigned rejects[8192] = {0};
    for (unsigned value = 0; value < (1u << 21); ++value) {
        short idx[5] = {(value >> 17) & 15, (value >> 13) & 15, (value >> 10) & 7,
                        (value >> 7) & 7, (value >> 4) & 7};
        float lsf[LPC_SHB_ORDER], mirror;
        Dequant_lower_LSF(idx, lsf);
        Dequant_mirror_point(lsf, (value >> 2) & 3, &mirror);
        int rejected = mirror > MAX_LSF;
        if (rejected) mirror = MAX_LSF;
        Map_higher_LSF(lsf, mirror, lsf_grid[value & 3]);
        for (unsigned i = 0; i < LPC_SHB_ORDER; ++i)
            if (lsf[i] > MAX_LSF) rejected = 1;
        unsigned context = ((value >> 16) << 8) | (value & 255);
        rejects[context] += rejected;
    }
    for (unsigned i = 0; i < 8192; ++i) printf("%u\n", rejects[i]);
    return ferror(stdout) != 0;
}
"""


def checked_source(root, name):
    data = (root / name).read_bytes().replace(b"\r\n", b"\n")
    if sha256(data).hexdigest() != SOURCE_HASHES[name]:
        raise ValueError(f"{name} differs from the pinned TS 26.443 floating-point source")
    return data.decode("utf-8")


def static_function(source, name):
    match = re.search(r"static void " + name + r"\s*\([^;{]+\)\s*\{", source)
    if match is None:
        raise ValueError(f"missing reference function {name}")
    return source[match.start():source.index("\n}", match.end()) + 2]


def context_counts(root):
    constants = checked_source(root, "lib_com/cnst.h")
    tables = checked_source(root, "lib_com/rom_com.c")
    decoder = checked_source(root, "lib_dec/swb_tbe_dec.c")
    # Extract only the five numeric definitions needed by the pinned tables and helpers.
    names = ("LPC_SHB_ORDER", "NUM_Q_LSF", "NUM_MAP_LSF", "MIRROR_POINT_Q_CB_SIZE", "MAX_LSF")
    definitions = re.findall(r"^#define (?:" + "|".join(names) + r")\s+\S+", constants, re.MULTILINE)
    body = tables[tables.index("const float lsf_q_cb_4b[16]"):tables.index("const float allpass_poles_3_ov_2")]
    functions = [static_function(decoder, name) for name in ("Dequant_lower_LSF", "Dequant_mirror_point", "Map_higher_LSF")]
    with tempfile.TemporaryDirectory() as directory:
        source = Path(directory) / "probe.c"
        executable = source.with_suffix("")
        source.write_text("\n".join(["#include <stdio.h>", *definitions, body, *functions, PROBE]), encoding="utf-8")
        subprocess.run(["cc", "-std=c99", "-O2", "-ffp-contract=off", str(source), "-o", str(executable)], check=True)
        output = subprocess.check_output([str(executable)], text=True)
    counts = [int(value) for value in output.splitlines()]
    if len(counts) != 8192 or any(count < 0 or count > 256 for count in counts):
        raise ValueError("unexpected count from the reference probe")
    return counts


def octet(token):
    if token in ("??", "--"):
        return None
    if not re.fullmatch("[0-9a-fA-F]{2}", token):
        raise ValueError("invalid projected octet")
    return int(token, 16)


def project(document, counts):
    counter = document["counter"]
    phases = document["received_du_phases"]
    if (document["format"] != "kcbs-evs-projection-v1" or type(counter) is not int
            or not 0 <= counter <= 0xffffffff or len(document["slots"]) != 60
            or not isinstance(phases, list) or any(type(p) is not int or p not in range(3) for p in phases)
            or phases != sorted(set(phases))):
        raise ValueError("expected one public 60-slot projection with valid counter and phase coordinates")
    slots = []
    statuses = Counter()
    for index, row in enumerate(document["slots"]):
        phase, local = divmod(index, 20)
        cycle, role = divmod(local, 4)
        keys = ("counter", "slot", "phase", "cycle", "position")
        coords = tuple(row[k] for k in keys)
        if any(type(n) is not int for n in coords) or coords != (counter, index, phase, cycle, role + 1):
            raise ValueError(f"invalid coordinates at slot {index}")
        received = phase in phases
        if row["receipt"] != ("received_du" if received else "missing_du"):
            raise ValueError(f"inconsistent phase receipt at slot {index}")
        entry = dict(zip(keys, coords))
        status = "missing_du"
        if received:
            tokens = row["octets"].split()
            if len(tokens) != 33:
                raise ValueError(f"expected 33 octet tokens at slot {index}")
            mode = octet(tokens[0])
            if mode is None:
                status = "mode_unavailable"
            elif mode >> 3 not in (10, 11, 19, 20) or mode & 4:
                status = "outside_mode"
            else:
                left, right = octet(tokens[30]), octet(tokens[32])
                if left is None or right is None:
                    status = "context_unavailable"
                else:
                    status = "evaluated"
                    rejected = counts[((left & 31) << 8) | right]
                    entry.update(rejected_values=rejected, remaining_values=256 - rejected)
        entry["status"] = status
        slots.append(entry)
        statuses[status] += 1
    return dict(counter=counter, status_counts=dict(statuses), slots=slots)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True, help="TS 26.443 floating-point c-code directory")
    parser.add_argument("--contexts", action="store_true", help="include all counts in context index order")
    parser.add_argument("--projection", type=Path, help="optional JSON from project_evs_group.py")
    args = parser.parse_args()
    try:
        counts = context_counts(args.source)
        result = dict(reference="ETSI TS 126 443 V19.0.0, floating point", source_sha256_lf=SOURCE_HASHES,
                      word_bit_range=[248, 256], context_index="((word[30] & 31) << 8) | word[32]",
                      total_contexts=len(counts), values_per_context=256, total_rejected=sum(counts),
                      contexts_by_rejected_values=dict(sorted(Counter(counts).items())),
                      scope="Counts test two LSF range guards in the ordinary 13.2 kb/s SWB GENERIC/VOICED TBE layout. "
                            "Passing both guards leaves the clear octet unverified.")
        if args.contexts:
            result["rejections_by_context_index"] = counts
        if args.projection:
            result["projection"] = project(json.loads(args.projection.read_bytes()), counts)
    except (OSError, ValueError, TypeError, KeyError, subprocess.CalledProcessError) as error:
        parser.exit(2, f"{parser.prog}: {error}\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
