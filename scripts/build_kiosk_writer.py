"""Build the pinned protected Imager CLI and record every shipped dependency."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path, PurePosixPath

VERSION = "2.0.12"
COMMIT = "84b03d96cd4c390ebe475a4b5db5735e5535e9a6"
WINDOWS_PATCH = "20f707049a4736604aa3d8f63beb914ac3e58088984b6c1f209d10acc01f6008"
DEPENDENCIES = {
    "curl": "https://github.com/curl/curl.git",
    "libarchive": "https://github.com/libarchive/libarchive.git",
    "libusb": "https://github.com/libusb/libusb.git",
    "nghttp2": "https://github.com/nghttp2/nghttp2.git",
    "xz": "https://github.com/tukaani-project/xz.git",
    "zlib": "https://github.com/madler/zlib.git",
    "zstd": "https://github.com/facebook/zstd.git",
}


def run(args, **kwargs):
    return subprocess.run([str(arg) for arg in args], check=True, **kwargs)


def compiler_path(path):
    """Avoid MinGW windres splitting quoted include paths during preprocessing."""
    path = path.resolve()
    if os.name != "nt" or not any(character.isspace() for character in str(path)):
        return path
    import ctypes

    buffer = ctypes.create_unicode_buffer(32768)
    length = ctypes.windll.kernel32.GetShortPathNameW(str(path), buffer, len(buffer))
    if not 0 < length < len(buffer) or any(character.isspace() for character in buffer.value):
        raise ValueError("Use a writer build folder without spaces; this volume has no short path aliases")
    return Path(buffer.value)


def linux_libraries(executable, destination):
    pending = [executable]
    copied = set()
    system = re.compile(r"^(?:ld-linux.*|libc\.so.*|libm\.so.*|libpthread\.so.*|libdl\.so.*|librt\.so.*)$")
    library_folder = destination / "lib"
    library_folder.mkdir()
    while pending:
        original = pending.pop()
        listing = run(["ldd", original], capture_output=True, text=True).stdout
        if "not found" in listing:
            raise ValueError("An Imager dependency could not be resolved")
        for line in listing.splitlines():
            match = re.search(r"=> (/\S+) \(", line)
            if not match:
                continue
            path = Path(match[1])
            if path.name in copied or system.fullmatch(path.name):
                continue
            copied.add(path.name)
            target = library_folder / path.name
            shutil.copyfile(path, target)
            pending.append(path)
            run(["patchelf", "--set-rpath", "$ORIGIN", target])
    run(["patchelf", "--set-rpath", "$ORIGIN/lib", executable])


def windows_libraries(executable, qt, destination):
    # MinGW and Qt DLL imports are resolved recursively; Windows system DLLs stay external.
    pending, copied = [executable], set()
    compiler = Path(shutil.which("gcc.exe") or "").parent
    search = [qt / "bin", compiler]
    system = Path(os.environ["SYSTEMROOT"]) / "System32"
    while pending:
        path = pending.pop()
        listing = run(["objdump.exe", "-p", path], capture_output=True, text=True).stdout
        for name in re.findall(r"DLL Name:\s*(\S+)", listing):
            if name.lower() in copied:
                continue
            copied.add(name.lower())
            source = next((folder / name for folder in search if (folder / name).is_file()), None)
            if source:
                target = destination / name
                shutil.copyfile(source, target)
                pending.append(target)
            elif not (system / name).is_file() and not name.lower().startswith(("api-ms-win-", "ext-ms-win-")):
                raise ValueError(f"Missing writer dependency: {name}")


def export_source(archive, destination):
    links, total = [], 0
    for index, member in enumerate(archive):
        name = PurePosixPath(member.name)
        if (
            index >= 100000
            or len(member.name) > 1024
            or name.is_absolute()
            or ".." in name.parts
            or "\\" in member.name
            or ":" in member.name
        ):
            raise ValueError("Invalid pinned dependency archive path")
        target = destination / member.name
        if not target.resolve().is_relative_to(destination.resolve()) or target.is_symlink():
            raise ValueError("A dependency archive escapes its export folder")
        if member.isdir():
            target.mkdir(parents=True, exist_ok=True)
        elif member.issym():
            links.append((target, member.linkname))
        elif member.isfile():
            total += member.size
            if member.size < 0 or member.size > 64 * 1024**2 or total > 512 * 1024**2:
                raise ValueError("A dependency archive exceeds its source limits")
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.extractfile(member) as incoming, target.open("xb") as outgoing:
                shutil.copyfileobj(incoming, outgoing, 1024**2)
            target.chmod(0o755 if member.mode & 0o111 else 0o644)
        else:
            raise ValueError("Unsupported dependency archive entry")
    for target, link in links:
        selected = (target.parent / link).resolve(strict=True)
        if not selected.is_relative_to(destination.resolve()) or not selected.is_file():
            raise ValueError("A dependency link escapes its source tree")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(selected, target)


def compile_source(source, binary, qt, work):
    links = run(["git", "-C", source, "ls-tree", "HEAD:src/dependencies/vendor"], capture_output=True, text=True).stdout
    commits = {line.split("\t")[1]: line.split()[2] for line in links.splitlines() if line.startswith("160000 commit ")}
    if set(commits) != set(DEPENDENCIES):
        raise ValueError("Unexpected pinned writer dependencies")
    notices = {}
    with tempfile.TemporaryDirectory(prefix="writer-dependencies-", dir=work) as temporary:
        stage = Path(temporary)
        options = []
        for name, url in DEPENDENCIES.items():
            cache = work / "dependency-git" / name
            if not cache.exists():
                cache.parent.mkdir(parents=True, exist_ok=True)
                run(["git", "init", "--bare", cache])
            run(["git", "-C", cache, "fetch", "--depth", "1", "--no-tags", url, commits[name]])
            if (
                run(["git", "-C", cache, "rev-parse", "FETCH_HEAD"], capture_output=True, text=True).stdout.strip()
                != commits[name]
            ):
                raise ValueError("A writer dependency changed identity")
            destination = stage / name
            destination.mkdir()
            export = subprocess.Popen(
                ["git", "-C", str(cache), "archive", "--format=tar", commits[name]], stdout=subprocess.PIPE
            )
            try:
                with tarfile.open(fileobj=export.stdout, mode="r|") as archive:
                    export_source(archive, destination)
                if export.wait(timeout=60):
                    raise ValueError("A pinned dependency could not be exported")
            finally:
                if export.poll() is None:
                    export.kill()
                    export.wait(timeout=5)
                export.stdout.close()
            for path in destination.rglob("*"):
                if (
                    path.is_file()
                    and path.name.lower().startswith(("license", "copying", "copyright", "notice"))
                    and path.stat().st_size < 1024**2
                ):
                    relative = path.relative_to(destination).as_posix().replace("/", "_")
                    if len(relative) <= 160:
                        notices[name + "_" + relative] = path.read_bytes()
            options.append("-DFETCHCONTENT_SOURCE_DIR_" + name.upper() + "=" + str(destination))
        if os.name == "nt":
            binary.mkdir(parents=True, exist_ok=True)
            # The resource uses Windows headers, the application icon and its generated
            # manifest. Passing every C++ dependency include triggers windres's broken
            # preprocessor quoting. These two short paths cover the actual resources.
            resource = "<CMAKE_RC_COMPILER> -O coff <DEFINES> <FLAGS>"
            resource += " -I" + str(compiler_path(source / "src")).replace("\\", "/")
            resource += " -I" + str(compiler_path(binary)).replace("\\", "/")
            rules = work / "resource-rules.cmake"
            rules.write_text(
                "set(CMAKE_RC_COMPILE_OBJECT [=[" + resource + " <SOURCE> <OBJECT>]=])\n", encoding="utf-8"
            )
            options.append("-DCMAKE_USER_MAKE_RULES_OVERRIDE=" + str(rules))
        run(
            [
                "cmake",
                "-S",
                source / "src",
                "-B",
                binary,
                "-G",
                "Ninja",
                "-DCMAKE_BUILD_TYPE=Release",
                "-DCMAKE_PREFIX_PATH=" + str(qt),
                "-DBUILD_CLI_ONLY=ON",
                "-DENABLE_TELEMETRY=OFF",
                "-DENABLE_CHECK_VERSION=OFF",
                "-DENABLE_TEST_HOOKS=OFF",
                "-DBUILD_TESTING=OFF",
                "-DGENERATE_TIMEZONES_FROM_IANA=OFF",
                "-DGENERATE_COUNTRIES_FROM_REGDB=OFF",
                *options,
            ]
        )
        run(["cmake", "--build", binary, "--target", "rpi-imager", "--parallel", "2"])
    return commits, notices


def build(work, qt, output):
    work.mkdir(parents=True, exist_ok=True)
    work, qt = compiler_path(work), compiler_path(qt)
    source, binary = work / "source", work / "build"
    if not source.exists():
        run(
            [
                "git",
                "clone",
                "--depth",
                "1",
                "--branch",
                "v" + VERSION,
                "https://github.com/raspberrypi/rpi-imager.git",
                source,
            ]
        )
    actual = run(["git", "-C", source, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    dirty = run(["git", "-C", source, "status", "--porcelain"], capture_output=True, text=True).stdout
    if actual != COMMIT:
        raise ValueError("The writer source does not match the reviewed immutable commit")
    patches = {}
    if os.name == "nt":
        patch = Path(__file__).resolve().parents[1] / "assets/packaging/kiosk/imager-cli-windows.patch"
        expected = patch.read_text(encoding="utf-8").replace("\r\n", "\n")
        if hashlib.sha256(expected.encode()).hexdigest() != WINDOWS_PATCH:
            raise ValueError("The Windows CLI patch does not match its reviewed checksum")
        if dirty:
            actual_diff = run(["git", "-C", source, "diff", "--binary"], capture_output=True, text=True).stdout
            untracked = run(
                ["git", "-C", source, "ls-files", "--others", "--exclude-standard"], capture_output=True, text=True
            ).stdout
            if actual_diff != expected or untracked:
                raise ValueError("The writer source has changes beyond the reviewed Windows CLI patch")
        else:
            run(["git", "-C", source, "apply", "--check", patch])
            run(["git", "-C", source, "apply", patch])
        patches[patch.name] = WINDOWS_PATCH
    elif dirty:
        raise ValueError("The writer source contains unreviewed changes")
    commits, dependency_notices = compile_source(source, binary, qt, work)
    output.mkdir(parents=True, exist_ok=False)
    suffix = ".exe" if os.name == "nt" else ""
    executable = output / ("rpi-imager" + suffix)
    shutil.copyfile(binary / ("rpi-imager-cli" + suffix), executable)
    executable.chmod(0o755)
    if os.name == "nt":
        windows_libraries(executable, qt, output)
    else:
        linux_libraries(executable, output)
    if os.name == "nt":
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from kioskdesktop.native_version import windows_version

        if windows_version(executable)[:3] != (2, 0, 12):
            raise ValueError("The writer's Windows version resource does not match its pinned version")
    else:
        reported = run([executable, "--version"], capture_output=True, text=True)
        if not re.search(r"^Raspberry Pi Imager v?2\.0\.12\r?$", reported.stdout + reported.stderr, re.MULTILINE):
            raise ValueError(
                "The built writer did not report its pinned version: " + repr((reported.stdout + reported.stderr)[:300])
            )
    notices = output / "notices"
    notices.mkdir()
    if os.name == "nt":
        licenses = Path(shutil.which("gcc.exe")).parent.parent / "licenses"
        if not (licenses / "gcc/COPYING.RUNTIME").is_file():
            raise ValueError("The MinGW runtime redistribution licenses are missing")
        for path in licenses.rglob("*"):
            if path.is_file():
                name = "mingw_" + path.relative_to(licenses).as_posix().replace("/", "_")
                shutil.copyfile(path, notices / name)
    for relative, data in dependency_notices.items():
        (notices / ("vendor_" + relative)).write_bytes(data)
    if os.name == "nt":
        (notices / "imager-cli-windows.patch").write_text(expected, encoding="utf-8", newline="\n")
    for base, prefix in ((source, "imager"), (qt, "qt")):
        for path in base.rglob("*"):
            if path.is_file() and path.name.lower().startswith(("license", "copying", "copyright", "notice")):
                relative = path.relative_to(base).as_posix().replace("/", "_")
                if len(relative) <= 160 and path.stat().st_size < 1024**2:
                    shutil.copyfile(path, notices / (prefix + "_" + relative))
    (notices / "SOURCES.txt").write_text(
        f"Raspberry Pi Imager {VERSION}\nhttps://github.com/raspberrypi/rpi-imager/tree/{COMMIT}\n"
        "Qt 6.9.3 (shared libraries)\nhttps://download.qt.io/archive/qt/6.9/6.9.3/single/\n"
        "Rebuild instructions: scripts/build_kiosk_writer.py and assets/packaging/kiosk/Dockerfile.writer\n",
        encoding="utf-8",
    )
    files = {
        path.relative_to(output).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(output.rglob("*"))
        if path.is_file()
    }
    if len(files) > 512 or sum(path.stat().st_size for path in output.rglob("*") if path.is_file()) > 256 * 1024**2:
        raise ValueError("The writer payload exceeds the worker's packaging limits")
    (output / "writer-manifest.json").write_text(
        json.dumps(
            {
                "format": 1,
                "version": VERSION,
                "commit": COMMIT,
                "telemetry": False,
                "cli_only": True,
                "patches": patches,
                "dependencies": commits,
                "sha256": files,
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--qt", type=Path, required=True)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    build(args.work.resolve(), args.qt.resolve(), args.output.resolve())


if __name__ == "__main__":
    main()
