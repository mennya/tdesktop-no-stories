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

STRICT_MUTE_SOURCES = (
    "Telegram/SourceFiles/main/main_strict_mute.cpp",
    "Telegram/SourceFiles/main/main_session.cpp",
    "Telegram/SourceFiles/data/data_chat_filters.cpp",
    "Telegram/SourceFiles/data/data_folder.cpp",
    "Telegram/SourceFiles/data/data_forum_topic.cpp",
    "Telegram/SourceFiles/data/data_session.cpp",
    "Telegram/SourceFiles/data/data_unread_value.cpp",
    "Telegram/SourceFiles/dialogs/dialogs_entry.cpp",
    "Telegram/SourceFiles/dialogs/dialogs_main_list.cpp",
    "Telegram/SourceFiles/dialogs/ui/dialogs_layout.cpp",
    "Telegram/SourceFiles/history/history.cpp",
    "Telegram/SourceFiles/history/history_widget.cpp",
    "Telegram/SourceFiles/history/view/history_view_chat_section.cpp",
    "Telegram/SourceFiles/history/view/history_view_corner_buttons.cpp",
    "Telegram/SourceFiles/history/view/history_view_subsection_tabs.cpp",
    "Telegram/SourceFiles/history/view/history_view_top_bar_widget.cpp",
    "Telegram/SourceFiles/window/notifications_manager.cpp",
    "Telegram/SourceFiles/window/window_peer_menu.cpp",
    "Telegram/SourceFiles/calls/calls_call.cpp",
    "Telegram/SourceFiles/calls/calls_panel.cpp",
    "Telegram/SourceFiles/ui/boxes/confirm_box.cpp",
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


def release_object_targets(entries, build, sources):
    windows = PureWindowsPath(str(build)).is_absolute()
    path_type = PureWindowsPath if windows else PurePosixPath
    normalize = ntpath.normpath if windows else posixpath.normpath
    build = path_type(normalize(str(build)))
    if not build.is_absolute():
        raise ValueError("The canonical build directory must be absolute.")
    relative_sources = [path_type(source) for source in sources]
    if not relative_sources or len(set(relative_sources)) != len(relative_sources):
        raise ValueError("Object source selection must be nonempty and unique.")
    if any(source.root or source.drive or ".." in source.parts for source in relative_sources):
        raise ValueError("Object sources must stay relative to the source checkout.")
    expected = {build.parent / source: [] for source in relative_sources}
    for entry in entries:
        directory = path_type(entry["directory"])
        source = path_type(normalize(str(directory / entry["file"])))
        if source not in expected:
            continue
        output = path_type(normalize(str(directory / compiler_output(entry))))
        try:
            relative = output.relative_to(build)
        except ValueError:
            raise ValueError("An object output escapes the canonical build directory.") from None
        # Ninja Multi-Config puts the configuration immediately after the
        # CMakeFiles/<target>.dir component. A source folder called Release
        # must not turn a Debug object into a selected Release target.
        parts = relative.parts
        config = next((
            parts[index + 2]
            for index in range(len(parts) - 2)
            if parts[index] == "CMakeFiles" and parts[index + 1].endswith(".dir")
        ), None)
        if config != "Release":
            continue
        if relative.suffix != (".obj" if windows else ".o"):
            raise ValueError("A Release output is not a compiler object.")
        expected[source].append(relative.as_posix())
    targets = []
    for source, matches in expected.items():
        if len(matches) != 1:
            raise ValueError(f"Expected one Release object for {source.name}; found {len(matches)}.")
        targets.extend(matches)
    if len({path_type(target) for target in targets}) != len(targets):
        raise ValueError("Sources share an ambiguous object output.")
    return targets


def personal_avatar_targets(entries, build):
    return release_object_targets(entries, build, PERSONAL_AVATAR_SOURCES)


def strict_mute_targets(entries, build):
    return release_object_targets(entries, build, STRICT_MUTE_SOURCES)


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
    parser.add_argument("--target", choices=(
        "Telegram",
        "external_qt_static_plugins_kimageformats",
        "personal-avatar-objects",
        "strict-mute-objects",
    ), default="Telegram")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[3]
    build = root / "out"
    entries = json.loads((build / "compile_commands.json").read_text(encoding="utf-8"))
    selectors = {
        "personal-avatar-objects": personal_avatar_targets,
        "strict-mute-objects": strict_mute_targets,
    }
    selector = selectors.get(args.target)
    targets = selector(entries, build) if selector else [args.target]
    longest = validate_compiler_paths(entries)
    print(f"Validated {len(entries)} compiler outputs; longest path: {longest} characters.", flush=True)
    print(f"Building {args.target} in canonical directory: {build}", flush=True)
    subprocess.run([
        "cmake", "--build", str(build), "--config", "Release",
        "--target", *targets, "--parallel", "4",
    ], cwd=build, check=True)


if __name__ == "__main__":
    main()
