"""Build untouched EVS reference C with GCC, outside the source tree."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess


def linux(path):
    """Return a path suitable for the Linux compiler or decoder."""
    path = Path(path).resolve()
    if os.name != 'nt':
        return str(path)
    return '/mnt/' + path.drive[0].lower() + path.as_posix()[2:]


def linux_command(*args):
    """Run a Linux tool directly on POSIX, or in Ubuntu WSL on Windows."""
    prefix = ['wsl', '-d', 'Ubuntu', '--'] if os.name == 'nt' else []
    return prefix + [linux(x) if isinstance(x, Path) else str(x) for x in args]


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out',required=True)
    a=ap.parse_args()
    root=Path(__file__).resolve().parents[1]
    src=root/'work/ref/evs/src/c-code'
    out=(root/a.out).resolve(); out.mkdir(parents=True,exist_ok=False)
    report=[]
    for mode in ('dec','enc'):
        files=sorted((src/'lib_com').glob('*.c'))+sorted((src/('lib_'+mode)).glob('*.c'))
        binary=out/('EVS_dec' if mode=='dec' else 'EVS_cod')
        arguments=['-O0','-std=gnu99','-fno-strict-aliasing']
        arguments += ['-I'+linux(src/sub) for sub in ('lib_com','lib_dec','lib_enc')]
        arguments += [linux(p) for p in files]+['-lm','-o',linux(binary)]
        rsp=out/(mode+'.rsp')
        rsp.write_text('\n'.join('"'+s.replace('"','\\"')+'"' for s in arguments),encoding='utf-8')
        command=linux_command('gcc', '@'+linux(rsp))
        result=subprocess.run(command,capture_output=True,timeout=600)
        (out/(mode+'.log')).write_bytes(result.stdout+b'\n'+result.stderr)
        row=dict(mode=mode,source_files=len(files),command=command,returncode=result.returncode,
                 binary=str(binary),unmodified_sources=True)
        if result.returncode:
            print(result.stderr.decode(errors='replace')[-4000:])
            raise SystemExit(result.returncode)
        row['sha256']=hashlib.sha256(binary.read_bytes()).hexdigest()
        report.append(row)
        print(json.dumps(row),flush=True)
    (out/'build.json').write_text(json.dumps(report,indent=2),encoding='utf-8')


if __name__=='__main__':
    main()
