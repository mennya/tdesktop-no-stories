import copy
import json
import os
import unittest
from unittest.mock import patch

import release_watch as watch


CONFIG = {"schema": 1, "installed_tag": "v7.3.3", "model": "gpt-6-luna",
          "state_branch": "codex/release-watch-state", "max_model_calls": 6}
ENV = {"GITHUB_REPOSITORY": "example/tdesktop-no-stories", "GITHUB_TOKEN": "fixture-github",
       "OPENAI_API_KEY": "fixture-openai", "PUSHOVER_APP_TOKEN": "fixture-app", "PUSHOVER_USER_KEY": "fixture-user"}


def state():
    return {"schema": 1, "installed_tag": "v7.3.3", "reviewed": {}, "outbox": {}, "failures": {}}


def item(tag="v7.3.4", text="Fix important Windows login failure.", kind="release"):
    return {"id": kind + ":" + tag, "tag": tag, "text": text, "kind": kind,
            "url": "https://github.com/telegramdesktop/tdesktop/releases/tag/" + tag}


def answer(important=True):
    return {"important": important, "category": "login" if important else "minor",
            "summary_ru": "Исправлена ошибка входа." if important else "Изменён цвет значка.",
            "reason_ru": "Влияет на обычный вход." if important else "Косметика."}


class MemoryStore:
    def __init__(self):
        self.saved = []

    def save(self, value):
        self.saved.append(copy.deepcopy(value))


class FakeHttp:
    def __init__(self, json_responses=None, raw=b""):
        self.responses = list(json_responses or [])
        self.calls = []
        self.raw = raw

    def json(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        result = self.responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    def request(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self.raw, {}


class SourceTests(unittest.TestCase):
    def test_stable_version_filter(self):
        self.assertEqual(watch.version("v7.4"), (7, 4, 0))
        self.assertEqual(watch.version("v7.3.10"), (7, 3, 10))
        self.assertIsNone(watch.version("v7.4.0-beta"))

    def test_actual_changelog_markup(self):
        html = '<article class="entry" id="v7.3.3"><h2><a href="#v7.3.3"></a>7.3.3 <time>21.10.26</time></h2><ul><li>Fix &#x27;?&#x27; key.</li></ul></article>'
        self.assertIn("Fix '?' key.", watch.parse_changelog(html)["v7.3.3"])

    def test_changelog_fail_closed(self):
        for html in ("<html>Bad Gateway</html>", '<article class="entry" id="v7.3.3">unfinished'):
            with self.assertRaises(watch.WatchError):
                watch.parse_changelog(html)

    def test_no_duplicate_changelog_ids(self):
        with self.assertRaises(watch.WatchError):
            watch.parse_changelog('<article class="entry" id="v7.3.3"></article>' * 2)

    def test_release_pagination_reaches_installed_baseline(self):
        page = [{"tag_name": "v8.0.0-beta", "prerelease": True}] * 99
        page.append({"tag_name": "v8.0.1", "prerelease": False})
        http = FakeHttp([(page, {}), ([{"tag_name": "v7.3.3"}, {"tag_name": "v7.2.0"}], {})])
        releases = watch.fetch_releases(http, (7, 3, 3))
        self.assertEqual([r["tag_name"] for r in releases], ["v8.0.1", "v7.3.3"])
        self.assertIn("page=2", http.calls[1][0][1])
        self.assertNotIn("Authorization", http.calls[0][0][2])

    def test_missing_baseline_is_error(self):
        with self.assertRaisesRegex(watch.WatchError, "INSTALLED_RELEASE_NOT_FOUND"):
            watch.fetch_releases(FakeHttp([([], {})]), (7, 3, 3))

    def test_advisory_pagination_and_auth_boundary(self):
        next_url = watch.GITHUB + "/repos/telegramdesktop/tdesktop/security-advisories?after=cursor"
        http = FakeHttp([([{"ghsa_id": "a"}], {"Link": '<' + next_url + '>; rel="next"'}),
                         ([{"ghsa_id": "b"}], {})])
        self.assertEqual(len(watch.fetch_advisories(http)), 2)
        self.assertEqual(http.calls[1][0][1], next_url)
        self.assertNotIn("Authorization", http.calls[0][0][2])

    def test_advisory_failure_is_not_empty_success(self):
        with self.assertRaisesRegex(watch.WatchError, "GITHUB_ADVISORIES_HTTP_403"):
            watch.fetch_advisories(FakeHttp([watch.WatchError("GITHUB_ADVISORIES_HTTP_403")]))

    def test_collect_excludes_old_and_withdrawn_advisories(self):
        release = {"tag_name": "v7.3.3", "published_at": "2026-10-21T00:00:00Z", "body": "Baseline",
                   "html_url": "https://github.com/telegramdesktop/tdesktop/releases/tag/v7.3.3"}
        fresh = {"ghsa_id": "GHSA-abcd-1234-5678", "state": "published", "updated_at": "2026-10-24T00:00:00Z",
                 "html_url": "https://github.com/telegramdesktop/tdesktop/security/advisories/GHSA-abcd-1234-5678"}
        old = dict(fresh, ghsa_id="GHSA-old", updated_at="2026-10-20T00:00:00Z")
        withdrawn = dict(fresh, ghsa_id="GHSA-withdrawn", withdrawn_at="2026-10-24T01:00:00Z")
        http = FakeHttp([([release], {}), ([fresh, old, withdrawn], {})],
                        b'<article class="entry" id="v7.3.3">Baseline notes</article>')
        self.assertEqual([r["tag"] for r in watch.collect(http, CONFIG)], [fresh["ghsa_id"], "v7.3.3"])

    def test_partial_sources_keep_positive_security_evidence_first(self):
        release = {"tag_name": "v7.3.3", "published_at": "2026-10-21T00:00:00Z", "body": "Baseline",
                   "html_url": "https://github.com/telegramdesktop/tdesktop/releases/tag/v7.3.3"}
        security = dict(release, tag_name="v7.3.5", body="Fix CVE-2026-12345", html_url=release["html_url"].replace("3.3", "3.5"))
        cosmetic = dict(release, tag_name="v7.3.4", html_url=release["html_url"].replace("3.3", "3.4"))
        http = FakeHttp([([release, cosmetic, security], {}), watch.WatchError("GITHUB_ADVISORIES_HTTP_503")],
                        b'<article class="entry" id="v7.3.3">Baseline notes</article>')
        items = watch.collect(http, CONFIG)
        self.assertEqual(items[0]["tag"], "v7.3.5")
        self.assertFalse(items[0]["complete"])
        self.assertEqual(len(items.errors), 3)


class ModelTests(unittest.TestCase):
    @patch.dict(os.environ, ENV)
    def test_structured_response_with_leading_reasoning_item(self):
        response = {"status": "completed", "output": [{"type": "reasoning"},
                    {"type": "message", "content": [{"type": "output_text", "text": json.dumps(answer())}]}]}
        http = FakeHttp([(response, {})])
        self.assertTrue(watch.classify(http, "public notes")["important"])
        payload = http.calls[0][0][3]
        self.assertEqual(payload["model"], "gpt-6-luna")
        self.assertFalse(payload["store"])
        self.assertEqual(payload["reasoning"], {"effort": "none"})
        self.assertEqual(payload["max_output_tokens"], 800)
        self.assertNotIn("tools", payload)

    @patch.dict(os.environ, ENV)
    def test_refusal_incomplete_and_bad_schema_fail_closed(self):
        bad_answer = dict(answer(), important="false")
        responses = [
            {"status": "incomplete", "output": []},
            {"status": "completed", "output": [{"type": "message", "content": [{"type": "refusal", "refusal": "No"}]}]},
            {"status": "completed", "output": [{"type": "message", "content": [{"type": "output_text", "text": json.dumps(bad_answer)}]}]},
        ]
        for response in responses:
            with self.assertRaisesRegex(watch.WatchError, "OPENAI_INVALID_STRUCTURED_RESPONSE"):
                watch.classify(FakeHttp([(response, {})]), "notes")

    def test_overlong_notes_are_not_silently_truncated(self):
        with self.assertRaisesRegex(watch.WatchError, "MODEL_INPUT_LIMIT"):
            watch.classify(FakeHttp(), "x" * (watch.MAX_ITEM + 1))


class DeliveryTests(unittest.TestCase):
    def test_state_saved_before_external_side_effect(self):
        value, store = state(), MemoryStore()
        def send(*args):
            self.assertEqual(store.saved[-1]["outbox"]["event"]["status"], "sending")
        with patch.object(watch, "pushover", side_effect=send) as notify:
            self.assertTrue(watch.deliver(None, store, value, "event", "title", "message", "https://example.com"))
            self.assertFalse(watch.deliver(None, store, value, "event", "title", "message", "https://example.com"))
        self.assertEqual(notify.call_count, 1)
        self.assertEqual(value["outbox"]["event"]["status"], "sent")

    def test_unknown_delivery_is_not_automatically_retried(self):
        value, store = state(), MemoryStore()
        with patch.object(watch, "pushover", side_effect=watch.WatchError("PUSHOVER_NETWORK", True)) as notify:
            with self.assertRaises(watch.WatchError):
                watch.deliver(None, store, value, "event", "title", "message", "https://example.com")
            with self.assertRaisesRegex(watch.WatchError, "OUTCOME_UNKNOWN"):
                watch.deliver(None, store, value, "event", "title", "message", "https://example.com")
        self.assertEqual(notify.call_count, 1)
        self.assertEqual(value["outbox"]["event"]["status"], "unknown")

    def test_known_rejection_remains_retryable(self):
        value, store = state(), MemoryStore()
        with patch.object(watch, "pushover", side_effect=[watch.WatchError("PUSHOVER_HTTP_429"), None]) as notify:
            with self.assertRaises(watch.WatchError):
                watch.deliver(None, store, value, "event", "title", "message", "https://example.com")
            self.assertEqual(value["outbox"]["event"]["status"], "rejected")
            watch.deliver(None, store, value, "event", "title", "message", "https://example.com")
        self.assertEqual(notify.call_count, 2)

    def test_checkpoint_failure_prevents_send(self):
        value, store = state(), MemoryStore()
        with patch.object(store, "save", side_effect=watch.WatchError("STATE_HTTP_409")):
            with patch.object(watch, "pushover") as notify:
                with self.assertRaises(watch.WatchError):
                    watch.deliver(None, store, value, "event", "title", "message", "https://example.com")
                notify.assert_not_called()


class MonitorTests(unittest.TestCase):
    def test_security_bypasses_unavailable_model_and_deduplicates(self):
        value, store = state(), MemoryStore()
        source = item(text="Fix vulnerability CVE-2026-12345.")
        with patch.object(watch, "collect", return_value=[source]), patch.object(watch, "classify") as model:
            with patch.object(watch, "pushover") as notify:
                first = watch.check(None, store, value, CONFIG)
                second = watch.check(None, store, value, CONFIG)
        model.assert_not_called()
        self.assertEqual(notify.call_count, 1)
        self.assertEqual(first["notifications"], 1)
        self.assertEqual(second["changed"], 0)
        self.assertEqual(value["installed_tag"], "v7.3.3")

    def test_initial_baseline_silent_but_edited_baseline_reassessed(self):
        value, store = state(), MemoryStore()
        with patch.object(watch, "collect", return_value=[item("v7.3.3", "Existing fixes")]):
            with patch.object(watch, "classify") as model, patch.object(watch, "pushover") as notify:
                watch.check(None, store, value, CONFIG)
                model.assert_not_called()
                notify.assert_not_called()
        with patch.object(watch, "collect", return_value=[item("v7.3.3", "Security fix for CVE-2026-12345")]):
            with patch.object(watch, "pushover") as notify:
                watch.check(None, store, value, CONFIG)
                self.assertEqual(notify.call_count, 1)

    def test_minor_new_release_silent_and_installed_baseline_preserved(self):
        value, store = state(), MemoryStore()
        with patch.object(watch, "collect", return_value=[item()]), patch.object(watch, "classify", return_value=answer(False)):
            with patch.object(watch, "pushover") as notify:
                watch.check(None, store, value, CONFIG)
                watch.check(None, store, value, CONFIG)
        notify.assert_not_called()
        self.assertEqual(value["installed_tag"], "v7.3.3")

    def test_model_limit_leaves_backlog_unreviewed(self):
        value, store = state(), MemoryStore()
        with patch.object(watch, "collect", return_value=[item("v7.3." + str(n)) for n in range(4, 12)]):
            with patch.object(watch, "classify", return_value=answer(False)) as model:
                counts = watch.check(None, store, value, CONFIG)
        self.assertEqual(model.call_count, 6)
        self.assertEqual(counts["deferred"], 2)
        self.assertEqual(len(value["reviewed"]), 6)
        self.assertEqual(value["last_status"], "backlog")

    def test_security_notification_limit_leaves_backlog(self):
        value, store = state(), MemoryStore()
        with patch.object(watch, "collect", return_value=[item("v7.3." + str(n), "Security fix") for n in range(4, 12)]):
            with patch.object(watch, "pushover") as notify:
                counts = watch.check(None, store, value, CONFIG)
        self.assertEqual(notify.call_count, 6)
        self.assertEqual(counts["deferred"], 2)

    def test_model_failure_does_not_mark_reviewed_or_hide_security(self):
        value, store = state(), MemoryStore()
        sources = [item("v7.3.4"), item("v7.3.5", "Fix CVE-2026-12345")]
        with patch.object(watch, "collect", return_value=sources):
            with patch.object(watch, "classify", side_effect=watch.WatchError("OPENAI_HTTP_429")):
                with patch.object(watch, "pushover") as notify:
                    with self.assertRaisesRegex(watch.WatchError, "OPENAI_HTTP_429"):
                        watch.check(None, store, value, CONFIG)
        self.assertEqual(notify.call_count, 1)
        self.assertNotIn("release:v7.3.4", value["reviewed"])
        self.assertIn("release:v7.3.5", value["reviewed"])

    @patch.dict(os.environ, ENV)
    def test_source_failure_alert_only_once(self):
        value, store = state(), MemoryStore()
        with patch.object(watch, "pushover") as notify:
            watch.report_failure(None, store, value, "CHANGELOG_FORMAT_CHANGED")
            watch.report_failure(None, store, value, "CHANGELOG_FORMAT_CHANGED")
        self.assertEqual(notify.call_count, 1)
        self.assertEqual(value["last_status"], "failed")

    @patch.dict(os.environ, ENV)
    def test_failure_recurrence_alerts_again_after_recovery(self):
        value, store = state(), MemoryStore()
        with patch.object(watch, "pushover") as notify:
            watch.report_failure(None, store, value, "CHANGELOG_FORMAT_CHANGED")
            with patch.object(watch, "collect", return_value=[]):
                watch.check(None, store, value, CONFIG)
            self.assertNotIn("last_error", value)
            watch.report_failure(None, store, value, "CHANGELOG_FORMAT_CHANGED")
        self.assertEqual(notify.call_count, 2)

    def test_ambiguous_old_delivery_does_not_block_new_security(self):
        value, store = state(), MemoryStore()
        old = item("v7.3.4", "Security fix one")
        new = item("v7.3.5", "Security fix two")
        key = old["id"] + ":" + watch.digest({"text": old["text"], "url": old["url"]})
        value["outbox"][key] = {"status": "unknown"}
        with patch.object(watch, "collect", return_value=[old, new]), patch.object(watch, "pushover") as notify:
            with self.assertRaisesRegex(watch.WatchError, "OUTCOME_UNKNOWN"):
                watch.check(None, store, value, CONFIG)
        self.assertEqual(notify.call_count, 1)
        self.assertIn(new["id"], value["reviewed"])
        self.assertNotIn(old["id"], value["reviewed"])

    def test_partial_source_error_still_sends_security_and_stays_failed(self):
        value, store = state(), MemoryStore()
        source = dict(item(text="Security fix CVE-2026-12345"), complete=False)
        items = watch.Candidates([source], [watch.WatchError("CHANGELOG_RELEASE_MISSING")])
        with patch.object(watch, "collect", return_value=items), patch.object(watch, "pushover") as notify:
            with self.assertRaisesRegex(watch.WatchError, "CHANGELOG_RELEASE_MISSING"):
                watch.check(None, store, value, CONFIG)
        self.assertEqual(notify.call_count, 1)
        self.assertNotIn(source["id"], value["reviewed"])
        self.assertEqual(value["last_status"], "failed")

    @patch.dict(os.environ, ENV)
    def test_connection_sends_exactly_one_explicit_test(self):
        with patch.object(watch, "classify", side_effect=[answer(False), answer(True)]) as model:
            with patch.object(watch, "pushover") as notify:
                result = watch.test_connection(None, CONFIG)
        self.assertEqual(model.call_count, 2)
        self.assertEqual(notify.call_count, 1)
        self.assertIn("ТЕСТ", notify.call_args.args[1])
        self.assertFalse(result["release_state_changed"])


if __name__ == "__main__":
    unittest.main()
