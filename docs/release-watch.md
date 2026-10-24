# Important Telegram release monitoring

[Telegram Release Watch](https://github.com/mennya/tdesktop-no-stories/actions/workflows/release-watch.yml)
runs on GitHub-hosted Ubuntu every day at 09:00 Europe/Berlin, including daylight
saving time changes. The owner's PC and MS-01 do not need to be running.
GitHub may delay or occasionally drop scheduled jobs; this is a daily advisory
check, not a guaranteed-time security feed.

## Sources and decisions

The monitor reads official stable
[releases](https://github.com/telegramdesktop/tdesktop/releases), the
[changelog](https://telegramdesktop.github.io/tdesktop/changelog/) and published
[security advisories](https://github.com/telegramdesktop/tdesktop/security/advisories).
It checks versions since the installed baseline, including edited release
information. Prereleases are excluded. Missing sources and parser errors fail
the run rather than imply that there are no updates.

New or changed information is classified using `gpt-6-luna` through the OpenAI
Responses API. Public source text is treated as data, without tools or code
execution. Requests disable response storage and use a strict JSON schema,
bounded input and output, and at most six model calls per normal run. Unchanged
information incurs no model call. Explicit security signals and published
advisories bypass model filtering; an advisory is not proof that the installed
version is affected. No published advisory does not prove the absence of flaws.

Pushover receives concise Russian notices for security/privacy fixes, data loss,
serious Windows crashes, login/compatibility issues and substantial ordinary
messaging/calling changes. Cosmetic, Stories-only and unspecified minor fixes
stay quiet. The monitor does not build, install, update the installed baseline,
operate a VM, or change client settings.

## Credentials and state

Set these repository Actions secrets; never put their values in Git, logs,
workflow inputs or chat:

- `OPENAI_API_KEY`: dedicated OpenAI project key with model/Responses access.
- `PUSHOVER_APP_TOKEN`: dedicated Telegram Release Watch application token.
- `PUSHOVER_USER_KEY`: the owner's Pushover user key.

Optional repository variable `PUSHOVER_DEVICE` selects a device. If omitted,
Pushover sends to all active devices on that account. The workflow's ephemeral
`GITHUB_TOKEN` writes state; no personal access token is required. Telegram
build credentials are not passed to this workflow.

`.github/release-watch-config.json` records the owner-confirmed installed tag
and build commit. `state.json` on the separate `codex/release-watch-state` branch
records source fingerprints, notification outcomes and check health. This is
public operational metadata and contains no credentials or Telegram account
data. Daily checkpoints retain meaningful repository activity. GitHub can
disable public-repository schedules after 60 days without activity; inspect the
workflow's enabled state when investigating missing checks.

## Verification and operation

Use **Run workflow**, branch `codex/no-stories`:

- `mode=test` makes two small live model classifications and sends one clearly
  marked test notification. It does not alter the release ledger.
- `mode=check` checks real sources and saves state. A repeated unchanged check
  should report zero model calls and zero notifications.

Pushover API acceptance confirms the service accepted a message, not that a
particular device displayed it. Confirm initial device receipt separately.
The job summary contains counts; failed jobs contain sanitized error codes.

The notification ledger records intent before sending and acceptance afterward.
An ambiguous network result is retained as `sending` or `unknown` and is not
automatically resent. Inspect the matching message in Pushover and the Actions
run before changing that exact ledger entry to `sent` or `rejected`. A known
rejection can be retried after its cause is corrected. Do not delete all state
to retry one message: that can repeat old notifications. Repeated check errors
are deduplicated; inspect failed Actions runs if Pushover itself is unavailable.

After the owner confirms installing a newer reviewed fork build, deliberately
update the installed tag/commit in configuration and the matching installed tag
in state. Do not advance the baseline merely because an upstream release or
build exists. Keep the notification history.

Disable this workflow to stop monitoring. The previous local Codex monitor
should remain paused after successful migration. Re-enable it only as an
explicit fallback, to avoid duplicate notices.

Run local checks with Python 3.12 or newer:

```sh
python3 -m unittest discover -s .github/scripts -p 'test_release_watch.py' -v
```

Changes limited to this monitor or documentation do not trigger a Windows build.
Actual application/build changes and explicit build dispatches retain their
existing behavior.
