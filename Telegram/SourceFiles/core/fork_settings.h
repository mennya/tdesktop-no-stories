/*
This file is part of Telegram Desktop.
For license and copyright information please see:
https://github.com/telegramdesktop/tdesktop/blob/master/LEGAL
*/
#pragma once

namespace Core::ForkSettings {

// Local UI policy only. Do not change Telegram account settings on the server.
inline constexpr auto kStoriesEnabled = false;
inline constexpr auto kBirthdaySetupReminderEnabled = false;

} // namespace Core::ForkSettings
