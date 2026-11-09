import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import urllib.request
import urllib.error
import zipfile

import publish_update as publish
from fork_update_tools import REPOSITORY, UpdateError


COMMIT = "a" * 40
TAG = "fork-v7.4.1-b21011"


def release_metadata(identifier=123, tag=TAG, draft=True, **values):
    return dict(id=identifier, tag_name=tag, draft=draft,
                target_commitish=COMMIT, assets=[], **values)


class TransportTests(unittest.TestCase):
    def test_only_http_404_is_treated_as_missing(self):
        path = f"/repos/{REPOSITORY}/releases/tags/{TAG}"
        with patch.object(publish, "request", return_value=object()):
            for status in (401, 403, 404, 429, 500):
                error = urllib.error.HTTPError("https://api.github.com", status, "synthetic", {}, None)
                with self.subTest(status=status), patch.object(urllib.request.OpenerDirector, "open", side_effect=error):
                    if status == 404:
                        self.assertIsNone(publish.api(path, missing_ok=True))
                    else:
                        with self.assertRaisesRegex(UpdateError, f"HTTP {status}"):
                            publish.api(path, missing_ok=True)

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


class ReleaseLookupTests(unittest.TestCase):
    def page(self, start=1):
        return [release_metadata(i, f"other-{i}", draft=False)
                for i in range(start, start + publish.RELEASE_PAGE_SIZE)]

    def test_public_tag_uses_exact_endpoint_without_listing(self):
        existing = release_metadata(draft=False)
        with patch.object(publish, "api", return_value=existing) as api:
            self.assertEqual(publish.find_release(TAG), existing)
            api.assert_called_once_with(f"/repos/{REPOSITORY}/releases/tags/{TAG}", missing_ok=True)

    def test_draft_missing_from_tag_endpoint_is_found_in_list(self):
        draft = release_metadata()
        with patch.object(publish, "api", side_effect=[None, [draft]]) as api:
            self.assertEqual(publish.find_release(TAG), draft)
            self.assertEqual(api.call_args_list[1].args,
                             (f"/repos/{REPOSITORY}/releases?per_page=100&page=1",))

    def test_draft_on_later_page_and_absent_release(self):
        draft = release_metadata(identifier=500)
        with patch.object(publish, "api", side_effect=[None, self.page(), [draft]]) as api:
            self.assertEqual(publish.find_release(TAG), draft)
            self.assertEqual(api.call_args_list[-1].args,
                             (f"/repos/{REPOSITORY}/releases?per_page=100&page=2",))
        with patch.object(publish, "api", side_effect=[None, []]):
            self.assertIsNone(publish.find_release(TAG))

    def test_ambiguous_drafts_on_same_or_later_page_fail_closed(self):
        first, second = release_metadata(), release_metadata(identifier=500)
        for pages in ([[first, second]], [[first] + self.page()[1:], [second]]):
            with self.subTest(pages=len(pages)), patch.object(publish, "api", side_effect=[None, *pages]):
                with self.assertRaisesRegex(UpdateError, "ambiguous"):
                    publish.find_release(TAG)

    def test_full_history_bound_never_implies_absence_or_unique_match(self):
        for found in (False, True):
            pages = [self.page(i * 100 + 1) for i in range(publish.MAX_RELEASE_PAGES)]
            if found:
                pages[0][0] = release_metadata(identifier=5000)
            with self.subTest(found=found), patch.object(publish, "api", side_effect=[None, *pages]) as api:
                with self.assertRaisesRegex(UpdateError, "bounded history"):
                    publish.find_release(TAG)
                self.assertEqual(api.call_count, 1 + publish.MAX_RELEASE_PAGES)

    def test_malformed_tag_or_list_metadata_is_rejected(self):
        for response in ({}, [], release_metadata(tag="other"),
                         dict(release_metadata(), draft="false"), dict(release_metadata(), id=True)):
            with self.subTest(response=response), patch.object(publish, "api", return_value=response):
                with self.assertRaises(UpdateError):
                    publish.find_release(TAG)
        for response in (None, {}, [None], [dict(release_metadata(), tag_name=42)],
                         [dict(release_metadata(), id=0)], self.page() + [release_metadata()]):
            with self.subTest(response_type=type(response).__name__), patch.object(publish, "api", side_effect=[None, response]):
                with self.assertRaises(UpdateError):
                    publish.find_release(TAG)

    def test_auth_or_list_failure_cannot_become_a_create_decision(self):
        for responses, calls in (([UpdateError("GitHub API returned HTTP 403.")], 1),
                                 ([None, UpdateError("GitHub API returned HTTP 500.")], 2)):
            with self.subTest(calls=calls), patch.object(publish, "api", side_effect=responses) as api:
                with self.assertRaises(UpdateError):
                    publish.find_release(TAG)
                self.assertEqual(api.call_count, calls)


class PublicationLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.stack.enter_context(contextlib.chdir(root))
        self.directory = root / "signed-release"
        self.directory.mkdir()
        (self.directory / "synthetic-update").write_bytes(b"synthetic signed artifact")
        report = dict(source_sha=COMMIT, source_run=456,
                      release=dict(tag=TAG, version="7.4.1", build=21011))
        (self.directory / "signing-report.json").write_text(json.dumps(report), encoding="utf-8")
        publish.checksum_file(self.directory)
        self.args = SimpleNamespace(directory=self.directory, commit=COMMIT, run="456", mode="stage")
        self.guard = self.stack.enter_context(patch.object(publish, "require_native_job"))
        self.source = self.stack.enter_context(patch.object(publish, "source_run"))
        self.api = self.stack.enter_context(patch.object(publish, "api", side_effect=self.answer))
        self.commands = self.stack.enter_context(patch.object(publish.subprocess, "run", side_effect=self.command))
        self.stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
        self.existing = None
        self.latest = None
        self.created = 0

    def assets(self):
        return [dict(name=p.name, digest="sha256:" + publish.sha256(p))
                for p in sorted(self.directory.iterdir()) if p.is_file()]

    def answer(self, path, missing_ok=False):
        if path == f"/repos/{REPOSITORY}/git/ref/tags/{TAG}":
            return dict(object=dict(type="commit", sha=COMMIT))
        if path == f"/repos/{REPOSITORY}/releases/latest":
            return self.latest
        if path == f"/repos/{REPOSITORY}/releases/tags/{TAG}":
            # Reproduce GitHub's actual draft/tag endpoint behavior.
            return self.existing if self.existing and not self.existing["draft"] else None
        if path == f"/repos/{REPOSITORY}/releases?per_page=100&page=1":
            return [self.existing] if self.existing else []
        raise AssertionError("Unexpected API path: " + path)

    def command(self, args, **options):
        if args[:3] == ["gh", "release", "create"]:
            self.assertIsNone(self.existing, "must not recreate an existing draft")
            self.created += 1
            self.existing = release_metadata(identifier=700)
        elif args[:3] == ["gh", "release", "upload"]:
            self.assertTrue(self.existing["draft"])
            self.existing["assets"] = self.assets()
        elif args[:3] == ["gh", "release", "edit"]:
            self.assertIn("--draft=false", args)
            self.assertIn("--latest", args)
            self.existing["draft"] = False
            self.latest = self.existing
        else:
            raise AssertionError("Unexpected command")

    def test_stage_then_publish_reuses_same_draft_and_retry_is_read_only(self):
        publish.publish(self.args)
        identifier = self.existing["id"]
        self.assertTrue(self.existing["draft"])
        self.assertEqual(self.created, 1)
        self.args.mode = "publish"
        publish.publish(self.args)
        self.assertEqual(self.existing["id"], identifier)
        self.assertEqual(self.created, 1)
        self.assertFalse(self.existing["draft"])
        self.assertEqual([call.args[0][2] for call in self.commands.call_args_list],
                         ["create", "upload", "upload", "edit"])
        self.commands.reset_mock()
        publish.publish(self.args)
        self.commands.assert_not_called()

    def test_draft_with_another_source_is_not_mutated(self):
        self.existing = dict(release_metadata(), target_commitish="b" * 40)
        self.args.mode = "publish"
        with self.assertRaisesRegex(UpdateError, "another source"):
            publish.publish(self.args)
        self.commands.assert_not_called()

    def test_published_exact_assets_are_idempotent_and_different_assets_are_immutable(self):
        self.existing = dict(release_metadata(draft=False), assets=self.assets())
        self.latest = self.existing
        for mode in ("stage", "publish"):
            self.args.mode = mode
            publish.publish(self.args)
        self.commands.assert_not_called()
        self.existing["assets"][0]["digest"] = "sha256:" + "0" * 64
        with self.assertRaisesRegex(UpdateError, "immutable"):
            publish.publish(self.args)
        self.commands.assert_not_called()

    def test_native_failure_blocks_before_lookup_or_mutation(self):
        self.guard.side_effect = UpdateError("Exact-run native Windows acceptance has not succeeded.")
        with self.assertRaisesRegex(UpdateError, "native Windows acceptance"):
            publish.publish(self.args)
        self.api.assert_not_called()
        self.source.assert_not_called()
        self.commands.assert_not_called()

    def test_invalid_checksums_block_before_lookup_or_mutation(self):
        (self.directory / "synthetic-update").write_bytes(b"changed")
        with self.assertRaises(UpdateError):
            publish.publish(self.args)
        self.api.assert_not_called()
        self.source.assert_not_called()
        self.commands.assert_not_called()

    def test_unknown_or_newer_latest_release_is_not_replaced(self):
        self.args.mode = "publish"
        for tag in ("unknown", "fork-v7.4.1-b21012", "fork-v7.4.2-b1"):
            self.latest = release_metadata(tag=tag, draft=False)
            with self.subTest(tag=tag), self.assertRaisesRegex(UpdateError, "newer latest"):
                publish.publish(self.args)
        self.commands.assert_not_called()


if __name__ == "__main__":
    unittest.main()
