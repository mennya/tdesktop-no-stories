"""Compile and run the shipping verifier/feed/extractor translation units."""
from pathlib import Path
import shlex
import subprocess
import tempfile


def main():
    root = Path(__file__).resolve().parents[3]
    source = root / "Telegram" / "SourceFiles"
    trust = root / "Telegram" / "Resources" / "no-stories" / "update"
    flags = shlex.split(subprocess.check_output(
        ["pkg-config", "--cflags", "--libs", "Qt6Core", "openssl", "liblzma"], text=True))
    output_root = root / "out" / "fork-unit-tests"
    output_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output_root) as temporary:
        work = Path(temporary)
        header = "#pragma once\nnamespace Core::Updates::details {\n"
        for name, path in (("kRootPublicKeyPem", "root-public.pem"),
                           ("kEmbeddedManifest", "manifest.min.json"),
                           ("kEmbeddedManifestSig", "manifest.sig")):
            data = (trust / path).read_bytes()
            header += "inline constexpr unsigned char " + name + "[] = {"
            header += ",".join(str(x) for x in data) + "};\n"
        (work / "update_keys_data.h").write_text(header + "}\n")
        (work / "fork_update_build.h").write_text(
            "#pragma once\ninline constexpr auto ForkUpdateBuildCounter = 40010U;\n"
            'inline constexpr char ForkUpdateUserAgent[] = "Telegram-No-Stories fork-build:40010 windows-x64";\n')
        cases = [
            ("fork", ["core/fork_update.cpp", "core/update_keys.cpp", "core/update_verify.cpp",
                      "core/update_unpack.cpp", "tests/test_fork_update.cpp"], True),
            ("verify", ["core/update_keys.cpp", "core/update_verify.cpp", "tests/test_update_verify.cpp"], True),
            ("unpack", ["core/update_unpack.cpp", "tests/test_update_unpack.cpp"], False),
        ]
        for name, files, fork in cases:
            executable = work / name
            args = ["g++", "-std=c++20", "-O1", "-fPIC", "-Wall", "-Wextra", "-Werror",
                    "-I" + str(source), "-I" + str(work)]
            if fork:
                args += ["-DTDESKTOP_FORK_AUTOUPDATE"]
            args += [str(source / item) for item in files] + flags + ["-o", str(executable)]
            subprocess.run(args, check=True)
            subprocess.run([str(executable)], check=True)


if __name__ == "__main__":
    main()
