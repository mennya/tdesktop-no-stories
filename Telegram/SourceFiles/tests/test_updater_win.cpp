/*
This file is part of Telegram Desktop,
the official desktop application for the Telegram messaging service.

For license and copyright information please follow this link:
https://github.com/telegramdesktop/tdesktop/blob/master/LEGAL
*/
#include "_other/updater.h"

#include <sddl.h>

#include <filesystem>
#include <fstream>
#include <iostream>
#include <limits>
#include <memory>
#include <vector>

namespace {

using Handle = std::unique_ptr<void, decltype(&CloseHandle)>;

auto Failures = 0;

void Check(bool condition, const char *name) {
	if (!condition) {
		++Failures;
		std::cerr << "FAILED: " << name << std::endl;
	}
}

ULONGLONG CreationTime(HANDLE process) {
	auto created = FILETIME();
	auto exited = FILETIME();
	auto kernel = FILETIME();
	auto user = FILETIME();
	const auto result = GetProcessTimes(
		process,
		&created,
		&exited,
		&kernel,
		&user);
	Check(result != FALSE, "read test process identity");
	return (ULONGLONG(created.dwHighDateTime) << 32) | created.dwLowDateTime;
}

void TestArguments() {
	auto id = DWORD(0);
	auto created = ULONGLONG(0);
	Check(
		ParseUpdateProcess(L"1234", L"134000000000000000", id, created),
		"accept launcher identity");
	Check(
		id == 1234 && created == 134000000000000000ULL,
		"preserve full creation time");
	Check(
		ParseUpdateProcess(L"4294967295", L"18446744073709551615", id, created),
		"accept representable upper bounds");
	Check(
		id == std::numeric_limits<DWORD>::max()
			&& created == std::numeric_limits<ULONGLONG>::max(),
		"preserve upper bounds");
	const auto invalid = {
		L"", L"0", L"-1", L"+1", L" 1", L"1 ", L"1x", L"1.0",
		L"18446744073709551616", L"999999999999999999999999999999",
	};
	for (const auto value : invalid) {
		id = 17;
		created = 19;
		Check(
			!ParseUpdateProcess(value, L"1", id, created),
			"reject malformed process id");
		Check(
			!ParseUpdateProcess(L"1", value, id, created),
			"reject malformed creation time");
		Check(id == 17 && created == 19, "failed parse preserves outputs");
	}
	Check(
		!ParseUpdateProcess(L"4294967296", L"1", id, created),
		"reject process id overflow");
}

void TestErrors() {
	const auto message = wstring(8192, L'x') + L"\u4e2d\u6587";
	const auto text = FormatUpdateError(message, ERROR_SHARING_VIOLATION);
	Check(text.starts_with(message), "preserve long Unicode error context");
	Check(
		text.find(L"Error code: 32") != wstring::npos,
		"report original numeric error");
	const auto unknown = FormatUpdateError(L"test", 0xE0000001);
	Check(
		unknown.find(L"3758096385") != wstring::npos,
		"format unsigned error code");
	Check(
		unknown.find(L"(Unknown error)") != wstring::npos,
		"handle unavailable system error description");
}

void TestRelaunchArguments() {
	Check(
		UpdateRelaunchArguments({}) == L"-noupdate",
		"default relaunch arguments");
	for (auto flags = 0; flags != 8; ++flags) {
		const auto options = UpdateRelaunchOptions{
			.autostart = bool(flags & 1),
			.debug = bool(flags & 2),
			.startInTray = bool(flags & 4),
			.workingDirectory = L"C:\\Profile with spaces \u0416\\",
			.keyFile = LR"(custom "key" \)",
		};
		auto expected = std::vector<wstring>{ L"-noupdate" };
		if (options.autostart) {
			expected.push_back(L"-autostart");
		}
		if (options.debug) {
			expected.push_back(L"-debug");
		}
		if (options.startInTray) {
			expected.push_back(L"-startintray");
		}
		expected.insert(expected.end(), {
			L"-workdir", options.workingDirectory, L"-key", options.keyFile,
		});
		const auto command = L"probe.exe " + UpdateRelaunchArguments(options);
		auto count = 0;
		const auto arguments = CommandLineToArgvW(command.c_str(), &count);
		const auto guard = std::unique_ptr<void, decltype(&LocalFree)>(
			arguments,
			&LocalFree);
		Check(
			arguments && count == int(expected.size()) + 1,
			"parse relaunch argument count");
		if (arguments && count == int(expected.size()) + 1) {
			for (auto i = 0; i != int(expected.size()); ++i) {
				Check(
					arguments[i + 1] == expected[i],
					"preserve relaunch flags, Unicode and quoting");
			}
		}
	}
}

struct ProbeReport {
	DWORD processId = 0;
	ULONGLONG created = 0;
	std::vector<wstring> values;
};

bool WriteProbeReport(const wchar_t *path, int argc, wchar_t *argv[]) {
	auto directory = wstring(32768, L'\0');
	const auto length = GetCurrentDirectoryW(DWORD(directory.size()), directory.data());
	if (!length || length >= directory.size()) {
		return false;
	}
	directory.resize(length);
	auto values = std::vector<wstring>{ directory };
	for (auto i = 1; i != argc; ++i) {
		values.push_back(argv[i]);
	}
	auto output = std::ofstream(std::filesystem::path(path), std::ios::binary);
	const auto processId = GetCurrentProcessId();
	const auto created = CreationTime(GetCurrentProcess());
	const auto count = DWORD(values.size());
	output.write(reinterpret_cast<const char*>(&processId), sizeof(processId));
	output.write(reinterpret_cast<const char*>(&created), sizeof(created));
	output.write(reinterpret_cast<const char*>(&count), sizeof(count));
	for (const auto &value : values) {
		const auto size = DWORD(value.size());
		output.write(reinterpret_cast<const char*>(&size), sizeof(size));
		output.write(reinterpret_cast<const char*>(value.data()), size * sizeof(wchar_t));
	}
	output.close();
	return bool(output);
}

ProbeReport ReadProbeReport(const std::filesystem::path &path) {
	auto result = ProbeReport();
	auto input = std::ifstream(path, std::ios::binary);
	auto count = DWORD(0);
	input.read(reinterpret_cast<char*>(&result.processId), sizeof(result.processId));
	input.read(reinterpret_cast<char*>(&result.created), sizeof(result.created));
	input.read(reinterpret_cast<char*>(&count), sizeof(count));
	if (!input || count > 32) {
		Check(false, "read owned launch probe report header");
		return result;
	}
	for (auto i = DWORD(0); i != count; ++i) {
		auto size = DWORD(0);
		input.read(reinterpret_cast<char*>(&size), sizeof(size));
		if (!input || size > 32768) {
			Check(false, "read bounded launch probe value");
			return result;
		}
		auto value = wstring(size, L'\0');
		input.read(reinterpret_cast<char*>(value.data()), size * sizeof(wchar_t));
		if (!input) {
			Check(false, "read complete launch probe value");
			return result;
		}
		result.values.push_back(std::move(value));
	}
	return result;
}

int RunRelaunchProbe(int argc, wchar_t *argv[]) {
	if (argc != 11 || wstring(argv[9]) != L"--probe-report") {
		return ERROR_INVALID_PARAMETER;
	}
	const auto event = Handle(
		OpenEventW(EVENT_MODIFY_STATE, FALSE, argv[8]),
		&CloseHandle);
	const auto finishName = wstring(argv[8]) + L"-finish";
	const auto finish = Handle(
		OpenEventW(SYNCHRONIZE, FALSE, finishName.c_str()),
		&CloseHandle);
	if (!event || !finish || !WriteProbeReport(argv[10], argc, argv)) {
		return ERROR_WRITE_FAULT;
	}
	if (!SetEvent(event.get())) {
		return int(GetLastError());
	}
	return (WaitForSingleObject(finish.get(), 30000) == WAIT_OBJECT_0)
		? 0
		: ERROR_TIMEOUT;
}

void TestRelaunch(const wchar_t *executable) {
	namespace fs = std::filesystem;
	auto temporary = wstring(32768, L'\0');
	const auto length = GetTempPathW(DWORD(temporary.size()), temporary.data());
	Check(length && length < temporary.size(), "get launch fixture root");
	if (!length || length >= temporary.size()) {
		return;
	}
	temporary.resize(length);
	const auto name = L"TelegramUpdaterRelaunch-" + std::to_wstring(GetCurrentProcessId())
		+ L"-" + std::to_wstring(GetTickCount64());
	const auto root = fs::path(temporary) / name;
	const auto reserved = fs::create_directory(root);
	Check(reserved, "reserve owned launch fixture");
	if (!reserved) {
		return;
	}
	const auto cleanup = [&] {
		const auto owned = fs::canonical(root).parent_path() == fs::canonical(temporary)
			&& root.filename().wstring().starts_with(L"TelegramUpdaterRelaunch-");
		Check(owned, "confine fixture cleanup");
		if (owned) {
			auto error = std::error_code();
			fs::remove_all(root, error);
			Check(!error, "remove only owned launch fixture");
		}
	};
	const auto program = root / L"program with spaces \u0416";
	const auto profile = root / L"profile with spaces \u03A9";
	Check(fs::create_directory(program), "create probe program directory");
	Check(fs::create_directory(profile), "create synthetic profile directory");
	const auto target = program / L"Restart probe.exe";
	const auto receipt = root / L"probe.bin";
	const auto marker = profile / L"synthetic-account-marker.txt";
	{
		auto output = std::ofstream(marker);
		output << "preserve synthetic storage";
	}
	Check(fs::copy_file(fs::absolute(executable), target), "copy owned probe executable");
	const auto eventName = L"Local\\" + name;
	const auto finishName = eventName + L"-finish";
	const auto event = Handle(
		CreateEventW(nullptr, TRUE, FALSE, eventName.c_str()),
		&CloseHandle);
	const auto finish = Handle(
		CreateEventW(nullptr, TRUE, FALSE, finishName.c_str()),
		&CloseHandle);
	Check(event && finish, "create owned launch probe events");
	if (!event || !finish) {
		cleanup();
		return;
	}
	auto command = L"\"" + fs::absolute(executable).wstring()
		+ L"\" --relaunch-helper \"" + target.wstring() + L"\" \"" + program.wstring()
		+ L"\" \"" + profile.wstring() + L"\" \"" + eventName + L"\" \"" + receipt.wstring() + L"\"";
	auto startup = STARTUPINFOW();
	startup.cb = sizeof(startup);
	auto information = PROCESS_INFORMATION();
	const auto started = CreateProcessW(
		nullptr,
		command.data(),
		nullptr,
		nullptr,
		FALSE,
		CREATE_NO_WINDOW,
		nullptr,
		nullptr,
		&startup,
		&information);
	Check(started != FALSE, "start owned launcher without message loop");
	auto launcher = Handle(information.hProcess, &CloseHandle);
	auto thread = Handle(information.hThread, &CloseHandle);
	if (started) {
		Check(
			WaitForSingleObject(launcher.get(), 10000) == WAIT_OBJECT_0,
			"launcher exits immediately after shell call");
		auto code = DWORD(1);
		Check(
			GetExitCodeProcess(launcher.get(), &code) && !code,
			"synchronous shell launch succeeds");
		if (WaitForSingleObject(event.get(), 10000) == WAIT_OBJECT_0) {
			const auto report = ReadProbeReport(receipt);
			const auto expected = std::vector<wstring>{
				L"-noupdate", L"-autostart", L"-debug", L"-startintray",
				L"-workdir", profile.wstring() + L"\\", L"-key", eventName,
				L"--probe-report", receipt.generic_wstring(),
			};
			Check(
				report.values.size() == expected.size() + 1,
				"restarted child reports all arguments");
			if (report.values.size() == expected.size() + 1) {
				Check(
					fs::equivalent(report.values[0], program),
					"use program directory as process cwd");
				for (auto i = size_t(0); i != expected.size(); ++i) {
					Check(
						report.values[i + 1] == expected[i],
						"preserve synthetic profile and relaunch arguments");
				}
			}
			auto probe = Handle(
				OpenProcess(
					SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION,
					FALSE,
					report.processId),
				&CloseHandle);
			Check(
				probe && CreationTime(probe.get()) == report.created,
				"own exact live restarted probe");
			Check(SetEvent(finish.get()) != FALSE, "release owned restarted probe");
			if (probe) {
				Check(
					WaitForSingleObject(probe.get(), 10000) == WAIT_OBJECT_0,
					"restarted probe exits cleanly");
			}
		} else {
			Check(false, "child starts after launcher process has exited");
			Check(SetEvent(finish.get()) != FALSE, "release timed out launch probe");
		}
	}
	Check(
		LaunchUpdatedProcess(
			(program / L"missing.exe").wstring(),
			L"",
			program.wstring()) != ERROR_SUCCESS,
		"propagate failed launch instead of reporting success");
	Check(
		LaunchUpdatedProcess(L"", L"", program.wstring()) == ERROR_INVALID_PARAMETER,
		"refuse an empty executable");
	{
		auto input = std::ifstream(marker);
		auto value = std::string();
		std::getline(input, value);
		Check(
			value == "preserve synthetic storage",
			"relaunch preserves synthetic account marker");
	}
	thread.reset();
	launcher.reset();
	cleanup();
}

void TestProcess(const wchar_t *executable, bool force, bool denyTermination) {
	const auto eventName = L"Local\\TelegramUpdaterTest-"
		+ std::to_wstring(GetCurrentProcessId())
		+ L"-" + std::to_wstring(GetTickCount64());
	const auto event = Handle(
		CreateEvent(nullptr, TRUE, FALSE, eventName.c_str()),
		&CloseHandle);
	Check(event != nullptr, "create test exit event");
	if (!event) {
		return;
	}
	auto command = L"\"" + wstring(executable)
		+ L"\" --child " + eventName;
	auto startup = STARTUPINFO();
	startup.cb = sizeof(startup);
	auto information = PROCESS_INFORMATION();
	const auto started = CreateProcess(
		executable,
		command.data(),
		nullptr,
		nullptr,
		FALSE,
		CREATE_NO_WINDOW,
		nullptr,
		nullptr,
		&startup,
		&information);
	Check(started != FALSE, "start owned test child");
	if (!started) {
		return;
	}
	auto process = Handle(information.hProcess, &CloseHandle);
	auto thread = Handle(information.hThread, &CloseHandle);
	const auto created = CreationTime(process.get());
	Check(
		FinishUpdateProcess(information.dwProcessId, created + 1)
			== ERROR_SUCCESS,
		"ignore reused process id");
	Check(
		WaitForSingleObject(process.get(), 0) == WAIT_TIMEOUT,
		"identity mismatch leaves process running");
	if (denyTermination) {
		auto descriptor = PSECURITY_DESCRIPTOR(nullptr);
		const auto parsed = ConvertStringSecurityDescriptorToSecurityDescriptor(
			L"D:(D;;0x00000001;;;WD)(A;;0x001FFFFF;;;WD)",
			SDDL_REVISION_1,
			&descriptor,
			nullptr);
		const auto guard = std::unique_ptr<void, decltype(&LocalFree)>(
			descriptor,
			&LocalFree);
		Check(parsed != FALSE, "create test process permissions");
		if (parsed) {
			Check(
				SetKernelObjectSecurity(
					process.get(),
					DACL_SECURITY_INFORMATION,
					descriptor) != FALSE,
				"deny termination of test child");
		}
	}
	if (!force) {
		Check(SetEvent(event.get()) != FALSE, "request normal test exit");
	}
	const auto startedAt = GetTickCount64();
	const auto result = FinishUpdateProcess(information.dwProcessId, created);
	if (force) {
		Check(
			GetTickCount64() - startedAt >= 4900,
			"allow normal exit grace period");
	}
	if (force && denyTermination) {
		Check(result == ERROR_ACCESS_DENIED, "report denied termination");
		Check(
			WaitForSingleObject(process.get(), 0) == WAIT_TIMEOUT,
			"denied termination leaves process running");
	} else {
		Check(result == ERROR_SUCCESS, "finish matching process");
		Check(
			WaitForSingleObject(process.get(), 0) == WAIT_OBJECT_0,
			"success guarantees process exited");
		auto code = DWORD(0);
		Check(
			GetExitCodeProcess(process.get(), &code) != FALSE,
			"read test exit code");
		Check(
			code == (force ? ERROR_PROCESS_ABORTED : 37),
			"use forced exit only after timeout");
		Check(
			FinishUpdateProcess(information.dwProcessId, created)
				== ERROR_SUCCESS,
			"accept already exited process");
	}
	Check(SetEvent(event.get()) != FALSE, "release test child");
	Check(
		WaitForSingleObject(process.get(), 35000) == WAIT_OBJECT_0,
		"test child cleanup");
	if (!denyTermination) {
		thread.reset();
		process.reset();
		Check(
			FinishUpdateProcess(information.dwProcessId, created)
				== ERROR_SUCCESS,
			"accept absent process");
	}
}

} // namespace

int wmain(int argc, wchar_t *argv[]) {
	if (argc > 1 && wstring(argv[1]) == L"-noupdate") {
		return RunRelaunchProbe(argc, argv);
	}
	if (argc == 7 && wstring(argv[1]) == L"--relaunch-helper") {
		const auto options = UpdateRelaunchOptions{
			.autostart = true,
			.debug = true,
			.startInTray = true,
			.workingDirectory = std::filesystem::path(argv[4]).wstring() + L"\\",
			.keyFile = argv[5],
		};
		const auto arguments = UpdateRelaunchArguments(options)
			+ L" --probe-report \"" + std::filesystem::path(argv[6]).generic_wstring() + L"\"";
		return int(LaunchUpdatedProcess(argv[2], arguments, argv[3]));
	}
	if (argc == 3 && wstring(argv[1]) == L"--child") {
		const auto event = Handle(
			OpenEvent(SYNCHRONIZE, FALSE, argv[2]),
			&CloseHandle);
		if (!event || WaitForSingleObject(event.get(), 30000) != WAIT_OBJECT_0) {
			return 38;
		}
		Sleep(250);
		return 37;
	}
	TestArguments();
	TestErrors();
	TestRelaunchArguments();
	TestRelaunch(argv[0]);
	Check(
		FinishUpdateProcess(0, 1) == ERROR_INVALID_PARAMETER,
		"reject zero process id");
	Check(
		FinishUpdateProcess(
			GetCurrentProcessId(),
			CreationTime(GetCurrentProcess())) == ERROR_INVALID_PARAMETER,
		"refuse to terminate updater itself");
	TestProcess(argv[0], false, false);
	TestProcess(argv[0], true, false);
	TestProcess(argv[0], false, true);
	TestProcess(argv[0], true, true);
	std::cout << "Updater tests: " << Failures << " failures." << std::endl;
	return Failures ? 1 : 0;
}
