/*
This file is part of Telegram Desktop.
For license and copyright information see https://github.com/telegramdesktop/tdesktop/blob/master/LEGAL
*/
#include "core/fork_update.h"

#include "core/update_verify.h"
#ifdef TDESKTOP_FORK_AUTOUPDATE
#include "fork_update_build.h"
#endif

#include <QtCore/QFile>
#include <QtCore/QJsonDocument>
#include <QtCore/QJsonObject>
#include <QtCore/QRegularExpression>
#include <limits>

namespace Core::ForkUpdates {
namespace {

constexpr auto kMaxFeedSize = 64 * 1024;

void Fail(QString *error, const char *text) {
	if (error) {
		*error = QString::fromLatin1(text);
	}
}

std::optional<quint32> Integer(const QJsonValue &value) {
	if (!value.isDouble()) {
		return std::nullopt;
	}
	const auto number = value.toDouble();
	if (!(number > 0.) || number > std::numeric_limits<quint32>::max()) {
		return std::nullopt;
	}
	const auto result = quint32(number);
	return (double(result) == number) ? std::optional(result) : std::nullopt;
}

} // namespace

quint32 BuildCounter() {
#ifdef TDESKTOP_FORK_AUTOUPDATE
	return ForkUpdateBuildCounter;
#else
	return 0;
#endif
}

QString VersionSuffix() {
	return QStringLiteral(" fork #%1").arg(BuildCounter());
}

QString ReleasesUrl() {
	return QStringLiteral("https://github.com/mennya/tdesktop-no-stories/releases");
}

QString FeedUrl() {
	return ReleasesUrl() + QStringLiteral("/latest/download/fork-update.json");
}

bool Release::newerThan(quint32 base, quint32 counter) const {
	return Updates::MakeUpdateVersion(baseVersion, build)
		> Updates::MakeUpdateVersion(base, counter);
}

QString Release::downloadUrl() const {
	return ReleasesUrl() + QStringLiteral("/download/") + tag + '/' + filename;
}

std::optional<Release> ParseFeed(
		const QByteArray &response,
		const QByteArray &rootPublicKey,
		QString *error) {
	if (response.isEmpty() || response.size() > kMaxFeedSize) {
		Fail(error, "Bad fork feed size.");
		return std::nullopt;
	}
	const auto outer = QJsonDocument::fromJson(response);
	if (!outer.isObject()) {
		Fail(error, "Bad fork feed document.");
		return std::nullopt;
	}
	const auto wrapper = outer.object();
	const auto bytes = QByteArray::fromBase64(
		wrapper.value(QStringLiteral("data")).toString().toLatin1(),
		QByteArray::AbortOnBase64DecodingErrors);
	const auto signature = QByteArray::fromBase64(
		wrapper.value(QStringLiteral("signature")).toString().toLatin1(),
		QByteArray::AbortOnBase64DecodingErrors);
	if (!Updates::ParseVerifiedManifest(bytes, signature, rootPublicKey, error)) {
		return std::nullopt;
	}
	const auto object = QJsonDocument::fromJson(bytes).object()
		.value(QStringLiteral("release")).toObject();
	const auto base = Integer(object.value(QStringLiteral("base_version")));
	const auto build = Integer(object.value(QStringLiteral("build")));
	const auto size = Integer(object.value(QStringLiteral("size")));
	const auto version = object.value(QStringLiteral("version")).toString();
	const auto match = QRegularExpression(
		QStringLiteral("^([0-9]{1,3})\\.([0-9]{1,3})\\.([0-9]{1,3})$")
	).match(version);
	if (object.value(QStringLiteral("product")).toString()
			!= QStringLiteral("telegram-no-stories")
		|| object.value(QStringLiteral("platform")).toString()
			!= QStringLiteral("windows-x64")
		|| !base || !build || !size || *size > Updates::kMaxPayloadSize
		|| !match.hasMatch()
		|| *base != (match.captured(1).toUInt() * 1000000
			+ match.captured(2).toUInt() * 1000
			+ match.captured(3).toUInt())) {
		Fail(error, "Bad fork release identity.");
		return std::nullopt;
	}
	auto result = Release();
	result.baseVersion = *base;
	result.build = *build;
	result.size = *size;
	result.version = version;
	result.commit = object.value(QStringLiteral("commit")).toString();
	result.sha256 = object.value(QStringLiteral("sha256")).toString();
	result.tag = object.value(QStringLiteral("tag")).toString();
	result.filename = object.value(QStringLiteral("filename")).toString();
	if (!QRegularExpression(QStringLiteral("^[0-9a-f]{40}$"))
			.match(result.commit).hasMatch()
		|| !QRegularExpression(QStringLiteral("^[0-9a-f]{64}$"))
			.match(result.sha256).hasMatch()
		|| result.tag != QStringLiteral("fork-v%1-b%2").arg(version).arg(*build)
		|| result.filename != QStringLiteral("td-update-win-x64-%1-fork-%2")
			.arg(*base).arg(*build)) {
		Fail(error, "Bad fork release coordinates.");
		return std::nullopt;
	}
	return result;
}

QString ReadyVersion(const QString &workingDirectory) {
	auto file = QFile(workingDirectory + QStringLiteral("tupdates/temp/build-info.json"));
	if (!file.open(QIODevice::ReadOnly) || file.size() > 4096) {
		return QString();
	}
	const auto object = QJsonDocument::fromJson(file.readAll()).object();
	const auto version = object.value(QStringLiteral("version")).toString();
	const auto build = Integer(object.value(QStringLiteral("fork_build")));
	if (!build || !QRegularExpression(QStringLiteral("^[0-9]{1,3}\\.[0-9]{1,3}\\.[0-9]{1,3}$"))
			.match(version).hasMatch()) {
		return QString();
	}
	return version + QStringLiteral(" fork #%1").arg(*build);
}

} // namespace Core::ForkUpdates
