# Building Telegram No Stories for Windows

This fork builds Windows x64 with Qt 6 from upstream stable tag **v7.4.1**.
The `No Stories Windows x64` workflow produces a Release executable, a portable
ZIP, an unsigned installer and SHA-256 checksums. The first dependency build can
take several hours. Later runs reuse separate build-tool, library and Qt caches.
The workflow reports free disk space and removes disposable dependency object and
debug-symbol files before caching and building the app. Qt installed object
libraries and generated sources remain intact. The standard hosted runner has
limited storage, so these cleanup and cache boundaries must be preserved. No
paid runner or cache-storage increase is enabled automatically.

## Build modes

Prepare each update in a `codex/candidate/<slug>` branch based on the current
`codex/no-stories` head. Keep the upstream merge and personal changes in separate
commits. A push starts a **validation** run with public test API configuration,
the production MSVC/SDK and Release flags. Only the release branch can receive
repository API credentials. Candidate runs finish with compilation and produce
no installation packages.

The validation helper derives changed paths from Git and maps source files to
real Release objects in `compile_commands.json`. Header, build recipe, resource,
schema, dependency and unknown-source changes select the full `Telegram` target.
Known macOS/Linux-only source files are excluded from Windows object selection.
The compiler collects up to eight failures per validation run. Model tests remain
an earlier logic check.

After both `regression-models` and `Windows validation` succeed for the exact
candidate head, promote it from the clean candidate checkout:

```sh
python3 Telegram/build/no-stories/ci.py promote \
  --commit <full-checked-head> --expected-base <current-release-head>
```

The helper requires the latest trusted candidate run to pass and checks that the
release branch still matches the expected base before a normal fast-forward
push. A moved base requires integration and fresh validation. Release-branch
protection requires the same two GitHub Actions checks. The production workflow
also verifies the exact candidate run before its Windows job can start.

Source/build changes on the release branch then create **production** packages.
Changes confined to the ignored documentation/monitor paths do not automatically
trigger a build. A green manual dispatch alone did not satisfy this repository's
protected-branch admission; publication needs successful push-triggered candidate
checks. The trigger-policy follow-up is tracked in
[issue #362](https://gitlab.taild93257.ts.net/root/wiki/-/work_items/362).
Manual `build_kind=verification` on the release branch still produces clearly
marked test packages after the same candidate check. The default is production.

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

Avatar policy definitions live in the `Telegram` application target, where the
model and MTProto PCH prerequisites exist. The low-level `td_ui` userpic renderer
must not include `data_user.h`. The automatic compilation scope covers changed
renderer/policy sources and expands to the full target for headers or uncertain
inputs. Legacy avatar/strict-mute object commands remain available for diagnosis.
A required Ninja Multi-Config fixture verifies exact Release object selection,
excludes Debug/unrelated objects and reproduces two private-member errors before
accepting corrected sources. These checks complement the model tests.

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
taskbar labels and Alt-Tab. Chat-list counters and unread state are preserved
for ordinary chats. Popup notifications, sounds and the separate taskbar
attention-flash setting keep their existing behavior outside strict mute.

## Quiet names and composer

Custom emoji in names and emoji status decorations use their first frame in the
chat list, chat header, profiles, main menu and message sender names. Message-body
emoji, stickers and reactions retain their existing animation behavior.

Empty message composers show no microphone or round-video recording button and
reclaim its space. Voice and round-video recording shortcuts are disabled. Send,
schedule, edit and attachment controls retain their existing behavior, as do
incoming voice-message playback and outgoing calls. Strict mute separately
suppresses incoming-call attention for selected peers.

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

## Strict mute

Enable **Strict mute** in a chat's menu and accept the confirmation to make that
chat quiet locally. A static lock-and-mute mark beside the chat name and in its
header distinguishes it from Telegram's ordinary mute. Icon-only chat lists show
the same mark on a small plaque at the avatar's bottom edge, without a number or
animation. The mark remains visible when the optional native mute icon is
disabled, follows the current theme and
selection colors, and reserves title space instead of covering the name. The
header exposes the localized label as tooltip and accessibility description.

Strict mute suppresses notifications, sound, flashing and unread/mention/reaction
attention from the selected peer, including pending notifications. Incoming
one-to-one calls do not open a call panel, ring or show a desktop notification;
they are not automatically declined, and Telegram's signaling/timeouts remain.
The owner may still explicitly open an available call or start an outgoing call.

The stored preference is per account and per local installation. It does not
change Telegram's server mute settings or mark messages read. The display omits
strict-muted peers from unread badges and aggregate counters while preserving the
underlying messages and unread state. The chat retains a stored sorting anchor
instead of rising with new messages; explicit pinning and normal list/filter
membership still apply; automatic unread/unmuted filters exclude strict-muted
chats unless they are explicitly included. Turning strict mute off restores actual unread counts
and current normal sorting without replaying old notifications. Restarting the
client preserves the preference and anchor; signing into another account does
not inherit them. Both enabling and disabling require explicit confirmation;
Enter/Return cancels the confirmation by default.

The archive may initially have a cloud total without all dialog metadata. The
client requests the known strict-muted dialogs once per connection epoch. Until
their archive membership and counts are known, or while a strict-muted forum has
incomplete topic counts, only the unresolved archive aggregate is hidden. Failed
requests do not turn unknown data into known counts and are retried on normal
reconnection; unrelated chats keep their counters. Loading the archive/topics
allows the display to reconcile without changing messages or read state.

## Verification

Run `python3 Telegram/build/no-stories/test_personal_userpics.py` on a host with
Python 3 and a C++20 `g++` compiler. It executes extracted production policy,
cloud-view and personal-photo transition functions with synthetic dependencies;
it does not compile the application or exercise Qt painting or the UI.

Run the strict-mute regression checks with the same Python/C++20 environment:

```sh
python3 Telegram/build/no-stories/test_ci.py
python3 Telegram/build/no-stories/test_changed.py
python3 Telegram/build/no-stories/test_strict_mute_order.py
python3 Telegram/build/no-stories/test_strict_mute_unread.py
python3 Telegram/build/no-stories/test_strict_mute_calls.py
python3 Telegram/build/no-stories/test_strict_mute_notifications.py
python3 Telegram/build/no-stories/test_build.py --integration required
```

These compile selected production methods against synthetic dependencies. They
cover ordering, raw/display counter separation, folder matching, call latching
and queue cancellation. The CMake/Ninja fixture checks exact Release object
selection. Windows CI then compiles the modified translation units before the
full application; neither layer substitutes for logged-in GUI acceptance.

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

For strict-mute acceptance, use controlled test chats and check the following in
a production build after normal owner login. These are acceptance requirements,
not a claim that interactive testing has already passed.

| Case | Required result |
| --- | --- |
| Enable, cancel, disable | Both transitions ask for confirmation; cancel or stray Enter changes nothing. Disabling restores actual unread counts and normal sorting without replaying alerts. |
| New messages, mentions and reactions | Strict-muted peers produce no local notification, sound, attention flash or unread/mention/reaction badge; ordinary and ordinary-muted chats retain their expected behavior. |
| Pending notifications | An alert queued before enabling strict mute is suppressed; disabling it does not replay the old queue. |
| Chat list and aggregate counts | Strict-muted contributions disappear from chat, folder/filter and account counters while messages and actual unread state remain intact. |
| Sorting and restart | Incoming messages, own sends, local/cloud drafts and reactions does not advance the stored anchor. Restart preserves it; explicit pinning and filter membership remain usable. |
| Accounts | Switching between two accounts does not leak strict-mute preferences or anchors. |
| Incoming and outgoing calls | A strict-muted caller produces no ringing, popup or notification; no automatic decline is sent. Explicitly opened and outgoing calls remain usable. |
| Static marker | Lock-and-mute stays visible with the ordinary mute icon off, in light/dark themes, active/hovered rows, long names, narrow title areas, icon-only lists and RTL. Header label updates when the setting, chat or language changes. |
| Regression controls | Non-strict chats, service peers, self chat, text/media sending, voice playback, personal avatars and existing quiet-interface changes retain their intended behavior. |
