"""Stage or publish only native-verified production updates of this repository."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
import zipfile

from fork_update_tools import (REPOSITORY, UpdateError, checksum_file, counter_from_env,
                               sha256, sign_release, verify_artifact_checksums, version_base)


MAX_ARCHIVE = 2 * 1024 * 1024 * 1024


class ArtifactRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        parsed = urllib.parse.urlsplit(urllib.parse.urljoin(request.full_url, newurl))
        host = parsed.hostname or ""
        if (parsed.scheme != "https" or parsed.username or parsed.password
                or not (host.endswith(".blob.core.windows.net")
                        or host.endswith(".githubusercontent.com")
                        or host == "github.com" or host == "api.github.com")):
            raise UpdateError("Artifact redirect left the allowed HTTPS download hosts.")
        result = super().redirect_request(request, fp, code, message, headers, newurl)
        if result:
            # A repository token must never follow a signed artifact/CDN URL.
            result.remove_header("Authorization")
        return result


def request(path):
    token = os.environ.get("GH_TOKEN", "")
    if not token:
        raise UpdateError("The CI repository token is required.")
    if not path.startswith("/repos/" + REPOSITORY + "/"):
        raise UpdateError("API request left the configured repository.")
    return urllib.request.Request("https://api.github.com" + path, headers={
        "Authorization": "Bearer " + token, "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "Telegram-No-Stories-Publisher"})


def api(path, missing_ok=False):
    try:
        with urllib.request.build_opener(ArtifactRedirect()).open(request(path), timeout=45) as response:
            data = response.read(2 * 1024 * 1024 + 1)
            if len(data) > 2 * 1024 * 1024:
                raise UpdateError("Oversized GitHub API response.")
            return json.loads(data)
    except urllib.error.HTTPError as error:
        if missing_ok and error.code == 404:
            return None
        raise UpdateError(f"GitHub API returned HTTP {error.code}.") from None
    except (urllib.error.URLError, TimeoutError):
        raise UpdateError("GitHub API request could not finish.") from None


def source_run(run_id, commit):
    if not re.fullmatch(r"[1-9][0-9]*", str(run_id)) or not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise UpdateError("An exact production run and commit are required.")
    data = api(f"/repos/{REPOSITORY}/actions/runs/{run_id}")
    if (str(data.get("id")) != str(run_id)
            or data.get("head_sha") != commit or data.get("head_branch") != "codex/no-stories"
            or data.get("event") not in ("push", "workflow_dispatch")
            or data.get("status") != "completed" or data.get("conclusion") != "success"
            or data.get("path") != ".github/workflows/no-stories-windows.yml"
            or data.get("repository", {}).get("full_name") != REPOSITORY):
        raise UpdateError("Source is not a successful exact-commit protected-branch production run.")
    return data


def unpack_artifact(archive, directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    with zipfile.ZipFile(archive) as source:
        entries = source.infolist()
        if not entries or len(entries) > 512:
            raise UpdateError("Artifact file count exceeds bounds.")
        names, total = set(), 0
        for item in entries:
            total += item.file_size
            reserved = {"CON", "PRN", "AUX", "NUL"} | {f"{p}{i}" for p in ("COM", "LPT") for i in range(1, 10)}
            if (item.is_dir() or not re.fullmatch(r"[A-Za-z0-9_.-]{1,200}", item.filename)
                    or item.filename.startswith(".") or item.filename.endswith(".")
                    or item.filename.split(".")[0].upper() in reserved
                    or item.filename.lower() in names or total > MAX_ARCHIVE
                    or item.flag_bits & 1 or (item.external_attr >> 16) & 0o170000 == 0o120000):
                raise UpdateError("Artifact has an unsafe path, symlink or duplicate file.")
            names.add(item.filename.lower())
            with source.open(item) as stream, (directory / item.filename).open("xb") as output:
                while chunk := stream.read(1024 * 1024):
                    output.write(chunk)


def download_artifact(run, kind, destination):
    artifacts = api(f"/repos/{REPOSITORY}/actions/runs/{run['id']}/artifacts?per_page=100")
    if artifacts.get("total_count", 0) > 100:
        raise UpdateError("Too many source artifacts.")
    name = (("no-stories-windows-x64-production-" if kind == "packages" else "fork-update-verifier-")
            + str(run["run_number"]))
    matches = [item for item in artifacts.get("artifacts", []) if item.get("name") == name]
    if len(matches) != 1 or matches[0].get("expired"):
        raise UpdateError("The exact source artifact is absent or expired.")
    artifact = matches[0]
    expected = artifact.get("digest", "")
    if (type(artifact.get("id")) is not int or artifact["id"] <= 0
            or not re.fullmatch(r"sha256:[0-9a-f]{64}", expected)
            or type(artifact.get("size_in_bytes")) is not int
            or not 0 < artifact["size_in_bytes"] <= MAX_ARCHIVE):
        raise UpdateError("Source artifact digest or size is invalid.")
    archive = Path(str(destination) + ".zip")
    opener = urllib.request.build_opener(ArtifactRedirect())
    digest, size = hashlib.sha256(), 0
    try:
        with opener.open(request(f"/repos/{REPOSITORY}/actions/artifacts/{artifact['id']}/zip"), timeout=45) as source:
            with archive.open("xb") as output:
                while chunk := source.read(1024 * 1024):
                    size += len(chunk)
                    if size > MAX_ARCHIVE:
                        raise UpdateError("Artifact download exceeded its size limit.")
                    digest.update(chunk)
                    output.write(chunk)
    except (urllib.error.URLError, TimeoutError):
        raise UpdateError("Artifact download could not finish; signed URLs were not logged.") from None
    if digest.hexdigest() != expected.removeprefix("sha256:"):
        raise UpdateError("Downloaded artifact digest differs from GitHub's digest.")
    unpack_artifact(archive, destination)
    archive.unlink()
    return artifact


def emit_outputs(values):
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a", encoding="utf-8") as output:
            for key, value in values.items():
                if not re.fullmatch(r"[A-Za-z0-9_.:/-]+", str(value)):
                    raise UpdateError("Unsafe workflow output.")
                output.write(f"{key}={value}\n")


def prepare(args):
    run = source_run(args.run, args.commit)
    root = Path(__file__).resolve().parents[3]
    if subprocess.run(["git", "merge-base", "--is-ancestor", args.commit, "HEAD"], cwd=root).returncode:
        raise UpdateError("Production source is not in the protected release history.")
    artifact = download_artifact(run, "packages", Path("source-packages"))
    key = os.environ.get("TDESKTOP_UPDATE_SIGNING_KEY", "").encode()
    if not key:
        raise UpdateError("The update signing secret is not configured.")
    first = counter_from_env({"GITHUB_RUN_NUMBER": str(run["run_number"]),
                              "GITHUB_RUN_ATTEMPT": str(run.get("run_attempt", 1))})
    # Reject an authenticated but malformed build before signing or writing a feed.
    from fork_update_tools import select_build
    selected, _, _ = select_build(Path("source-packages"), args.commit, args.build)
    if selected not in (first, first + 1):
        raise UpdateError("Fork counter does not belong to this production run attempt.")
    release = sign_release(Path("source-packages"), args.output,
                           root / "Telegram/Resources/no-stories/update", args.commit, key, selected)
    report = dict(source_run=run["id"], source_sha=args.commit, source_artifact=artifact["id"],
                  artifact_sha256=artifact["digest"], release=release)
    (args.output / "signing-report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    checksum_file(args.output)
    emit_outputs(dict(source_run=run["id"], source_sha=args.commit, tag=release["tag"], build=selected))
    print(json.dumps(dict(source_run=run["id"], source_sha=args.commit,
                          fork_build=selected, tag=release["tag"], artifact_digest_verified=True)))


def verifier(args):
    run = source_run(args.run, args.commit)
    artifact = download_artifact(run, "verifier", args.output)
    files = list(args.output.iterdir())
    if not any(p.name == "test_fork_update.exe" for p in files) or any(p.suffix.lower() not in (".exe", ".dll") for p in files):
        raise UpdateError("Native verifier artifact has unexpected files.")
    print(json.dumps(dict(verifier_artifact=artifact["id"], artifact_digest_verified=True)))


def require_native_job():
    current = os.environ.get("GITHUB_RUN_ID", "")
    head = os.environ.get("GITHUB_SHA", "")
    if not re.fullmatch(r"[1-9][0-9]*", current) or not re.fullmatch(r"[0-9a-f]{40}", head):
        raise UpdateError("Publication requires its verified Actions run.")
    run = api(f"/repos/{REPOSITORY}/actions/runs/{current}")
    if (run.get("head_sha") != head or run.get("head_branch") != "codex/no-stories"
            or run.get("event") != "workflow_dispatch"
            or run.get("path") != ".github/workflows/publish-fork-update.yml"):
        raise UpdateError("Publication workflow identity did not match.")
    jobs = api(f"/repos/{REPOSITORY}/actions/runs/{current}/jobs?filter=latest&per_page=100")
    checked = [item for item in jobs.get("jobs", []) if item.get("name") == "verify-windows"]
    if (jobs.get("total_count", 0) > 100 or len(checked) != 1
            or checked[0].get("conclusion") != "success"
            or checked[0].get("head_sha") != head):
        raise UpdateError("Exact-run native Windows acceptance has not succeeded.")


def publish(args):
    require_native_job()
    verify_artifact_checksums(args.directory)
    report = json.loads((args.directory / "signing-report.json").read_text())
    if report.get("source_sha") != args.commit or str(report.get("source_run")) != str(args.run):
        raise UpdateError("Signed release report does not match the checked source.")
    source_run(args.run, args.commit)
    release = report["release"]
    tag = release.get("tag", "")
    version = release.get("version", "")
    build = release.get("build")
    if type(build) is not int or tag != f"fork-v{version}-b{build}":
        raise UpdateError("Bad signed release tag.")
    base = version_base(version)
    reference = api(f"/repos/{REPOSITORY}/git/ref/tags/{tag}", missing_ok=True)
    if reference:
        target = reference.get("object", {})
        for _ in range(3):
            if target.get("type") != "tag":
                break
            sha = target.get("sha", "")
            if not re.fullmatch(r"[0-9a-f]{40}", sha):
                raise UpdateError("Invalid annotated release tag.")
            target = api(f"/repos/{REPOSITORY}/git/tags/{sha}").get("object", {})
        if target.get("type") != "commit" or target.get("sha") != args.commit:
            raise UpdateError("Existing release tag points to another commit; it was not changed.")
    latest = api(f"/repos/{REPOSITORY}/releases/latest", missing_ok=True)
    if args.mode == "publish" and latest and latest.get("tag_name") != tag:
        match = re.fullmatch(r"fork-v([0-9]+\.[0-9]+\.[0-9]+)-b([0-9]+)", latest.get("tag_name", ""))
        if not match or (version_base(match[1]), int(match[2])) >= (base, build):
            raise UpdateError("Publication would replace an unknown or newer latest release.")
    existing = api(f"/repos/{REPOSITORY}/releases/tags/{tag}", missing_ok=True)
    if existing and not existing.get("draft"):
        expected = {p.name: "sha256:" + sha256(p) for p in args.directory.iterdir() if p.is_file()}
        actual = {p["name"]: p.get("digest") for p in existing.get("assets", [])}
        if actual == expected:
            print(json.dumps(dict(tag=tag, already_published=True, mutated=False)))
            return
        raise UpdateError("Published release is immutable; no assets were changed.")
    if existing and existing.get("target_commitish") != args.commit:
        raise UpdateError("Draft release belongs to another source commit.")
    notes = Path("release-notes.txt")
    notes.write_text(
        f"Personal Windows x64 fork, Telegram {version}, fork build {build}.\n\n"
        "This build enables signed in-app updates from this repository. "
        "Downloads happen in the background; installation starts when you click Update and restart. "
        "TelegramForcePortable and local settings are preserved.\n\n"
        f"[Features and current changes](https://github.com/{REPOSITORY}/blob/{args.commit}/README.md)\n\n"
        f"[Exact source](https://github.com/{REPOSITORY}/tree/{args.commit})\n\n"
        "Update feed, package signature, Windows x64 payload and executable hashes passed the native verifier. "
        "Windows executables and the installer remain unsigned by Authenticode. "
        "The first bootstrap installation is manual.\n", encoding="utf-8")
    if not existing:
        subprocess.run(["gh", "release", "create", tag, "--repo", REPOSITORY, "--draft", "--target", args.commit,
                        "--title", f"Telegram No Stories {version} build {build}", "--notes-file", str(notes)], check=True)
    files = [str(p) for p in sorted(args.directory.iterdir()) if p.is_file()]
    subprocess.run(["gh", "release", "upload", tag, "--repo", REPOSITORY, *files, "--clobber"], check=True)
    if args.mode == "publish":
        subprocess.run(["gh", "release", "edit", tag, "--repo", REPOSITORY, "--draft=false", "--latest"], check=True)
    print(json.dumps(dict(tag=tag, published=args.mode == "publish",
                          url=f"https://github.com/{REPOSITORY}/releases/tag/{tag}")))


def main():
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("prepare", "verifier", "publish"):
        command = commands.add_parser(name)
        command.add_argument("--run", required=True)
        command.add_argument("--commit", required=True)
        if name == "prepare":
            command.add_argument("--build", type=int)
            command.add_argument("--output", type=Path, default=Path("signed-release"))
        elif name == "verifier":
            command.add_argument("--output", type=Path, default=Path("native-verifier"))
        else:
            command.add_argument("--directory", type=Path, default=Path("signed-release"))
            command.add_argument("--mode", choices=("stage", "publish"), default="stage")
    args = parser.parse_args()
    try:
        {"prepare": prepare, "verifier": verifier, "publish": publish}[args.command](args)
    except (UpdateError, OSError, ValueError, zipfile.BadZipFile, subprocess.CalledProcessError) as error:
        # No raw API responses, signed URLs, headers, environment or key data.
        print("Fork update publication failed: " + (str(error) if isinstance(error, UpdateError)
                                                   else type(error).__name__), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
