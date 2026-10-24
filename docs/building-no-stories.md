# Building Telegram No Stories for Windows

This fork builds Windows x64 with Qt 6 from the approved upstream stable tag.
The `No Stories Windows x64` workflow produces a Release executable, a portable
ZIP, an unsigned installer and SHA-256 checksums. The first dependency build can
take several hours. Later runs reuse separate build-tool, library and Qt caches.
The workflow reports free disk space and removes disposable dependency object and
debug-symbol files before caching and building the app. Qt installed object
libraries and generated sources remain intact. The standard hosted runner has
limited storage; the first real run must establish whether it is sufficient.
No paid runner or cache-storage increase is enabled automatically.

## Build modes

Pushes to the trusted `codex/no-stories` branch create **production** packages
using this repository's API secrets. An explicit manual `build_kind=verification`
run uses Telegram's limited test credentials. Those filenames and README clearly
mark them as verification-only; do not use them as a daily client.

For a **production** build, obtain your own API credentials through
[Telegram API development tools](https://core.telegram.org/api/obtaining_api_id),
then set the repository Actions secrets `TDESKTOP_API_ID` and `TDESKTOP_API_HASH`.
Do not put values in source, workflow inputs, issue comments or chat messages.
Manually run the workflow with `build_kind=production` against the reviewed
commit. GitHub requires a manual workflow to exist on the repository's default
branch before it can be dispatched. Production configuration fails early if
credentials are missing or match the public test API id.

Credentials reach only the validation/configuration steps through environment
variables. The configure helper uses an initial CMake cache file so credential
values do not appear in command arguments, and removes that file after configure.
CMake's generated cache and sources contain the values required by the build;
they stay on the ephemeral runner and are neither cached nor uploaded. The API
credentials are embedded in the executable, as with other Telegram clients.

## Build and package behavior

The workflow pins its actions and uses `windows-2025-vs2026`, MSVC 14.44 and
Windows SDK 10.0.26100.0. It runs upstream dependency preparation with Release
libraries enabled, then builds the `Telegram` target. It does not build or ship
the official updater, and compiles with `DESKTOP_APP_DISABLE_AUTOUPDATE=ON`.
Crash report submission is also disabled for this personal build.

The portable ZIP includes `TelegramForcePortable`, which upstream's
`CheckPortableVersionFolder()` uses for isolated account storage. Extract the
whole ZIP into its own writable folder. Keep that directory beside `Telegram.exe`.
The installer has its own application id, installs under
`%LOCALAPPDATA%\Programs\Telegram No Stories`, and creates separately named
shortcuts. It does not register URL handlers, start the app, import official
account data, or delete account data during uninstall. Sign in normally.
Do not extract or install this fork over an official Telegram folder.

Packages include a source commit link, licensing files, executable hash and
build mode. They are unsigned because no code-signing certificate is configured.
Updates require a new reviewed fork build and manual installation. The inherited
upstream workflows are retained in `.github/upstream-workflows`, outside the
Actions discovery directory, so their bots and multi-platform pipelines do not
run for this fork branch.

## Verification

Inspect `build-info.json`, verify the package against `SHA256SUMS.txt`, and test
startup inside the dedicated VM. With production credentials, verify login,
ordinary messages/photos/videos, Stories suppression, the birthday setup prompt,
and live broadcasts. A successful compiler run does not establish these UI
behaviors. Preserve the portable account directory when replacing the executable.
