#!/usr/bin/env python3
"""Execute verbatim avatar policy/model functions with synthetic dependencies.
This does not compile Telegram, exercise Qt painting, or verify the GUI.
"""

import argparse
from pathlib import Path
import subprocess
import tempfile


def extract(source: str, signature: str) -> str:
    start = source.index(signature)
    body = source.index("{", start)
    depth = 1
    end = body + 1
    while depth:
        if source[end] == "{":
            depth += 1
        elif source[end] == "}":
            depth -= 1
        end += 1
    return source[start:end]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cxx", default="g++")
    args = parser.parse_args()
    here = Path(__file__).resolve().parent
    sources = here.parents[1] / "SourceFiles"
    policy = (sources / "ui/userpic_view.cpp").read_text(encoding="utf-8")
    peer = (sources / "data/data_peer.cpp").read_text(encoding="utf-8")
    user = (sources / "data/data_user.cpp").read_text(encoding="utf-8")
    functions = ["namespace Ui {", *[
        extract(policy, signature) for signature in (
            "bool PersonalUserpicOnly(",
            "bool PeerUserpicPhotoAllowed(",
        )
    ], "}", *[
        extract(peer, signature) for signature in (
            "QImage *PeerData::userpicCloudImage(",
            "void PeerData::loadUserpic(",
            "Ui::PeerUserpicView PeerData::activeUserpicView(",
            "Ui::PeerUserpicView PeerData::createUserpicView(",
            "bool PeerData::useEmptyUserpic(",
            "InMemoryKey PeerData::userpicUniqueKey(",
        )
    ], extract(user, "void UserData::setPhoto(")]
    fixture = here.joinpath("test_personal_userpics.cpp").read_text(encoding="utf-8")
    marker = "// PRODUCTION_FUNCTIONS"
    if fixture.count(marker) != 1:
        raise RuntimeError("Expected one production function insertion point")
    combined = fixture.replace(marker, "\n\n".join(functions))
    with tempfile.TemporaryDirectory(prefix="telegram-userpics-model-") as directory:
        source = Path(directory) / "model.cpp"
        binary = Path(directory) / "model"
        source.write_text(combined, encoding="utf-8")
        subprocess.run([
            args.cxx, "-std=c++20", "-Wall", "-Wextra", "-Werror",
            str(source), "-o", str(binary),
        ], check=True, timeout=45)
        subprocess.run([str(binary)], check=True, timeout=10)


if __name__ == "__main__":
    main()
