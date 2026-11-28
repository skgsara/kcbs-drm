"""Build the persistent EVS candidate decoder against the untouched EVS reference.

Compiles scripts/evs_candidate_decoder.c together with the UNMODIFIED 3GPP EVS
float reference sources (work/ref/evs/src/c-code lib_com/*.c and lib_dec/*.c,
leaving out lib_dec/decoder.c, whose main() the harness replaces) into
work/evs_candidate/evs_candidate_decoder.  Nothing from the reference tree is
copied into tracked files.  Objects are compiled in parallel; build.json records
the compiler, flags, SHA-256 of every source file and of the binary.

Exactness: the default flags (-O2 -fwrapv -ffp-contract=off -fno-strict-aliasing)
keep IEEE single-precision arithmetic identical to the project's -O0 EVS_dec on
x86-64; scripts/validate_evs_candidates.py checks byte-identical PCM.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

from build_evs_gcc_independent import linux, linux_command

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT/'work/ref/evs/src/c-code'
HARNESS = Path(__file__).resolve().parent/'evs_candidate_decoder.c'
DEFAULT_OUT = 'work/evs_candidate'
BINARY_NAME = 'evs_candidate_decoder'
FLAGS = ['-O2', '-std=gnu99', '-fno-strict-aliasing', '-fwrapv', '-ffp-contract=off']


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def reference_sources(src=SRC):
    """lib_com + lib_dec C files, without the reference decoder's main()."""
    files = sorted((src/'lib_com').glob('*.c'))
    files += [p for p in sorted((src/'lib_dec').glob('*.c')) if p.name != 'decoder.c']
    return files


def compile_one(source, obj, flags, includes):
    command = linux_command('gcc', *flags, *includes, '-c', source, '-o', obj)
    result = subprocess.run(command, capture_output=True, timeout=900)
    return source, result.returncode, result.stderr.decode(errors='replace')


def build(out, flags=FLAGS, jobs=None, src=SRC, harness=HARNESS):
    """Compile into `out` and return the build receipt (raises on failure)."""
    out = Path(out).resolve()
    objdir = out/'obj'
    if objdir.exists():
        shutil.rmtree(objdir)
    objdir.mkdir(parents=True)
    includes = ['-I' + linux(src/sub) for sub in ('lib_com', 'lib_dec', 'lib_enc')]
    sources = reference_sources(src) + [Path(harness)]
    jobs = jobs or os.cpu_count() or 1
    started = time.time()
    tasks = []
    with ThreadPoolExecutor(jobs) as pool:
        for i, source in enumerate(sources):
            obj = objdir/('%03d_%s.o' % (i, source.stem))
            tasks.append(pool.submit(compile_one, source, obj, flags, includes))
        results = [t.result() for t in tasks]
    log = []
    for source, code, err in results:
        if err.strip():
            log.append('== %s (rc %d)\n%s' % (source.name, code, err))
    (out/'build.log').write_text('\n'.join(log), encoding='utf-8')
    failed = [str(s) for s, code, _ in results if code]
    if failed:
        raise RuntimeError('compilation failed for %d file(s), first %s; see %s'
                           % (len(failed), failed[0], out/'build.log'))
    binary = out/BINARY_NAME
    objects = sorted(objdir.glob('*.o'))
    rsp = out/'link.rsp'
    rsp.write_text('\n'.join('"' + linux(o) + '"' for o in objects), encoding='utf-8')
    command = linux_command('gcc', *flags, '@' + linux(rsp), '-lm', '-o', binary)
    result = subprocess.run(command, capture_output=True, timeout=900)
    if result.returncode:
        raise RuntimeError('link failed: ' + result.stderr.decode(errors='replace')[-3000:])
    gcc = subprocess.run(linux_command('gcc', '--version'), capture_output=True, text=True)
    receipt = dict(
        tool='build_evs_candidate_decoder.py',
        binary=str(binary),
        sha256=sha256(binary),
        flags=flags,
        compiler=gcc.stdout.splitlines()[0] if gcc.stdout else None,
        reference_root=str(src),
        unmodified_sources=True,
        excluded=['lib_dec/decoder.c (reference main(), replaced by the harness)'],
        harness=dict(path=str(Path(harness).relative_to(ROOT)), sha256=sha256(harness)),
        source_files=len(sources) - 1,
        sources={str(p.relative_to(src)): sha256(p) for p in sources[:-1]},
        seconds=round(time.time() - started, 1),
    )
    receipt['reference_sha256'] = hashlib.sha256(
        json.dumps(receipt['sources'], sort_keys=True).encode()).hexdigest()
    (out/'build.json').write_text(json.dumps(receipt, indent=2), encoding='utf-8')
    shutil.rmtree(objdir)
    return receipt


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--out', default=DEFAULT_OUT, help='output directory (default %(default)s)')
    ap.add_argument('--jobs', type=int, default=None, help='parallel compiler processes')
    ap.add_argument('--flags', default=None,
                    help='override compiler flags (space separated); default: %s' % ' '.join(FLAGS))
    a = ap.parse_args()
    if not (SRC/'lib_dec/evs_dec.c').exists():
        raise SystemExit('EVS reference source not found under %s' % SRC)
    flags = a.flags.split() if a.flags else FLAGS
    receipt = build(ROOT/a.out, flags=flags, jobs=a.jobs)
    summary = {k: receipt[k] for k in ('binary', 'sha256', 'flags', 'compiler',
                                       'source_files', 'reference_sha256', 'seconds')}
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
