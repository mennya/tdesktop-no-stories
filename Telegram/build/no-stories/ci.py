"""Plan trusted Windows validation and promote an exactly checked commit."""

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
from urllib.parse import urlencode


REPOSITORY = "mennya/tdesktop-no-stories"
RELEASE_BRANCH = "codex/no-stories"
CANDIDATE_PREFIX = "codex/candidate/"
WORKFLOW = "no-stories-windows.yml"
WORKFLOW_PATH = ".github/workflows/" + WORKFLOW
CHECKS = {"regression-models", "Windows validation"}


class ValidationError(RuntimeError):
    pass


def commit_id(value):
    if not re.fullmatch(r"[0-9a-f]{40}", value or "") or value == "0" * 40:
        raise ValidationError("Expected a complete nonzero commit SHA.")
    return value


def pipeline(event_name, ref):
    if event_name not in ("push", "workflow_dispatch"):
        raise ValidationError("Only repository pushes and manual dispatch are supported.")
    if ref == "refs/heads/" + RELEASE_BRANCH:
        return "production"
    if ref.startswith("refs/heads/" + CANDIDATE_PREFIX):
        return "validation"
    raise ValidationError("Use the release branch or a codex/candidate/ task branch.")


def git(root, *arguments):
    result = subprocess.run(
        ["git", "-C", str(root), *arguments],
        capture_output=True, text=True, check=False,
    )
    if result.returncode:
        raise ValidationError("Git operation failed: " + arguments[0] + ".")
    return result.stdout.strip()


def api(endpoint):
    result = subprocess.run(
        ["gh", "api", "--hostname", "github.com", endpoint],
        capture_output=True, text=True, check=False, timeout=30,
    )
    if result.returncode:
        status = re.search(r"HTTP (\d{3})", result.stderr)
        suffix = " (HTTP " + status.group(1) + ")" if status else ""
        raise ValidationError("GitHub validation lookup failed" + suffix + ".")
    try:
        return json.loads(result.stdout)
    except ValueError:
        raise ValidationError("GitHub returned an invalid validation response.") from None


def candidate_run(run, head, workflow_id):
    return (
        run.get("head_sha") == head
        and run.get("workflow_id") == workflow_id
        and run.get("path", "").split("@", 1)[0] == WORKFLOW_PATH
        and (run.get("head_repository") or {}).get("full_name", "").lower()
        == REPOSITORY.lower()
        and run.get("head_branch", "").startswith(CANDIDATE_PREFIX)
        and run.get("event") in ("push", "workflow_dispatch")
    )


def checked_run(runs, jobs, head, workflow_id):
    eligible = [run for run in runs if candidate_run(run, head, workflow_id)]
    if not eligible:
        raise ValidationError("This commit has no trusted candidate validation run.")
    latest = max(eligible, key=lambda run: run["id"])
    if latest.get("status") != "completed" or latest.get("conclusion") != "success":
        raise ValidationError("The latest candidate validation has not succeeded.")
    actual = {job.get("name"): job for job in jobs(latest["id"])}
    for name in CHECKS:
        job = actual.get(name, {})
        if job.get("status") != "completed" or job.get("conclusion") != "success":
            raise ValidationError("Required validation job did not succeed: " + name)
        if job.get("head_sha") != head:
            raise ValidationError("Validation job belongs to another commit.")
    return latest


def require_validation(head, request=api):
    commit_id(head)
    workflow = request("repos/" + REPOSITORY + "/actions/workflows/" + WORKFLOW)
    if workflow.get("path") != WORKFLOW_PATH:
        raise ValidationError("Unexpected validation workflow identity.")
    query = urlencode({"head_sha": head, "per_page": 100})
    result = request(
        "repos/" + REPOSITORY + "/actions/workflows/" + WORKFLOW + "/runs?" + query
    )

    def jobs(run_id):
        result = request(
            "repos/" + REPOSITORY + "/actions/runs/" + str(run_id)
            + "/jobs?filter=latest&per_page=100"
        )
        if result.get("total_count", 0) > 100:
            raise ValidationError("Validation job list is incomplete.")
        return result.get("jobs", [])

    return checked_run(result.get("workflow_runs", []), jobs, head, workflow["id"])


def plan(root):
    if os.environ.get("GITHUB_REPOSITORY") != REPOSITORY:
        raise ValidationError("This workflow is scoped to the personal fork.")
    head = commit_id(os.environ.get("GITHUB_SHA", ""))
    if git(root, "rev-parse", "HEAD") != head:
        raise ValidationError("Checkout does not match the requested commit.")
    mode = pipeline(os.environ.get("GITHUB_EVENT_NAME"), os.environ.get("GITHUB_REF", ""))
    if mode == "validation":
        base = commit_id(git(root, "rev-parse", "origin/" + RELEASE_BRANCH))
        if base == head or git(root, "merge-base", base, head) != base:
            raise ValidationError("Rebase the candidate onto the current release branch.")
        run_id = ""
    else:
        base = head
        run_id = str(require_validation(head)["id"])
    outputs = {"pipeline": mode, "base_commit": base, "validation_run_id": run_id}
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
        for key, value in outputs.items():
            output.write(key + "=" + value + "\n")
    print(json.dumps({"commit": head, **outputs}))


def promote(root, head, expected_base):
    commit_id(head)
    commit_id(expected_base)
    if git(root, "rev-parse", "HEAD") != head or git(root, "status", "--porcelain"):
        raise ValidationError("Promote the exact clean candidate checkout.")
    branch = git(root, "branch", "--show-current")
    if not branch.startswith(CANDIDATE_PREFIX):
        raise ValidationError("Promotion requires a candidate task branch.")
    run = require_validation(head)
    if run["head_branch"] != branch:
        raise ValidationError("Validation belongs to another candidate branch.")
    remote = git(root, "ls-remote", "origin", "refs/heads/" + RELEASE_BRANCH).split()
    if len(remote) != 2 or remote[0] != expected_base:
        raise ValidationError("The release branch moved; rebase and validate again.")
    if git(root, "merge-base", expected_base, head) != expected_base:
        raise ValidationError("Candidate does not extend the expected release commit.")
    git(root, "push", "origin", head + ":refs/heads/" + RELEASE_BRANCH)
    print(json.dumps({"promoted_commit": head, "validation_run_id": run["id"]}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("plan")
    promotion = sub.add_parser("promote")
    promotion.add_argument("--commit", required=True)
    promotion.add_argument("--expected-base", required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[3]
    try:
        if args.command == "plan":
            plan(root)
        else:
            promote(root, args.commit, args.expected_base)
    except (ValidationError, OSError, subprocess.TimeoutExpired) as error:
        if isinstance(error, ValidationError):
            parser.exit(1, str(error) + "\n")
        parser.exit(1, "Validation helper could not finish its local or API operation.\n")


if __name__ == "__main__":
    main()
