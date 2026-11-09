/*
This file is part of Telegram Desktop.
For license and copyright information see https://github.com/telegramdesktop/tdesktop/blob/master/LEGAL
*/
#pragma once

#include <QtCore/QString>
#include <QtCore/QByteArray>
#include <optional>

namespace Core::ForkUpdates {

inline constexpr auto kVersionFileMarker = quint32(0x7FFFFFFD);
[[nodiscard]] quint32 BuildCounter();
[[nodiscard]] QString VersionSuffix();
[[nodiscard]] QString FeedUrl();
[[nodiscard]] QByteArray UserAgent();
[[nodiscard]] QString ReleasesUrl();

struct Release {
	quint32 baseVersion = 0;
	quint32 build = 0;
	QString version;
	QString commit;
	QString tag;
	QString filename;
	QString sha256;
	quint32 size = 0;

	[[nodiscard]] bool newerThan(quint32 base, quint32 counter) const;
	[[nodiscard]] QString downloadUrl() const;
};

// The root signature is verified before interpreting release metadata.
// The downloaded v2 envelope is independently authenticated by the native
// verifier before decompression or file extraction.
[[nodiscard]] std::optional<Release> ParseFeed(
	const QByteArray &response,
	const QByteArray &rootPublicKey,
	QString *error = nullptr);
[[nodiscard]] QString ReadyVersion(const QString &workingDirectory);

} // namespace Core::ForkUpdates
