# Personal fork updates

This Windows x64 fork uses Telegram's native v2 signature verifier, download
progress, Update button and restart handoff. It discovers releases only at
`https://github.com/mennya/tdesktop-no-stories/releases/latest/download/fork-update.json`.
The official HTTP and MTProto update channels are not used.

## Client behavior

Install the first bootstrap with the fork installer or portable ZIP. Preserve
`TelegramForcePortable`; do not import an official client's sessions. Subsequent
fork releases download in the background when automatic update checks are on.
Use the Update button in the chat list, Advanced settings or login screen to
install and restart. Ordinary startup, settings restarts and a crash report's
background download do not authorize installation. Advanced settings includes a
link to the fork's release notes. About/version information includes the fork
build number.

The authenticated feed binds product, Windows x64 target, source commit, Telegram
version, fork counter, package filename, size and SHA256. The native verifier
also authenticates the v2 envelope before decompression, checks its target and
rejects an installed or older revision. A higher fork counter can update the
same Telegram version; an older Telegram base version is not accepted.

The package contains program files and runtime DLLs. Account directories,
`tdata`, preferences and sessions are excluded. The updater backs up existing
program files before replacement and restores completed replacements if a later
write fails. If restoration cannot finish, it retains the recovery directory
and stops instead of launching an inconsistent program. A portable copy does
not modify a different installation's registration; installer version metadata
uses only this fork's own AppId and matching install location.

A failed download or invalid signature leaves the installed program available.
The normal manual installer/portable replacement remains the recovery route.
Executables remain unsigned by Authenticode; update signatures are a separate
application-level trust mechanism.

## Build and publish

A checked production build creates a bootstrap and an incremental successor from
the same source commit. Only the generated fork-counter translation unit needs
recompilation for the successor. The pair allows an actual update test without
a second full application build. Verification builds use test API credentials
and are never eligible for the public update channel.

Counters are `workflow_run_number * 1000 + workflow_attempt * 10`, followed by
`+1` for the successor. Attempts above 99 require a fresh build run. Local builds
provide an explicit positive uint32 `FORK_BUILD_COUNTER`.

The Windows runner emits an unsigned native envelope. It never receives the
update signing key. Run **Publish signed fork update** on `codex/no-stories`,
with the exact successful production run ID and full source commit:

```sh
gh workflow run publish-fork-update.yml --ref codex/no-stories \
  -f source_run=PRODUCTION_RUN_ID -f source_commit=FULL_COMMIT -f mode=stage
```

The publication workflow:

1. Requires a successful exact-commit protected-branch production run; checks
   the downloaded GitHub artifact digest and all package checksums.
2. Independently compares the native Windows payload with the portable archive,
   checks AMD64 executables, source/build identity and absence of account data.
3. Signs the native envelope and discovery feed in an isolated Linux job.
4. Downloads the digest-checked verifier from that production run and executes
   the actual Windows verifier, decompressor and extractor against signed files.
5. Creates a draft release only after that exact native Windows job succeeds.

The optional `fork_build` input selects the bootstrap or successor; otherwise
it selects the successor. Review/test the staged packages, then use `mode=publish`
with the same source inputs. The final job uploads assets and atomically makes
the stable release the discovery target. Published tags/assets are not rewritten,
and a newer latest fork revision cannot be replaced by an older one. Candidate,
PR and verification artifacts cannot be published by this workflow.

## Key custody and recovery

The pinned public key and signed key manifest are in
`Telegram/Resources/no-stories/update/`. The private key is the
`TDESKTOP_UPDATE_SIGNING_KEY` **environment secret** in `tdesktop-fork-updates`.
That environment permits only the `codex/no-stories` branch and no tag refs;
there is no repository-level duplicate. It needs no additional per-run reviewer
prompt. The secret is passed only to the isolated signing step, uses private
scratch files for one process, and is excluded from artifacts and logs.

Keep this key stable. Losing or replacing the pinned key requires a reviewed
manual bootstrap for the new trust root; do not disable verification to recover.
For a defective release, prepare a corrected successor with a higher revision
or use the manual fork installer. A procedure here does not authorize changes
to Windows security settings or unrelated installation data.
