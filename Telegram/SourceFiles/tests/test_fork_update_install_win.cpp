/*
This file is part of Telegram Desktop.
For license and copyright information see https://github.com/telegramdesktop/tdesktop/blob/master/LEGAL
*/
#include "_other/fork_update_install_win.h"
#include <filesystem>
#include <fstream>
#include <iostream>

namespace {
namespace fs = std::filesystem;
int Checks = 0;
int Failures = 0;

void Check(bool passed, const char *message) {
	++Checks;
	if (!passed) { ++Failures; std::cerr << "FAILED: " << message << std::endl; }
}
void Write(const fs::path &path, const std::string &data) {
	fs::create_directories(path.parent_path());
	std::ofstream(path, std::ios::binary) << data;
}
std::string Read(const fs::path &path) {
	auto input = std::ifstream(path, std::ios::binary);
	return std::string(std::istreambuf_iterator<char>(input), {});
}
struct Fixture {
	fs::path program;
	fs::path stage;
	explicit Fixture(const fs::path &root) : program(root / L"program"), stage(root / L"work/tupdates/temp") {
		Write(program / L"Telegram.exe", "old executable");
		Write(program / L"build-info.json", "old manifest");
		Write(program / L"modules/x64/d3d/test.dll", "old dll");
		Write(program / L"TelegramForcePortable/tdata/settings", "account fixture; preserve");
		Write(stage / L"Telegram.exe", "new executable");
		Write(stage / L"build-info.json", "new manifest");
		Write(stage / L"modules/x64/d3d/test.dll", "new dll");
		Write(stage / L"ready", "1");
		Write(stage / L"tdata/version", "version fixture");
	}
	ForkUpdater::Result install(const std::wstring &name = L"Telegram.exe") const {
		return ForkUpdater::Install(stage.wstring(), program.wstring(), name);
	}
	void unchanged() const {
		Check(Read(program / L"Telegram.exe") == "old executable", "previous executable retained");
		Check(Read(program / L"build-info.json") == "old manifest", "previous manifest retained");
		Check(Read(program / L"modules/x64/d3d/test.dll") == "old dll", "previous DLL retained");
		accountUnchanged();
	}
	void accountUnchanged() const {
		Check(Read(program / L"TelegramForcePortable/tdata/settings") == "account fixture; preserve", "account storage untouched");
		Check(!fs::exists(program / L"tdata"), "no account directory created beside executable");
	}
};
} // namespace

int main() {
	auto token = HANDLE();
	auto elevation = TOKEN_ELEVATION();
	auto length = DWORD(0);
	const auto queried = OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY, &token)
		&& GetTokenInformation(token, TokenElevation, &elevation, sizeof(elevation), &length);
	if (token) { CloseHandle(token); }
	Check(queried, "own process elevation queried");
	Check(ForkUpdater::PerUserUpdateAllowed() == bool(queried && !elevation.TokenIsElevated),
		"actual elevated token cannot authorize a per-user automatic update");
	const auto workspace = fs::canonical(fs::current_path());
	const auto root = workspace / (L"fork-install-tests-" + std::to_wstring(GetCurrentProcessId())
		+ L"-" + std::to_wstring(GetTickCount64()));
	if (!fs::create_directory(root) || root.parent_path() != workspace) { return 2; }
	{
		const auto fixture = Fixture(root / L"success with spaces \u0442\u0435\u0441\u0442");
		const auto result = fixture.install();
		Check(result.success, "program transaction succeeds");
		Check(Read(fixture.program / L"Telegram.exe") == "new executable", "new executable installed");
		Check(Read(fixture.program / L"build-info.json") == "new manifest", "new manifest installed");
		Check(Read(fixture.program / L"modules/x64/d3d/test.dll") == "new dll", "new DLL installed");
		Check(result.recoveryDirectory.empty(), "successful backup retired");
		fixture.accountUnchanged();
	}
	{
		const auto fixture = Fixture(root / L"rollback");
		Write(fixture.stage / L"fresh.dll", "new optional runtime");
		const auto locked = CreateFileW((fixture.program / L"Telegram.exe").c_str(),
			GENERIC_READ, FILE_SHARE_READ, nullptr, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, nullptr);
		Check(locked != INVALID_HANDLE_VALUE, "locked original fixture opened");
		const auto result = fixture.install();
		CloseHandle(locked);
		Check(!result.success, "locked executable refuses replacement");
		fixture.unchanged();
		Check(!fs::exists(fixture.program / L"fresh.dll"), "new file removed during rollback");
		Check(result.recoveryDirectory.empty(), "complete rollback retired backup");
	}
	{
		const auto fixture = Fixture(root / L"account payload");
		Write(fixture.stage / L"TelegramForcePortable/tdata/settings", "must not be installed");
		Check(!fixture.install().success, "account payload rejected before replacement");
		fixture.unchanged();
	}
	{
		const auto fixture = Fixture(root / L"legacy tdata payload");
		Write(fixture.stage / L"tdata/key_data", "must not be installed");
		Check(!fixture.install().success, "legacy account payload rejected");
		fixture.unchanged();
	}
	{
		const auto fixture = Fixture(root / L"running helper payload");
		Write(fixture.stage / L"Updater.exe", "must be retired by verified parent");
		Check(!fixture.install().success, "running helper is not overwritten by file transaction");
		fixture.unchanged();
	}
	{
		const auto fixture = Fixture(root / L"missing manifest");
		fs::remove(fixture.stage / L"build-info.json");
		Check(!fixture.install().success, "incomplete payload rejected");
		fixture.unchanged();
	}
	{
		const auto fixture = Fixture(root / L"destination symlink");
		const auto outside = root / L"outside";
		fs::create_directory(outside);
		fs::remove_all(fixture.program / L"modules");
		std::error_code error;
		fs::create_directory_symlink(outside, fixture.program / L"modules", error);
		Check(!error, "isolated destination symlink fixture created");
		if (!error) {
			Check(!fixture.install().success, "destination reparse point rejected");
			Check(fs::is_empty(outside), "update did not escape program directory");
			Check(Read(fixture.program / L"Telegram.exe") == "old executable", "reparse rejection preserves executable");
			fs::remove(fixture.program / L"modules");
		}
	}
	// The only recursive cleanup target is the new directory reserved above.
	Check(fs::canonical(root).parent_path() == workspace, "cleanup remains in test workspace");
	fs::remove_all(root);
	std::cout << "Windows update transaction checks: " << Checks << ", failures: " << Failures << std::endl;
	return Failures ? 1 : 0;
}
