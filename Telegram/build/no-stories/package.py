import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import zipfile

from fork_update_tools import checksum_file, counter_from_env, sha256, version_base


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[3]
    release = root / "out" / "Release"
    for executable in ("Telegram.exe", "Updater.exe", "Packer.exe"):
        if not (release / executable).is_file():
            sys.exit(f"Release {executable} was not produced.")
    kind = os.environ.get("BUILD_KIND", "production")
    if kind not in ("production", "verification"):
        sys.exit("Unknown BUILD_KIND.")
    counter = counter_from_env()
    generated = root / "out" / "Telegram" / "gen" / "fork_update_build.h"
    if not generated.exists():
        generated = root / "out" / "gen" / "fork_update_build.h"
    match = re.search(r"ForkUpdateBuildCounter = ([0-9]+)U;", generated.read_text())
    if not match or int(match[1]) != counter:
        sys.exit("Configured fork counter differs from the package counter.")
    version_text = (root / "Telegram" / "build" / "version").read_text()
    version = re.search(r"^AppVersionStrSmall\s+(\S+)$", version_text, re.M)[1]
    base = version_base(version)
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    name = f"telegram-no-stories-{version}-win-x64-{commit[:8]}-b{counter}-{kind}"
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    stage = root / "out" / name
    if stage.exists():
        sys.exit("Package staging directory exists; use a fresh build counter.")
    stage.mkdir()
    for executable in ("Telegram.exe", "Updater.exe"):
        shutil.copy2(release / executable, stage / executable)
    for dll in release.glob("*.dll"):
        shutil.copy2(dll, stage / dll.name)
    if (release / "modules").is_dir():
        shutil.copytree(release / "modules", stage / "modules")
    portable = stage / "TelegramForcePortable"
    portable.mkdir()
    (portable / "KEEP-THIS-FOLDER.txt").write_text(
        "This directory keeps this fork's account data separate from official Telegram.\n"
        "Keep it when updating this installation.\n", encoding="utf-8")
    for filename in ("LICENSE", "LEGAL"):
        shutil.copy2(root / filename, stage / filename)
    warning = ("VERIFICATION ONLY: built with Telegram test credentials. "
               "Do not use this package as your daily client.\n\n") if kind == "verification" else ""
    (stage / "README.txt").write_text(
        warning + "Telegram No Stories - Windows x64\n\n"
        "Extract the whole portable ZIP into its own writable folder and run Telegram.exe.\n"
        "Keep TelegramForcePortable beside the executable. Sign in normally.\n"
        "Never extract over official Telegram or import its session files.\n"
        "This bootstrap enables signed updates from this fork's GitHub Releases.\n"
        "Updates download in the background and install only when you click Update.\n"
        "Account data and local settings are not included in update packages.\n"
        "Manual replacement of program files remains available for recovery.\n"
        "The Windows executables and installer do not carry an Authenticode certificate.\n\n"
        f"Source: https://github.com/mennya/tdesktop-no-stories/tree/{commit}\n"
        f"Build kind: {kind}; fork build: {counter}\n", encoding="utf-8")
    manifest = {
        "name": "Telegram No Stories", "version": version, "commit": commit,
        "platform": "windows-x64", "configuration": "Release", "build_kind": kind,
        "official_auto_updates": False, "fork_auto_updates": True,
        "fork_build": counter, "signed": False, "update_signature": "Ed25519",
        "executable_sha256": sha256(stage / "Telegram.exe"),
        "updater_sha256": sha256(stage / "Updater.exe"),
    }
    (stage / "build-info.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    with zipfile.ZipFile(output / (name + "-portable.zip"), "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for item in sorted(stage.rglob("*")):
            if item.is_file():
                archive.write(item, Path("Telegram No Stories") / item.relative_to(stage))
    compiler = shutil.which("ISCC.exe") or str(
        Path(os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)")) / "Inno Setup 6" / "ISCC.exe")
    if not Path(compiler).is_file():
        sys.exit("Inno Setup compiler is missing.")
    subprocess.run([
        compiler, "/Qp", f"/DPackageDir={stage}", f"/DOutputDir={output}",
        f"/DPackageVersion={version}", f"/DPackageName={name}",
        str(Path(__file__).with_name("setup.iss")),
    ], check=True)
    shutil.copy2(stage / "build-info.json", output / (name + "-build-info.json"))
    if kind == "production":
        update = root / "out" / (name + "-update")
        update.mkdir()
        for item in stage.iterdir():
            if item.name == "TelegramForcePortable":
                continue
            if item.is_dir():
                shutil.copytree(item, update / item.name)
            else:
                shutil.copy2(item, update / item.name)
        signing_input = update / "signing-input.tmp"
        paths = []
        for item in sorted(update.iterdir(), key=lambda x: (x.name != "Telegram.exe", x.name)):
            paths += ["-path", item.name]
        subprocess.run([
            str(release / "Packer.exe"), *paths, "-target", "win64",
            "-version", str(base), "-counter", str(counter), "-channel", "stable",
            "-keys-loc", str(root / "Telegram" / "Resources" / "no-stories" / "update"),
            "-emit-signing-input", str(signing_input),
        ], cwd=update, check=True)
        unsigned_name = f"td-update-win-x64-{base}-fork-{counter}.unsigned"
        shutil.move(str(update / unsigned_name), output / unsigned_name)
        signing_input.unlink()
    checksum_file(output)
    print("Packaged", name, "(native update awaits isolated signing)")


if __name__ == "__main__":
    main()
