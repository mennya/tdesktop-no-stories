/*
This file is part of Telegram Desktop.
For license and copyright information see https://github.com/telegramdesktop/tdesktop/blob/master/LEGAL
*/
#pragma once
#include <windows.h>
#include <string>

namespace ForkUpdater {
struct Result {
	bool success = false;
	DWORD error = ERROR_SUCCESS;
	std::wstring message;
	std::wstring recoveryDirectory;
};

// Installs only program files. Existing files are backed up before replacement;
// failure restores every completed replacement and retains recovery data if
// restoration itself fails. Does not open account data or launch applications.
[[nodiscard]] Result Install(
	const std::wstring &stagingDirectory,
	const std::wstring &programDirectory,
	const std::wstring &executableName);
[[nodiscard]] inline bool PerUserUpdateAllowed() {
	auto token = HANDLE();
	if (!OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY, &token)) { return false; }
	auto elevation = TOKEN_ELEVATION();
	auto length = DWORD(0);
	const auto checked = GetTokenInformation(token, TokenElevation, &elevation, sizeof(elevation), &length);
	CloseHandle(token);
	return checked && !elevation.TokenIsElevated;
}
void UpdateRegistration(const std::wstring &programDirectory, const std::wstring &executableName);
} // namespace ForkUpdater
