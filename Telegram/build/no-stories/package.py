import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import zipfile


def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[3]
    release = root / "out" / "Release"
    if not (release / "Telegram.exe").is_file():
        sys.exit("Release Telegram.exe was not produced.")
    kind = os.environ.get("BUILD_KIND", "production")
    if kind not in ("production", "verification"):
        sys.exit("Unknown BUILD_KIND.")
    version_text = (root / "Telegram" / "build" / "version").read_text()
    version = re.search(r"^AppVersionStrSmall\s+(\S+)$", version_text, re.M)[1]
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    name = f"telegram-no-stories-{version}-win-x64-{commit[:8]}-{kind}"
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    stage = root / "out" / name
    if stage.exists():
        sys.exit("Package staging directory already exists; use a fresh build output.")
    stage.mkdir()
    shutil.copy2(release / "Telegram.exe", stage / "Telegram.exe")
    for dll in release.glob("*.dll"):
        shutil.copy2(dll, stage / dll.name)
    if (release / "modules").is_dir():
        shutil.copytree(release / "modules", stage / "modules")
    portable = stage / "TelegramForcePortable"
    portable.mkdir()
    (portable / "KEEP-THIS-FOLDER.txt").write_text(
        "This directory keeps this fork's account data separate from official Telegram.\n"
        "Do not delete it while using this installation.\n", encoding="utf-8")
    for filename in ("LICENSE", "LEGAL"):
        shutil.copy2(root / filename, stage / filename)
    warning = ("VERIFICATION ONLY: built with Telegram test credentials. "
               "Do not use this package as your daily client.\n\n") if kind == "verification" else ""
    (stage / "README.txt").write_text(
        warning + "Telegram No Stories - Windows x64\n\n"
        "Extract the whole portable ZIP into its own writable folder and run Telegram.exe.\n"
        "Keep TelegramForcePortable beside the executable. Sign in normally.\n"
        "Never extract this package over an official Telegram installation or copy its tdata.\n"
        "Official auto-updates are disabled; install rebuilt fork updates manually.\n"
        "The installer uses a separate folder and preserves account data when uninstalled.\n"
        "This personal build is unsigned.\n\n"
        f"Source: https://github.com/mennya/tdesktop-no-stories/tree/{commit}\n"
        f"Build kind: {kind}\n", encoding="utf-8")
    manifest = {
        "name": "Telegram No Stories", "version": version, "commit": commit,
        "platform": "windows-x64", "configuration": "Release", "build_kind": kind,
        "official_auto_updates": False, "signed": False,
        "executable_sha256": sha256(stage / "Telegram.exe"),
    }
    (stage / "build-info.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    with zipfile.ZipFile(output / (name + "-portable.zip"), "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for item in sorted(stage.rglob("*")):
            if item.is_file():
                archive.write(item, Path("Telegram No Stories") / item.relative_to(stage))
    compiler = shutil.which("ISCC.exe") or str(
        Path(os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)")) / "Inno Setup 6" / "ISCC.exe")
    if not Path(compiler).is_file():
        sys.exit("Inno Setup compiler is missing on the build runner.")
    subprocess.run([
        compiler, "/Qp", f"/DPackageDir={stage}", f"/DOutputDir={output}",
        f"/DPackageVersion={version}", f"/DPackageName={name}",
        str(Path(__file__).with_name("setup.iss")),
    ], check=True)
    shutil.copy2(stage / "build-info.json", output / (name + "-build-info.json"))
    checksums = "".join(f"{sha256(path)}  {path.name}\n" for path in sorted(output.iterdir()) if path.is_file())
    (output / "SHA256SUMS.txt").write_text(checksums, encoding="utf-8")
    print("Packaged", name)


if __name__ == "__main__":
    main()
