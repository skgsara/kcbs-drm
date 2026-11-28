"""Build the offline IQ file generator using an existing Dream qmake console build."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import tempfile

HERE = Path(__file__).resolve().parent
MODULE_SOURCES = (
    "DrmTransmitter.cpp", "OFDM.cpp", "mlc/MLC.cpp", "interleaver/SymbolInterleaver.cpp",
    "ofdmcellmapping/OFDMCellMapping.cpp", "FAC/FAC.cpp", "SDC/SDCTransmit.cpp", "DataIO.cpp", "Parameter.cpp",
)
# Use the exact compiler flags, libraries and object list of the given Dream build.
# Both an in-tree qmake build and a shadow build can choose their own OBJECTS_DIR.
RECIPE = """include Makefile
.PHONY: file_only_control
file_only_control:
	$(CXX) $(CXXFLAGS) $(INCPATH) -I"$(DREAM_SOURCE)" -std=c++17 -c "$(HARNESS)" -o "$(HARNESS_OBJECT)"
	$(LINK) $(LFLAGS) -o "$(BINARY)" "$(HARNESS_OBJECT)" $(filter-out main.o %/main.o,$(OBJECTS)) $(LIBS)
	@printf '%s\\n' $(filter-out main.o %/main.o,$(OBJECTS)) > "$(OBJECT_LIST)"
"""


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def source_directory(build, override):
    if override:
        candidates = [override.resolve()]
    else:
        candidates = [build, build / "src/dream"]
        for line in (build / "Makefile").read_text().splitlines():
            if line.startswith("# Project:"):
                project = Path(line.split(":", 1)[1].strip())
                candidates.append((build / project).resolve().parent)
                break
    for source in candidates:
        if (source / "src/DrmTransmitter.h").is_file():
            return source
    raise ValueError("provide the Dream source directory with --dream-source")


def build_generator(build, source_override, destination):
    source = source_directory(build, source_override)
    harness = HERE / "msc_to_iq.cpp"
    destination.mkdir(parents=True, exist_ok=True)
    binary = destination / "msc_to_iq"
    receipt = destination / "build.json"
    if binary.exists() or receipt.exists():
        raise ValueError("choose an output directory without an existing generator or build receipt")
    with tempfile.TemporaryDirectory(dir=destination) as temporary:
        stage = Path(temporary)
        extra_makefile = stage / "harness.mk"
        extra_makefile.write_text(RECIPE, encoding="utf-8")
        obj_list = stage / "objects.txt"
        executable = stage / "msc_to_iq"
        command = ["make", "--no-print-directory", "-f", str(extra_makefile), "file_only_control",
                   f"DREAM_SOURCE={source}", f"HARNESS={harness}", f"HARNESS_OBJECT={stage / 'harness.o'}",
                   f"BINARY={executable}", f"OBJECT_LIST={obj_list}"]
        with (destination / "build.log").open("wb") as log:
            subprocess.run(command, cwd=build, stdout=log, stderr=subprocess.STDOUT, check=True)
        objects = {name: digest(build / name) for name in obj_list.read_text().splitlines()}
        if not objects or any(Path(name).name == "main.o" for name in objects):
            raise ValueError("unexpected objects in the file generator link")
        git = subprocess.run(["git", "-C", str(source), "rev-parse", "HEAD"], capture_output=True, text=True)
        result = dict(harness_sha256=digest(harness), makefile_sha256=digest(build / "Makefile"),
                      binary_sha256=digest(executable), dream_source_path=str(source),
                      dream_revision=git.stdout.strip() if git.returncode == 0 else None,
                      dream_module_sources={s: digest(source / "src" / s) for s in MODULE_SOURCES},
                      linked_objects=objects)
        (stage / "build.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        executable.replace(binary)
        (stage / "build.json").replace(receipt)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dream-build", type=Path, required=True, help="completed qmake console build containing Makefile")
    parser.add_argument("--dream-source", type=Path, help="source tree for a custom shadow build")
    parser.add_argument("--out", type=Path, required=True, help="destination for msc_to_iq, build.log and build.json")
    args = parser.parse_args()
    try:
        result = build_generator(args.dream_build.resolve(), args.dream_source, args.out.resolve())
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f"{parser.prog}: {exc}\n")
    print(f"{args.out / 'msc_to_iq'}  sha256 {result['binary_sha256']}")


if __name__ == "__main__":
    main()
