#!/usr/bin/env python3
"""Run extracted production unread projections with synthetic session/dialog data.

This compiles actual arithmetic/projection functions, not Telegram or Qt widgets.
It verifies raw-state preservation, exclusion/restore, archive cold-start and
ignore-current semantics. Server timing, RPCs, rendering and event wiring still
require the normal application build and acceptance checks.
"""
import argparse
from pathlib import Path
import subprocess
import tempfile
from test_personal_userpics import extract


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cxx", default="g++")
    args = parser.parse_args()
    here = Path(__file__).resolve().parent
    sources = here.parents[1] / "SourceFiles"
    common = (sources / "dialogs/dialogs_common.h").read_text()
    state = common[common.index("struct UnreadState {"):common.index("#ifdef _DEBUG", common.index("struct UnreadState {"))]
    main_list = (sources / "dialogs/dialogs_main_list.cpp").read_text()
    unread = (sources / "data/data_unread_value.cpp").read_text()
    session = (sources / "data/data_session.cpp").read_text()
    filters = (sources / "data/data_chat_filters.cpp").read_text()
    funcs = "namespace Dialogs {\n" + "\n".join(extract(main_list, sig) for sig in (
        "UnreadState MainList::unreadState() const",
        "UnreadState MainList::attentionUnreadState() const",
    )) + "\n}\nnamespace Data {\n" + "\n".join(extract(unread, sig) for sig in (
        "Dialogs::UnreadState AttentionUnreadState(",
        "Dialogs::UnreadState BadgeUnreadState(",
        "[[nodiscard]] Dialogs::UnreadState MainListMapUnreadState(",
    )) + "\n" + "\n".join(extract(session, sig) for sig in (
        "int Session::computeUnreadBadge(",
        "bool Session::computeUnreadBadgeMuted(",
        "int Session::unreadBadge() const",
        "int Session::unreadBadgeIgnoreOne(",
        "bool Session::unreadBadgeMutedIgnoreOne(",
    )) + "\n}\n"
    funcs += "namespace Data {\n" + extract(filters, "bool ChatFilter::contains(") + "\n}\n"
    fixture = here.joinpath("test_strict_mute_unread.cpp").read_text()
    combined = fixture.replace("// PRODUCTION_STATE", state).replace("// PRODUCTION_FUNCTIONS", funcs)
    with tempfile.TemporaryDirectory(prefix="telegram-strict-mute-unread-") as directory:
        source = Path(directory) / "model.cpp"
        binary = Path(directory) / "model"
        source.write_text(combined)
        subprocess.run([args.cxx, "-std=c++20", "-Wall", "-Wextra", "-Werror", str(source), "-o", str(binary)], check=True, timeout=45)
        subprocess.run([str(binary)], check=True, timeout=10)


if __name__ == "__main__":
    main()
