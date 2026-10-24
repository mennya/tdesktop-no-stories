import argparse
import os
from pathlib import Path
import re
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()
    kind = os.environ.get("BUILD_KIND", "production")
    if kind not in ("production", "verification"):
        sys.exit("Unknown BUILD_KIND.")
    api_id = os.environ.get("TDESKTOP_API_ID", "")
    api_hash = os.environ.get("TDESKTOP_API_HASH", "")
    if kind == "production":
        if not re.fullmatch(r"[1-9][0-9]*", api_id):
            sys.exit("Production requires a valid TDESKTOP_API_ID repository secret.")
        if not re.fullmatch(r"[a-fA-F0-9]{32}", api_hash):
            sys.exit("Production requires a valid TDESKTOP_API_HASH repository secret.")
        if api_id == "17349":
            sys.exit("Test credentials are not allowed in a production build.")
    print("Build kind:", kind)
    if args.validate_only:
        return
    root = Path(__file__).resolve().parents[3]
    cache = root / "out" / "fork-api-cache.cmake"
    cache.parent.mkdir(exist_ok=True)
    try:
        if kind == "production":
            contents = (
                'set(TDESKTOP_API_TEST OFF CACHE BOOL "" FORCE)\n'
                f'set(TDESKTOP_API_ID "{api_id}" CACHE STRING "" FORCE)\n'
                f'set(TDESKTOP_API_HASH "{api_hash}" CACHE STRING "" FORCE)\n'
            )
        else:
            contents = 'set(TDESKTOP_API_TEST ON CACHE BOOL "" FORCE)\n'
        cache.write_text(contents, encoding="utf-8")
        subprocess.run([
            sys.executable, str(root / "Telegram" / "configure.py"),
            "-G", "Ninja Multi-Config", "qt6", "-C", str(cache),
            "-DCMAKE_CONFIGURATION_TYPES=Release",
            "-DCMAKE_COMPILE_WARNING_AS_ERROR=ON",
            "-DCMAKE_MSVC_DEBUG_INFORMATION_FORMAT=",
            "-DDESKTOP_APP_DISABLE_AUTOUPDATE=ON",
            "-DDESKTOP_APP_DISABLE_CRASH_REPORTS=ON",
        ], cwd=root / "Telegram", check=True)
    finally:
        cache.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
