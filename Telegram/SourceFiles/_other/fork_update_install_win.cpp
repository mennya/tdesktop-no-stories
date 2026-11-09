/*
This file is part of Telegram Desktop.
For license and copyright information see https://github.com/telegramdesktop/tdesktop/blob/master/LEGAL
*/
#include "fork_update_install_win.h"
#include <algorithm>
#include <cwctype>
#include <filesystem>
#include <set>
#include <vector>

namespace ForkUpdater {
namespace {
namespace fs = std::filesystem;

std::wstring Fold(std::wstring value) {
	std::transform(value.begin(), value.end(), value.begin(), [](wchar_t c) {
		return wchar_t(std::towlower(c));
	});
	return value;
}

bool Reparse(const fs::path &path) {
	const auto attributes = GetFileAttributesW(path.c_str());
	return attributes != INVALID_FILE_ATTRIBUTES
		&& (attributes & FILE_ATTRIBUTE_REPARSE_POINT);
}

bool ProgramFile(const std::wstring &name) {
	if (name.empty() || name.find(L':') != name.npos
		|| name.find(L"..") != name.npos) {
		return false;
	}
	return (name == L"telegram.exe")
		|| (name == L"build-info.json")
		|| (name == L"license") || (name == L"legal")
		|| (name == L"readme.txt")
		|| (name.ends_with(L".dll")
			&& (name.find(L'/') == name.npos || name.starts_with(L"modules/")));
}

bool Replace(const fs::path &source, const fs::path &target, DWORD &error) {
	auto temporary = target;
	temporary += L".fork-new-" + std::to_wstring(GetCurrentProcessId());
	if (!CopyFileW(source.c_str(), temporary.c_str(), TRUE)) {
		error = GetLastError();
		return false;
	}
	if (!MoveFileExW(temporary.c_str(), target.c_str(),
			MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH)) {
		error = GetLastError();
		DeleteFileW(temporary.c_str());
		return false;
	}
	return true;
}

struct Entry {
	fs::path source;
	fs::path target;
	fs::path backup;
	std::wstring relative;
	bool existed = false;
};

} // namespace

Result Install(
		const std::wstring &stagingDirectory,
		const std::wstring &programDirectory,
		const std::wstring &executableName) {
	auto result = Result();
	try {
		const auto stage = fs::canonical(stagingDirectory);
		const auto destination = fs::canonical(programDirectory);
		const auto executable = fs::path(executableName);
		if (stage == destination || executable.empty() || executable.has_parent_path()
			|| executable.has_root_name() || Fold(executable.extension().wstring()) != L".exe"
			|| Fold(executableName) == L"updater.exe" || executableName.find(L':') != executableName.npos) {
			result.error = ERROR_INVALID_PARAMETER;
			result.message = L"Invalid fork update location or executable.";
			return result;
		}
		auto entries = std::vector<Entry>();
		auto names = std::set<std::wstring>();
		auto hasExecutable = false;
		auto hasManifest = false;
		for (const auto &file : fs::recursive_directory_iterator(stage)) {
			const auto relative = file.path().lexically_relative(stage);
			const auto name = Fold(relative.generic_wstring());
			if (Reparse(file.path())) {
				result.error = ERROR_ACCESS_DENIED;
				result.message = L"Update staging contains a reparse point.";
				return result;
			}
			if (file.is_directory()) {
				if (name != L"modules" && !name.starts_with(L"modules/")
					&& name != L"tdata") {
					result.error = ERROR_INVALID_DATA;
					result.message = L"Update contains a non-program directory.";
					return result;
				}
				continue;
			}
			if (name == L"ready" || name == L"tdata/version") {
				continue;
			}
			if (!file.is_regular_file() || !ProgramFile(name)
				|| !names.insert(name).second) {
				result.error = ERROR_INVALID_DATA;
				result.message = L"Update contains an unsafe or duplicate filename.";
				return result;
			}
			auto target = destination / ((name == L"telegram.exe") ? executable : relative);
			for (auto ancestor = target; ancestor != destination; ancestor = ancestor.parent_path()) {
				if (ancestor.empty() || Reparse(ancestor)) {
					result.error = ERROR_ACCESS_DENIED;
					result.message = L"Program destination contains a reparse point.";
					return result;
				}
			}
			hasExecutable |= (name == L"telegram.exe");
			hasManifest |= (name == L"build-info.json");
			entries.push_back({file.path(), target, {}, name, fs::exists(target)});
		}
		if (!hasExecutable || !hasManifest) {
			result.error = ERROR_INVALID_DATA;
			result.message = L"Update is missing the executable or build manifest.";
			return result;
		}
		// Install the executable last, after its runtime files are in place.
		std::sort(entries.begin(), entries.end(), [](const Entry &a, const Entry &b) {
			if ((a.relative == L"telegram.exe") != (b.relative == L"telegram.exe")) {
				return b.relative == L"telegram.exe";
			}
			return a.relative < b.relative;
		});
		const auto backup = stage.parent_path()
			/ (L"fork-rollback-" + std::to_wstring(GetCurrentProcessId())
				+ L"-" + std::to_wstring(GetTickCount64()));
		if (!fs::create_directory(backup)) {
			result.error = ERROR_ALREADY_EXISTS;
			result.message = L"Could not reserve update recovery directory.";
			return result;
		}
		result.recoveryDirectory = backup.wstring();
		for (auto i = size_t(0); i != entries.size(); ++i) {
			auto &entry = entries[i];
			entry.backup = backup / std::to_wstring(i);
			if (entry.existed && !CopyFileW(entry.target.c_str(), entry.backup.c_str(), TRUE)) {
				result.error = GetLastError();
				result.message = L"Could not back up program files; nothing was replaced.";
				return result;
			}
		}
		// Prepare all destination directories before the first replacement.
		for (const auto &entry : entries) {
			fs::create_directories(entry.target.parent_path());
		}
		auto applied = size_t(0);
		for (; applied != entries.size(); ++applied) {
			auto error = DWORD(ERROR_SUCCESS);
			if (!Replace(entries[applied].source, entries[applied].target, error)) {
				result.error = error;
				auto restored = true;
				while (applied) {
					const auto &entry = entries[--applied];
					auto restoreError = DWORD(ERROR_SUCCESS);
					restored &= entry.existed
						? Replace(entry.backup, entry.target, restoreError)
						: bool(DeleteFileW(entry.target.c_str()));
				}
				result.message = restored
					? L"Update failed. The previous program files were restored."
					: L"Update failed. Recovery files were retained; do not discard them.";
				if (restored) {
					std::error_code ignored;
					fs::remove_all(backup, ignored);
					result.recoveryDirectory.clear();
				}
				return result;
			}
		}
		result.success = true;
		result.message = L"Update installed.";
		std::error_code ignored;
		fs::remove_all(backup, ignored);
		result.recoveryDirectory.clear();
		return result;
	} catch (const fs::filesystem_error &error) {
		result.error = DWORD(error.code().value());
		result.message = L"Filesystem check failed; retained recovery files must not be discarded.";
		return result;
	}
}

void UpdateRegistration(const std::wstring &programDirectory, const std::wstring &executableName) {
	const auto name = L"Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\{08DF0784-3B6C-44C3-8CBC-A7764CDB3C9E}_is1";
	auto key = HKEY();
	if (RegOpenKeyExW(HKEY_CURRENT_USER, name, 0, KEY_QUERY_VALUE | KEY_SET_VALUE, &key) != ERROR_SUCCESS) {
		return; // A portable copy has no installer registration.
	}
	try {
		auto type = DWORD(0);
		wchar_t location[32768] = {};
		auto size = DWORD(sizeof(location));
		if (RegQueryValueExW(key, L"InstallLocation", nullptr, &type,
				reinterpret_cast<BYTE*>(location), &size) != ERROR_SUCCESS
			|| type != REG_SZ || size < sizeof(wchar_t) || size > sizeof(location)) {
			RegCloseKey(key);
			return;
		}
		location[(sizeof(location) / sizeof(wchar_t)) - 1] = 0;
		std::error_code error;
		if (!fs::equivalent(programDirectory, location, error) || error) {
			RegCloseKey(key);
			return; // Updating one portable copy must not alter another install.
		}
		const auto executable = fs::path(programDirectory) / executableName;
		auto unused = DWORD(0);
		const auto length = GetFileVersionInfoSizeW(executable.c_str(), &unused);
		if (!length || length > 1024 * 1024) {
			RegCloseKey(key);
			return;
		}
		auto bytes = std::vector<BYTE>(length);
		VS_FIXEDFILEINFO *version = nullptr;
		auto versionSize = UINT(0);
		if (GetFileVersionInfoW(executable.c_str(), 0, length, bytes.data())
			&& VerQueryValueW(bytes.data(), L"\\", reinterpret_cast<void**>(&version), &versionSize)
			&& version && versionSize >= sizeof(VS_FIXEDFILEINFO)
			&& version->dwSignature == 0xFEEF04BD) {
			const auto text = std::to_wstring(HIWORD(version->dwProductVersionMS)) + L"."
				+ std::to_wstring(LOWORD(version->dwProductVersionMS)) + L"."
				+ std::to_wstring(HIWORD(version->dwProductVersionLS));
			RegSetValueExW(key, L"DisplayVersion", 0, REG_SZ,
				reinterpret_cast<const BYTE*>(text.c_str()), DWORD((text.size() + 1) * sizeof(wchar_t)));
		}
	} catch (const fs::filesystem_error &) {
		// Registration metadata cannot invalidate an already completed file update.
	}
	RegCloseKey(key);
}

} // namespace ForkUpdater
