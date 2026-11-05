"""Test exact Release object selection; optionally require a real Ninja Multi-Config build."""

import argparse
import json
from pathlib import Path, PurePosixPath, PureWindowsPath
import shutil
import subprocess
import tempfile
import unittest

from build import (
    PERSONAL_AVATAR_SOURCES,
    STRICT_MUTE_SOURCES,
    compiler_output,
    personal_avatar_targets,
    release_object_targets,
    strict_mute_targets,
    validate_compiler_paths,
)


class ObjectSelectionTests(unittest.TestCase):
    sources = PERSONAL_AVATAR_SOURCES
    select = staticmethod(personal_avatar_targets)

    def setUp(self):
        self.root = PureWindowsPath("C:/Build Root/tdesktop")
        self.build = self.root / "out"
        self.entries = [self.entry(source, index) for index, source in enumerate(self.sources)]

    def entry(self, source, index, config="Release"):
        return {
            "directory": str(self.build),
            "file": str(self.root / source),
            "output": f"CMakeFiles/target{index}.dir/{config}/source.cpp.obj",
        }

    def test_release_objects_ignore_debug(self):
        entries = self.entries + [self.entry(source, index, "Debug") for index, source in enumerate(self.sources)]
        self.assertEqual(self.select(entries, self.build), [entry["output"] for entry in self.entries])

    def test_command_and_arguments_outputs(self):
        for entry, expected in (
            ({"command": 'cl /c source.cpp /Fo"path with spaces/object.obj"'}, "path with spaces/object.obj"),
            ({"command": 'cl -Fopath/object.obj /c source.cpp'}, "path/object.obj"),
            ({"command": 'c++ -o "path with spaces/object.o" -c source.cpp'}, "path with spaces/object.o"),
            ({"arguments": ["cl", "/Fo", "path with spaces/object.obj"]}, "path with spaces/object.obj"),
            ({"arguments": ["cl", "/Fopath/object.obj"]}, "path/object.obj"),
            ({"arguments": ["c++", "-o", "path/object.o"]}, "path/object.o"),
        ):
            with self.subTest(entry=entry):
                self.assertEqual(compiler_output(entry), expected)

    def test_missing_output_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "no object output"):
            compiler_output({"command": "cl /c source.cpp"})

    def test_absolute_output_and_relative_source(self):
        self.entries[0]["file"] = "../" + self.sources[0]
        self.entries[0]["output"] = str(self.build / self.entries[0]["output"])
        self.assertEqual(len(self.select(self.entries, self.build)), len(self.sources))

    def test_source_from_other_checkout_is_not_selected(self):
        self.entries[0]["file"] = str(PureWindowsPath("C:/Another/tdesktop") / self.sources[0])
        with self.assertRaisesRegex(ValueError, "found 0"):
            self.select(self.entries, self.build)

    def test_missing_release_is_rejected(self):
        self.entries[0]["output"] = self.entries[0]["output"].replace("Release", "Debug")
        with self.assertRaisesRegex(ValueError, "found 0"):
            self.select(self.entries, self.build)

    def test_ambiguous_release_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "found 2"):
            self.select(self.entries + [self.entries[0]], self.build)

    def test_escaping_output_is_rejected(self):
        for output in (
            "../outside/Release/object.obj",
            "C:/Build Root/tdesktop/outside/Release/object.obj",
            "D:/out/Release/object.obj",
            "C:/Build Root/tdesktop/out/../outside/Release/object.obj",
        ):
            with self.subTest(output=output):
                self.entries[0]["output"] = output
                with self.assertRaisesRegex(ValueError, "escapes"):
                    self.select(self.entries, self.build)

    def test_non_object_is_rejected(self):
        self.entries[0]["output"] = "CMakeFiles/target0.dir/Release/file.pdb"
        with self.assertRaisesRegex(ValueError, "not a compiler object"):
            self.select(self.entries, self.build)

    def test_shared_output_is_rejected(self):
        self.entries[1]["output"] = self.entries[0]["output"]
        with self.assertRaisesRegex(ValueError, "ambiguous object"):
            self.select(self.entries, self.build)

    def test_windows_shared_output_with_different_case_is_rejected(self):
        self.entries[1]["output"] = self.entries[0]["output"].replace("target0", "TARGET0")
        with self.assertRaisesRegex(ValueError, "ambiguous object"):
            self.select(self.entries, self.build)

    def test_compiler_path_limit(self):
        entry = {"directory": "C:/", "output": "x" * 256}
        self.assertEqual(validate_compiler_paths([entry]), 259)
        entry["output"] += "x"
        with self.assertRaisesRegex(ValueError, "path limit"):
            validate_compiler_paths([entry])
        with self.assertRaisesRegex(ValueError, "No compilation entries"):
            validate_compiler_paths([])

    def test_relative_build_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "must be absolute"):
            self.select(self.entries, Path("out"))

    def test_source_folder_named_release_is_not_a_configuration(self):
        extra = self.entry(self.sources[0], 0, "Debug")
        extra["output"] = "CMakeFiles/target0.dir/Debug/Release/source.cpp.obj"
        self.assertEqual(self.select(self.entries + [extra], self.build), [entry["output"] for entry in self.entries])

    def test_other_sources_are_not_selected(self):
        extra = self.entry("Telegram/SourceFiles/not_selected.cpp", 999)
        self.assertEqual(self.select(self.entries + [extra], self.build), [entry["output"] for entry in self.entries])

    def test_windows_checkout_paths_are_case_insensitive(self):
        self.entries[0]["file"] = self.entries[0]["file"].upper()
        self.entries[0]["directory"] = self.entries[0]["directory"].upper()
        self.assertEqual(self.select(self.entries, self.build), [entry["output"] for entry in self.entries])


class StrictMuteSelectionTests(ObjectSelectionTests):
    sources = STRICT_MUTE_SOURCES
    select = staticmethod(strict_mute_targets)


class SourceSelectionTests(unittest.TestCase):
    def test_invalid_source_selection_is_rejected(self):
        build = PureWindowsPath("C:/Build Root/tdesktop/out")
        for sources in (
            (),
            (PERSONAL_AVATAR_SOURCES[0], PERSONAL_AVATAR_SOURCES[0]),
            (PERSONAL_AVATAR_SOURCES[0], PERSONAL_AVATAR_SOURCES[0].upper()),
            ("../outside.cpp",),
            ("/outside.cpp",),
            ("C:/Other/checkout/source.cpp",),
            ("D:relative.cpp",),
        ):
            with self.subTest(sources=sources), self.assertRaises(ValueError):
                release_object_targets([], build, sources)

    def test_posix_source_and_output_paths(self):
        root = PurePosixPath("/build/tdesktop")
        build = root / "out"
        entries = [{
            "directory": str(build),
            "file": str(root / source),
            "arguments": ["c++", "-o", f"CMakeFiles/target{index}.dir/Release/file.o"],
        } for index, source in enumerate(STRICT_MUTE_SOURCES)]
        self.assertEqual(strict_mute_targets(entries, build), [entry["arguments"][-1] for entry in entries])


def ninja_fixture(mode):
    missing = [tool for tool in ("cmake", "ninja") if not shutil.which(tool)]
    if mode == "skip" or (mode == "auto" and missing):
        print("SKIP: Ninja Multi-Config integration " + ("not requested." if mode == "skip" else "tools unavailable: " + ", ".join(missing)))
        return
    if missing:
        raise RuntimeError("Required Ninja Multi-Config tools unavailable: " + ", ".join(missing))
    with tempfile.TemporaryDirectory(prefix="telegram object targets-") as directory:
        root = Path(directory).resolve()
        build = root / "out"
        sources = tuple(dict.fromkeys(PERSONAL_AVATAR_SOURCES + STRICT_MUTE_SOURCES))
        for index, relative in enumerate(sources):
            source = root / relative
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_text(f"int fixture_{index}() {{ return {index}; }}\n", encoding="utf-8")
        root.joinpath("unselected.cpp").write_text("#error Unselected source must not compile\n", encoding="utf-8")
        root.joinpath("CMakeLists.txt").write_text(
            'cmake_minimum_required(VERSION 3.20)\n'
            'project(SelectedReleaseObjects LANGUAGES CXX)\n'
            'set(CMAKE_CONFIGURATION_TYPES "Debug;Release" CACHE STRING "" FORCE)\n'
            'set(CMAKE_EXPORT_COMPILE_COMMANDS ON)\n'
            f'add_library(low OBJECT {sources[0]})\n'
            f'add_library(app OBJECT {" ".join(sources[1:])})\n'
            'add_library(unselected OBJECT unselected.cpp)\n',
            encoding="utf-8",
        )
        subprocess.run([
            "cmake", "-S", str(root), "-B", str(build), "-G", "Ninja Multi-Config",
        ], check=True, capture_output=True, text=True, timeout=60)
        entries = json.loads(build.joinpath("compile_commands.json").read_text(encoding="utf-8"))
        selected = set()
        for label, selector in (
            ("personal avatars", personal_avatar_targets),
            ("strict mute", strict_mute_targets),
        ):
            targets = selector(entries, build)
            subprocess.run([
                "cmake", "--build", str(build), "--config", "Release", "--target", *targets, "--parallel", "2",
            ], check=True, capture_output=True, text=True, timeout=60)
            if not all((build / target).is_file() for target in targets):
                raise RuntimeError(f"Requested {label} Release objects were not created.")
            selected.update((build / target).resolve() for target in targets)
            others = [(Path(entry["directory"]) / compiler_output(entry)).resolve() for entry in entries]
            if any(path.is_file() for path in others if path not in selected):
                raise RuntimeError(f"{label} object build unexpectedly compiled Debug or unselected sources.")
            print(f"PASS: Ninja Multi-Config built only {len(targets)} selected {label} Release objects.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--integration", choices=("skip", "auto", "required"), default="skip")
    args = parser.parse_args()
    suite = unittest.TestSuite(
        unittest.defaultTestLoader.loadTestsFromTestCase(case)
        for case in (ObjectSelectionTests, StrictMuteSelectionTests, SourceSelectionTests)
    )
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    if not result.wasSuccessful():
        raise SystemExit(1)
    try:
        ninja_fixture(args.integration)
    except subprocess.CalledProcessError as error:
        print((error.stdout or "")[-4000:] + (error.stderr or "")[-2000:])
        raise SystemExit("Ninja Multi-Config integration failed.") from None


if __name__ == "__main__":
    main()
