"""Verify conservative changed-input compilation and real Git rename handling."""

from pathlib import Path, PureWindowsPath
import subprocess
import tempfile
import unittest

from build import changed_paths, changed_source_targets


class ChangedInputTests(unittest.TestCase):
    def setUp(self):
        self.root = PureWindowsPath("C:/Build Root/tdesktop")
        self.build = self.root / "out"
        self.sources = ["Telegram/SourceFiles/one.cpp", "Telegram/SourceFiles/two.cpp"]
        self.entries = [{
            "directory": str(self.build), "file": str(self.root / name),
            "output": f"CMakeFiles/target{index}.dir/Release/file.obj",
        } for index, name in enumerate(self.sources)]

    def select(self, paths):
        return changed_source_targets(self.entries, self.build, paths)[0]

    def test_selects_only_changed_real_compilation_unit(self):
        self.assertEqual(self.select([self.sources[1]]), [self.entries[1]["output"]])

    def test_header_build_recipe_resource_and_dependency_changes_use_full_target(self):
        for name in (
            "Telegram/SourceFiles/type.h", "Telegram/SourceFiles/type.HPP",
            "Telegram/CMakeLists.txt", "Telegram/cmake/options.cmake",
            "Telegram/build/no-stories/configure.py", ".gitmodules",
            "Telegram/ThirdParty/twidget", "Telegram/lib_ui",
            "Telegram/Resources/image.svg", ".github/workflows/no-stories-windows.yml",
        ):
            with self.subTest(name=name):
                self.assertEqual(self.select([self.sources[0], name]), ["Telegram"])

    def test_large_source_edit_uses_one_full_target(self):
        names = [f"Telegram/SourceFiles/source_{index}.cpp" for index in range(65)]
        self.assertEqual(self.select(names), ["Telegram"])

    def test_unmapped_or_removed_source_uses_full_target(self):
        self.assertEqual(self.select(["Telegram/SourceFiles/new.cpp"]), ["Telegram"])
        self.assertEqual(self.select(["Telegram/SourceFiles/removed.cpp"]), ["Telegram"])

    def test_known_other_platform_and_documentation_changes_need_no_windows_object(self):
        self.assertEqual(self.select(["README.md", "docs/guide.md", "Telegram/SourceFiles/platform/mac/code.cpp", "Telegram/SourceFiles/platform/linux/code.cpp"]), [])

    def test_malformed_inputs_are_rejected(self):
        for name in ("../escape.cpp", "/absolute.cpp", "C:/outside.cpp", "folder\\bad.cpp"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.select([name])

    def test_ambiguous_or_escaping_objects_are_not_accepted(self):
        self.entries.append(dict(self.entries[0]))
        with self.assertRaises(ValueError):
            self.select([self.sources[0]])
        self.entries.pop()
        self.entries[0]["output"] = "../outside/Release/source.obj"
        with self.assertRaises(ValueError):
            self.select([self.sources[0]])

    def test_actual_git_rename_and_header_deletion_remain_visible(self):
        with tempfile.TemporaryDirectory(prefix="telegram-changed-inputs-") as directory:
            root = Path(directory)
            def git(*args):
                return subprocess.check_output(["git", "-C", str(root), *args], text=True, stderr=subprocess.DEVNULL).strip()
            git("init", "-q")
            git("config", "user.name", "Fixture")
            git("config", "user.email", "fixture@localhost")
            (root / "space folder").mkdir()
            (root / "space folder/old.cpp").write_text("int value = 1;\n")
            (root / "old.h").write_text("#pragma once\n")
            git("add", ".")
            git("commit", "-qm", "Baseline")
            base = git("rev-parse", "HEAD")
            git("mv", "space folder/old.cpp", "space folder/new.cpp")
            git("rm", "old.h")
            git("commit", "-qm", "Rename and remove")
            self.assertEqual(set(changed_paths(root, base)), {"space folder/old.cpp", "space folder/new.cpp", "old.h"})
            with self.assertRaises(ValueError):
                changed_paths(root, "HEAD")


if __name__ == "__main__":
    unittest.main()
