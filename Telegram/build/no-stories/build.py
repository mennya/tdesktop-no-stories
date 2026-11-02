import argparse
import json
import ntpath
from pathlib import Path, PurePosixPath, PureWindowsPath
import posixpath
import re
import subprocess


PERSONAL_AVATAR_SOURCES = (
    "Telegram/SourceFiles/ui/userpic_view.cpp",
    "Telegram/SourceFiles/ui/peer/userpic_policy.cpp",
)


def compiler_output(entry):
    if output := entry.get("output"):
        return output
    arguments = entry.get("arguments", [])
    for index, argument in enumerate(arguments):
        if argument in ("/Fo", "-Fo", "-o") and index + 1 < len(arguments):
            return arguments[index + 1]
        if argument.startswith(("/Fo", "-Fo")) and len(argument) > 3:
            return argument[3:]
    match = re.search(
        r'(?:^|\s)(?:[/\-]Fo\s*|-o\s+)(?:"([^"\r\n]+)"|(\S+))',
        entry.get("command", ""),
    )
    if not match:
        raise ValueError("A compilation entry has no object output path.")
    return match.group(1) or match.group(2)


def personal_avatar_targets(entries, build):
    windows = PureWindowsPath(str(build)).is_absolute()
    path_type = PureWindowsPath if windows else PurePosixPath
    normalize = ntpath.normpath if windows else posixpath.normpath
    build = path_type(normalize(str(build)))
    if not build.is_absolute():
        raise ValueError("The canonical build directory must be absolute.")
    expected = {build.parent / source: [] for source in PERSONAL_AVATAR_SOURCES}
    for entry in entries:
        directory = path_type(entry["directory"])
        source = path_type(normalize(str(directory / entry["file"])))
        if source not in expected:
            continue
        output = path_type(normalize(str(directory / compiler_output(entry))))
        try:
            relative = output.relative_to(build)
        except ValueError:
            raise ValueError("An avatar object output escapes the canonical build directory.") from None
        if "Release" not in relative.parts:
            continue
        if relative.suffix != (".obj" if windows else ".o"):
            raise ValueError("An avatar Release output is not a compiler object.")
        expected[source].append(relative.as_posix())
    targets = []
    for source, matches in expected.items():
        if len(matches) != 1:
            raise ValueError(f"Expected one Release object for {source.name}; found {len(matches)}.")
        targets.extend(matches)
    if len(set(targets)) != len(targets):
        raise ValueError("Avatar sources share an ambiguous object output.")
    return targets


def validate_compiler_paths(entries):
    longest = 0
    for entry in entries:
        output = compiler_output(entry)
        path = PureWindowsPath(output)
        if not path.is_absolute():
            path = PureWindowsPath(entry["directory"]) / path
        length = len(str(path))
        if length >= 260:
            raise ValueError(f"Compiler output exceeds the Windows path limit ({length}): {path}")
        longest = max(longest, length)
    if not entries:
        raise ValueError("No compilation entries were generated.")
    return longest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", choices=("Telegram", "external_qt_static_plugins_kimageformats", "personal-avatar-objects"), default="Telegram")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[3]
    build = root / "out"
    entries = json.loads((build / "compile_commands.json").read_text(encoding="utf-8"))
    targets = personal_avatar_targets(entries, build) if args.target == "personal-avatar-objects" else [args.target]
    longest = validate_compiler_paths(entries)
    print(f"Validated {len(entries)} compiler outputs; longest path: {longest} characters.", flush=True)
    print(f"Building {args.target} in canonical directory: {build}", flush=True)
    subprocess.run([
        "cmake", "--build", str(build), "--config", "Release",
        "--target", *targets, "--parallel", "4",
    ], cwd=build, check=True)


if __name__ == "__main__":
    main()
