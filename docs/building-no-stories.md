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

Source/build changes pushed to the trusted `codex/no-stories` branch create **production** packages
using this repository's API secrets. Documentation and release-monitor-only
changes do not trigger a build. An explicit manual `build_kind=verification`
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

The workflow pins its actions and uses `windows-2022`, Visual Studio 2022,
MSVC 14.44 and Windows SDK 10.0.26100.0. This keeps the compiler and ATL headers
on the same toolset: Breakpad's `dump_syms` could not find ATL when using the
VS 2026 image's optional MSVC 14.44 compiler. Before preparing dependencies,
the workflow verifies the selected versions, both ATL headers, and compilation,
linking and execution of a small ATL probe. Ninja is used, so a Visual Studio
2026 CMake generator is not required. It runs dependency preparation with Release
libraries enabled, then builds the `Telegram` target. It does not build or ship
the official updater, and compiles with `DESKTOP_APP_DISABLE_AUTOUPDATE=ON`.
Crash report submission is also disabled for this personal build.

The app build uses the resolved `USERPROFILE\TBuild\tdesktop\out` path instead
of the longer workspace junction. CMake limits object paths to 220 characters;
the build helper checks generated compiler outputs against Windows' 260-character
limit. It first compiles the Qt image-format plugin target, including generated
MOC sources, before building the remaining Telegram targets. Dependency locations
and cache keys are independent of this application-output path handling.

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

## Windows unread indicators

This personal fork keeps the Windows tray and taskbar icons free of unread
numbers, muted grey badges and the monochrome unread dot. Tray tooltips and
window titles also omit unread counts, including active-chat counts shown by
taskbar labels and Alt-Tab. Chat-list counters and unread state are preserved.
Popup notifications, sounds and the separate taskbar attention-flash setting
keep their existing behavior.

## Quiet names and composer

Custom emoji in names and emoji status decorations use their first frame in the
chat list, chat header, profiles, main menu and message sender names. Message-body
emoji, stickers and reactions retain their existing animation behavior.

Empty message composers show no microphone or round-video recording button and
reclaim its space. Voice and round-video recording shortcuts are disabled. Send,
schedule, edit and attachment controls retain their existing behavior, as do
incoming voice-message playback and calls.

## Personal contact avatars

For other ordinary people, this fork displays initials unless the account owner
has assigned a personal contact photo through Telegram's existing **Set Profile
Photo** action. Assigned pictures remain static. Photo assignment and deletion
use Telegram's existing API and sync; there is no extra local avatar database.
Deleting an assigned photo returns to initials. Changing another person's own
photo cannot replace the displayed identity.

The rule covers common avatar painting, chat and sender rows, search, profiles,
quick contact cards, calls and newly generated Windows notification images.
Original-photo thumbnails, avatar galleries and avatar click-to-open are hidden
for these people; the photo editor still previews a picture the owner selects.
The edit-contact removal action is labeled **Delete**, because it returns to
initials instead of exposing the original. Self, bots, groups, channels and
service icons retain their prior behavior. Photos sent in messages still open.

This is a display policy, not deletion of Telegram's stored photos or cache.
Already delivered OS notifications are not rewritten. Other Telegram clients
still apply their own display rules, while personal contact photos continue to
sync through Telegram.

## Verification

Run `python3 Telegram/build/no-stories/test_personal_userpics.py` on a host with
Python 3 and a C++20 `g++` compiler. It executes extracted production policy,
cloud-view and personal-photo transition functions with synthetic dependencies;
it does not compile the application or exercise Qt painting or the UI.

Inspect `build-info.json`, verify the package against `SHA256SUMS.txt`, and test
startup inside the dedicated VM. With production credentials, verify login,
ordinary messages/photos/videos, Stories suppression, the birthday setup prompt,
and live broadcasts. Check that name/status emoji stay on their first frame in
the surfaces listed above while body emoji, stickers and reactions still animate.
Check an empty composer has no recording icon or blank gap, then verify text
sending, scheduled sending, editing and attachments, plus incoming voice playback
and calls. A successful compiler run does not establish these UI behaviors.
Preserve the portable account directory when replacing the executable.

For avatar acceptance, test cached originals after cold startup and account
switching; assign, change and delete a personal photo; let a contact change their
own photo; check list/search/sender/profile/quick-card/call/new-notification
surfaces. A contact without a personal photo must show initials throughout, and
an assigned photo must remain static. Check there is no original preview or
avatar gallery, the editor still works, message photos still open, and self,
bots, groups and channels retain their behavior. Use synthetic or owner-chosen
test contacts and normal login, never imported session data.
