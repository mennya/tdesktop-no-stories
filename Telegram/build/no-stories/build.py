import argparse
import json
from pathlib import Path, PureWindowsPath
import re
import subprocess


def validate_compiler_paths(entries):
    longest = 0
    for entry in entries:
        output = entry.get("output")
        if not output:
            match = re.search(r'/Fo(?:"([^"\r\n]+)"|(\S+))', entry.get("command", ""))
            if not match:
                raise ValueError("A compilation entry has no object output path.")
            output = match.group(1) or match.group(2)
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
    parser.add_argument("--target", choices=("Telegram", "external_qt_static_plugins_kimageformats"), default="Telegram")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[3]
    build = root / "out"
    entries = json.loads((build / "compile_commands.json").read_text(encoding="utf-8"))
    longest = validate_compiler_paths(entries)
    print(f"Validated {len(entries)} compiler outputs; longest path: {longest} characters.", flush=True)
    print(f"Building {args.target} in canonical directory: {build}", flush=True)
    subprocess.run([
        "cmake", "--build", str(build), "--config", "Release",
        "--target", args.target, "--parallel", "4",
    ], cwd=build, check=True)


if __name__ == "__main__":
    main()
