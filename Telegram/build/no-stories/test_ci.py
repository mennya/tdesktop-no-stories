"""Check publication binding, failed checks, and branch/base races offline."""

import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import ci


BASE = "1" * 40
HEAD = "2" * 40
WORKFLOW_ID = 17


def run_record(run_id=20):
    return {
        "id": run_id,
        "workflow_id": WORKFLOW_ID,
        "path": ci.WORKFLOW_PATH,
        "head_sha": HEAD,
        "head_branch": ci.CANDIDATE_PREFIX + "test",
        "head_repository": {"full_name": ci.REPOSITORY},
        "event": "push",
        "status": "completed",
        "conclusion": "success",
    }


def passed_jobs(_run_id):
    return [{"name": name, "status": "completed", "conclusion": "success", "head_sha": HEAD} for name in ci.CHECKS]


class ValidationTests(unittest.TestCase):
    def test_exact_candidate_passes(self):
        result = ci.checked_run([run_record()], passed_jobs, HEAD, WORKFLOW_ID)
        self.assertEqual(result["id"], 20)

    def test_other_commit_repository_workflow_and_branch_rejected(self):
        cases = (
            {"head_sha": BASE}, {"workflow_id": 99}, {"path": ".github/workflows/other.yml"},
            {"head_branch": ci.RELEASE_BRANCH}, {"head_repository": {"full_name": "other/fork"}},
            {"head_repository": None}, {"event": "pull_request"},
        )
        for change in cases:
            with self.subTest(change=change), self.assertRaises(ci.ValidationError):
                ci.checked_run([{**run_record(), **change}], passed_jobs, HEAD, WORKFLOW_ID)

    def test_latest_failed_or_running_attempt_blocks_older_success(self):
        for change in ({"conclusion": "failure"}, {"status": "in_progress", "conclusion": None}, {"conclusion": "cancelled"}):
            with self.subTest(change=change), self.assertRaises(ci.ValidationError):
                ci.checked_run([run_record(20), {**run_record(21), **change}], passed_jobs, HEAD, WORKFLOW_ID)

    def test_unrelated_newer_run_is_not_the_candidate(self):
        result = ci.checked_run([run_record(20), {**run_record(21), "head_branch": ci.RELEASE_BRANCH}], passed_jobs, HEAD, WORKFLOW_ID)
        self.assertEqual(result["id"], 20)

    def test_skipped_missing_or_wrong_commit_jobs_are_rejected(self):
        for field, value in (("conclusion", "skipped"), ("status", "queued"), ("head_sha", BASE)):
            jobs = passed_jobs(20)
            jobs[0][field] = value
            with self.subTest(field=field), self.assertRaises(ci.ValidationError):
                ci.checked_run([run_record()], lambda _: jobs, HEAD, WORKFLOW_ID)
        with self.assertRaises(ci.ValidationError):
            ci.checked_run([run_record()], lambda _: [], HEAD, WORKFLOW_ID)

    def test_api_requires_real_workflow_and_complete_job_list(self):
        def request(endpoint):
            if "/runs?" in endpoint:
                return {"workflow_runs": [run_record()]}
            if "/jobs?" in endpoint:
                return {"total_count": 101, "jobs": passed_jobs(20)}
            return {"id": WORKFLOW_ID, "path": ci.WORKFLOW_PATH}
        with self.assertRaisesRegex(ci.ValidationError, "incomplete"):
            ci.require_validation(HEAD, request)
        with self.assertRaises(ci.ValidationError):
            ci.require_validation(HEAD, lambda _: {"id": WORKFLOW_ID, "path": "other.yml"})

    def test_invalid_commit_is_rejected(self):
        for value in ("HEAD", "--help", "0" * 40, HEAD + "\n", "f" * 39):
            with self.subTest(value=value), self.assertRaises(ci.ValidationError):
                ci.commit_id(value)

    def test_only_trusted_push_and_dispatch_modes(self):
        self.assertEqual(ci.pipeline("push", "refs/heads/" + ci.RELEASE_BRANCH), "production")
        self.assertEqual(ci.pipeline("workflow_dispatch", "refs/heads/" + ci.CANDIDATE_PREFIX + "test"), "validation")
        for event, ref in (("pull_request", "refs/heads/" + ci.RELEASE_BRANCH), ("push", "refs/tags/v1"), ("push", "refs/heads/other")):
            with self.subTest(event=event, ref=ref), self.assertRaises(ci.ValidationError):
                ci.pipeline(event, ref)


class PromotionTests(unittest.TestCase):
    def test_clean_checked_commit_is_pushed_without_force(self):
        calls = []
        responses = {
            ("rev-parse", "HEAD"): HEAD,
            ("status", "--porcelain"): "",
            ("branch", "--show-current"): ci.CANDIDATE_PREFIX + "test",
            ("ls-remote", "origin", "refs/heads/" + ci.RELEASE_BRANCH): BASE + "\trefs/heads/" + ci.RELEASE_BRANCH,
            ("merge-base", BASE, HEAD): BASE,
        }
        def git(_root, *args):
            calls.append(args)
            return responses.get(args, "")
        with patch.object(ci, "git", git), patch.object(ci, "require_validation", return_value=run_record()):
            ci.promote(Path("."), HEAD, BASE)
        self.assertEqual(calls[-1], ("push", "origin", HEAD + ":refs/heads/" + ci.RELEASE_BRANCH))

    def test_dirty_checkout_or_moved_release_is_never_pushed(self):
        for dirty in (True, False):
            calls = []
            def git(_root, *args):
                calls.append(args)
                if args == ("rev-parse", "HEAD"):
                    return HEAD
                if args == ("status", "--porcelain"):
                    return " M file.cpp" if dirty else ""
                if args == ("branch", "--show-current"):
                    return ci.CANDIDATE_PREFIX + "test"
                if args[0] == "ls-remote":
                    return "3" * 40 + "\trefs/heads/" + ci.RELEASE_BRANCH
                raise AssertionError(args)
            with patch.object(ci, "git", git), patch.object(ci, "require_validation", return_value=run_record()), self.assertRaises(ci.ValidationError):
                ci.promote(Path("."), HEAD, BASE)
            self.assertFalse(any(args[0] == "push" for args in calls))


class PlanTests(unittest.TestCase):
    def test_real_git_candidate_binds_the_release_baseline(self):
        with tempfile.TemporaryDirectory(prefix="telegram-ci-plan-") as directory:
            root = Path(directory)
            def git(*args):
                return subprocess.check_output(["git", "-C", str(root), *args], text=True, stderr=subprocess.DEVNULL).strip()
            git("init", "-q")
            git("config", "user.name", "Fixture")
            git("config", "user.email", "fixture@localhost")
            (root / "file.cpp").write_text("int value = 1;\n")
            git("add", "file.cpp")
            git("commit", "-qm", "Baseline")
            base = git("rev-parse", "HEAD")
            git("update-ref", "refs/remotes/origin/" + ci.RELEASE_BRANCH, base)
            git("checkout", "-qb", ci.CANDIDATE_PREFIX + "test")
            (root / "file.cpp").write_text("int value = 2;\n")
            git("commit", "-qam", "Candidate")
            head = git("rev-parse", "HEAD")
            output = root / "outputs"
            env = {"GITHUB_REPOSITORY": ci.REPOSITORY, "GITHUB_SHA": head, "GITHUB_EVENT_NAME": "push", "GITHUB_REF": "refs/heads/" + ci.CANDIDATE_PREFIX + "test", "GITHUB_OUTPUT": str(output)}
            with patch.dict(os.environ, env, clear=True), patch.object(ci, "require_validation", side_effect=AssertionError("Candidate must not query production validation")):
                ci.plan(root)
            self.assertIn("base_commit=" + base, output.read_text())
            self.assertIn("pipeline=validation", output.read_text())
            with patch.dict(os.environ, {**env, "GITHUB_REPOSITORY": "other/fork"}, clear=True), self.assertRaises(ci.ValidationError):
                ci.plan(root)


if __name__ == "__main__":
    unittest.main()
