import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import urllib.request
import zipfile

import publish_update as publish
from fork_update_tools import REPOSITORY, UpdateError


COMMIT = "a" * 40


class TransportTests(unittest.TestCase):
    def test_token_does_not_follow_artifact_redirect(self):
        source = urllib.request.Request("https://api.github.com/repos/" + REPOSITORY + "/actions/artifacts/1/zip",
                                        headers={"Authorization": "Bearer synthetic-test-token"})
        redirected = publish.ArtifactRedirect().redirect_request(source, None, 302, "Found", {},
                                "https://results.blob.core.windows.net/artifact?sig=synthetic")
        self.assertIsNone(redirected.get_header("Authorization"))
        self.assertNotIn("Authorization", redirected.unredirected_hdrs)

    def test_redirect_cannot_downgrade_or_leave_download_hosts(self):
        source = urllib.request.Request("https://api.github.com/test")
        for url in ("http://results.blob.core.windows.net/file", "https://attacker.invalid/file",
                    "https://api.github.com.attacker.invalid/file", "https://user:pass@github.com/file"):
            with self.subTest(url=url), self.assertRaises(UpdateError):
                publish.ArtifactRedirect().redirect_request(source, None, 302, "Found", {}, url)

    def test_artifact_paths_are_confined_and_windows_safe(self):
        for name in ("../outside", "dir/file", "dir\\file", "..", ".env", "NUL.dll", "CON", "file."):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                with zipfile.ZipFile(root / "artifact.zip", "w") as archive:
                    archive.writestr(name, b"synthetic")
                with self.assertRaises(UpdateError):
                    publish.unpack_artifact(root / "artifact.zip", root / "extract")
                self.assertFalse((root / "outside").exists())

    def test_case_collisions_and_symlinks_are_refused(self):
        for mode in ("duplicate", "symlink"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                with zipfile.ZipFile(root / "artifact.zip", "w") as archive:
                    if mode == "duplicate":
                        archive.writestr("test.exe", b"one")
                        archive.writestr("TEST.exe", b"two")
                    else:
                        item = zipfile.ZipInfo("test.exe")
                        item.create_system = 3
                        item.external_attr = 0o120777 << 16
                        archive.writestr(item, b"target")
                with self.assertRaises(UpdateError):
                    publish.unpack_artifact(root / "artifact.zip", root / "extract")


class AdmissionTests(unittest.TestCase):
    def source(self):
        return dict(id=123, head_sha=COMMIT, head_branch="codex/no-stories", event="push",
                    status="completed", conclusion="success", repository={"full_name": REPOSITORY},
                    path=".github/workflows/no-stories-windows.yml")

    def test_only_completed_exact_protected_production_run_is_admitted(self):
        with patch.object(publish, "api", return_value=self.source()):
            self.assertEqual(publish.source_run("123", COMMIT)["id"], 123)
        for key, value in (("id", 124), ("head_sha", "b" * 40),
                           ("head_branch", "codex/candidate/example"), ("event", "pull_request_target"),
                           ("status", "in_progress"), ("conclusion", "failure"),
                           ("path", ".github/workflows/other.yml"),
                           ("repository", {"full_name": "other/repo"})):
            with self.subTest(key=key), patch.object(publish, "api", return_value=dict(self.source(), **{key: value})):
                with self.assertRaises(UpdateError):
                    publish.source_run("123", COMMIT)

    def test_user_input_cannot_become_an_api_path_or_workflow_output(self):
        for run, sha in (("123/../../other", COMMIT), ("123", "a" * 40 + "\nother=value")):
            with self.assertRaises(UpdateError):
                publish.source_run(run, sha)
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, {"GITHUB_OUTPUT": str(Path(temporary) / "output")}):
            with self.assertRaises(UpdateError):
                publish.emit_outputs({"source_sha": "a\nother=value"})

    def test_exact_native_job_must_succeed_before_publication(self):
        run = dict(head_sha=COMMIT, head_branch="codex/no-stories", event="workflow_dispatch",
                   path=".github/workflows/publish-fork-update.yml")
        job = dict(name="verify-windows", conclusion="success", head_sha=COMMIT)
        with patch.dict(os.environ, {"GITHUB_RUN_ID": "456", "GITHUB_SHA": COMMIT}):
            with patch.object(publish, "api", side_effect=[run, dict(jobs=[job], total_count=3)]):
                publish.require_native_job()
            for changed in (dict(job, conclusion="failure"), dict(job, head_sha="b" * 40)):
                with patch.object(publish, "api", side_effect=[run, dict(jobs=[changed], total_count=3)]):
                    with self.assertRaises(UpdateError):
                        publish.require_native_job()
            with patch.object(publish, "api", side_effect=[dict(run, head_branch="codex/candidate/other")]):
                with self.assertRaises(UpdateError):
                    publish.require_native_job()


if __name__ == "__main__":
    unittest.main()
