/*
This file is part of Telegram Desktop.
For license and copyright information see https://github.com/telegramdesktop/tdesktop/blob/master/LEGAL
*/
#include "core/fork_update.h"
#include "core/update_keys.h"
#include "core/update_verify.h"
#include "core/update_unpack.h"
#include <QtCore/QCoreApplication>
#include <QtCore/QCryptographicHash>
#include <QtCore/QDataStream>
#include <QtCore/QDateTime>
#include <QtCore/QDir>
#include <QtCore/QFile>
#include <QtCore/QJsonArray>
#include <QtCore/QJsonDocument>
#include <QtCore/QJsonObject>
#include <QtCore/QTemporaryDir>
#include <openssl/evp.h>
#include <openssl/pem.h>
#include <iostream>
#include <memory>

namespace {
using namespace Core::Updates;
int Failures = 0;
int Checks = 0;

void Check(bool passed, const char *message) {
	++Checks;
	if (!passed) {
		++Failures;
		std::cerr << "FAILED: " << message << std::endl;
	}
}

struct Key {
	EVP_PKEY *pair = nullptr;
	Key() {
		const auto context = EVP_PKEY_CTX_new_id(EVP_PKEY_ED25519, nullptr);
		if (context) {
			if (EVP_PKEY_keygen_init(context) == 1) {
				EVP_PKEY_keygen(context, &pair);
			}
			EVP_PKEY_CTX_free(context);
		}
	}
	~Key() { EVP_PKEY_free(pair); }
	QByteArray publicPem() const {
		const auto bio = BIO_new(BIO_s_mem());
		PEM_write_bio_PUBKEY(bio, pair);
		char *data = nullptr;
		const auto size = BIO_get_mem_data(bio, &data);
		const auto result = QByteArray(data, int(size));
		BIO_free(bio);
		return result;
	}
	QByteArray rawPublic() const {
		auto result = QByteArray(32, '\0');
		auto size = size_t(result.size());
		EVP_PKEY_get_raw_public_key(pair, reinterpret_cast<unsigned char*>(result.data()), &size);
		return result;
	}
	QByteArray sign(const QByteArray &data) const {
		auto result = QByteArray(64, '\0');
		auto size = size_t(result.size());
		const auto context = EVP_MD_CTX_new();
		const auto ok = context
			&& EVP_DigestSignInit(context, nullptr, nullptr, nullptr, pair) == 1
			&& EVP_DigestSign(context, reinterpret_cast<unsigned char*>(result.data()), &size,
				reinterpret_cast<const unsigned char*>(data.constData()), size_t(data.size())) == 1;
		EVP_MD_CTX_free(context);
		return ok ? result : QByteArray();
	}
};

QJsonObject Manifest(const Key &key) {
	const auto entry = QJsonObject{
		{QStringLiteral("id"), QStringLiteral("test-key")},
		{QStringLiteral("alg"), QStringLiteral("Ed25519")},
		{QStringLiteral("x"), QString::fromLatin1(key.rawPublic().toBase64(
			QByteArray::Base64UrlEncoding | QByteArray::OmitTrailingEquals))},
	};
	// Append explicitly: nested single-element braced QJsonArray construction
	// may select the copy constructor on MSVC instead of wrapping the group.
	auto groups = QJsonArray();
	groups.append(QJsonArray{QStringLiteral("test-key")});
	return {
		{QStringLiteral("format"), 1}, {QStringLiteral("manifest_version"), 1},
		{QStringLiteral("keys"), QJsonArray{entry}},
		{QStringLiteral("channels"), QJsonObject{{QStringLiteral("stable"), groups}}},
		{QStringLiteral("revoked"), QJsonArray{}},
	};
}

QJsonObject Release() {
	return {
		{QStringLiteral("product"), QStringLiteral("telegram-no-stories")},
		{QStringLiteral("platform"), QStringLiteral("windows-x64")},
		{QStringLiteral("version"), QStringLiteral("7.4.1")},
		{QStringLiteral("base_version"), 7004001}, {QStringLiteral("build"), 20010},
		{QStringLiteral("commit"), QString(40, QChar('a'))},
		{QStringLiteral("sha256"), QString(64, QChar('b'))},
		{QStringLiteral("size"), 1024},
		{QStringLiteral("tag"), QStringLiteral("fork-v7.4.1-b20010")},
		{QStringLiteral("filename"), QStringLiteral("td-update-win-x64-7004001-fork-20010")},
	};
}

QByteArray Feed(const Key &key, QJsonObject release) {
	auto manifest = Manifest(key);
	manifest.insert(QStringLiteral("release"), release);
	const auto bytes = QJsonDocument(manifest).toJson(QJsonDocument::Compact);
	return QJsonDocument(QJsonObject{
		{QStringLiteral("data"), QString::fromLatin1(bytes.toBase64())},
		{QStringLiteral("signature"), QString::fromLatin1(key.sign(bytes).toBase64())},
	}).toJson(QJsonDocument::Compact);
}

void U32(QByteArray &to, quint32 value) {
	for (auto i = 0; i != 4; ++i) { to.append(char((value >> (i * 8)) & 255)); }
}
void U64(QByteArray &to, quint64 value) {
	for (auto i = 0; i != 8; ++i) { to.append(char((value >> (i * 8)) & 255)); }
}
void Bytes(QByteArray &to, const QByteArray &value) {
	U32(to, quint32(value.size())); to += value;
}

QByteArray Envelope(const Key &key, Target target, quint64 version) {
	const auto manifest = QJsonDocument(Manifest(key)).toJson(QJsonDocument::Compact);
	auto result = QByteArray("TDUP");
	U32(result, 2);
	result.append(char(Channel::Stable)).append(char(target.os)).append(char(target.arch));
	U64(result, version);
	U64(result, quint64(QDateTime::currentSecsSinceEpoch()));
	Bytes(result, manifest);
	const auto payload = QByteArray("authenticated test payload");
	const auto signature = key.sign(result + QCryptographicHash::hash(payload, QCryptographicHash::Sha256));
	Bytes(result, key.sign(manifest));
	U32(result, 1);
	Bytes(result, QByteArray("test-key"));
	Bytes(result, signature);
	Bytes(result, payload);
	return result;
}

void Units() {
	const auto key = Key();
	Check(key.pair != nullptr, "test Ed25519 key generated");
	if (!key.pair) { return; }
	const auto good = Feed(key, Release());
	auto feedError = QString();
	const auto parsed = Core::ForkUpdates::ParseFeed(good, key.publicPem(), &feedError);
	Check(parsed.has_value(), "root-authenticated fork feed accepted");
	if (!parsed) { std::cerr << "Feed diagnostic: " << feedError.toStdString() << std::endl; }
	if (parsed) {
		Check(parsed->newerThan(7004001, 20000), "same Telegram version, newer fork build");
		Check(!parsed->newerThan(7004001, 20010), "same fork build not offered again");
		Check(!parsed->newerThan(7004001, 20020), "older fork build not offered");
		Check(!parsed->newerThan(7004002, 1), "upstream version cannot downgrade");
		Check(parsed->downloadUrl() == QStringLiteral(
			"https://github.com/mennya/tdesktop-no-stories/releases/download/fork-v7.4.1-b20010/td-update-win-x64-7004001-fork-20010"), "fixed repository download URL");
	}
	const auto other = Key();
	Check(!Core::ForkUpdates::ParseFeed(good, other.publicPem()), "different root rejected");
	Check(!Core::ForkUpdates::ParseFeed(QByteArray(65537, 'a'), key.publicPem()), "oversized feed rejected");
	Check(!Core::ForkUpdates::ParseFeed(QByteArray("7004001:https://desktop.telegram.org"), key.publicPem()), "legacy official feed rejected");
	auto changed = good;
	changed[changed.size() / 3] = changed[changed.size() / 3] == 'a' ? 'b' : 'a';
	Check(!Core::ForkUpdates::ParseFeed(changed, key.publicPem()), "modified signed feed rejected");
	for (const auto &field : {QStringLiteral("product"), QStringLiteral("platform"),
			QStringLiteral("version"), QStringLiteral("commit"), QStringLiteral("sha256"),
			QStringLiteral("tag"), QStringLiteral("filename")}) {
		auto release = Release();
		release.insert(field, QStringLiteral("../unexpected"));
		Check(!Core::ForkUpdates::ParseFeed(Feed(key, release), key.publicPem()), "signed malformed release field rejected");
	}
	for (const auto &field : {QStringLiteral("base_version"), QStringLiteral("build"), QStringLiteral("size")}) {
		for (const auto number : {0., -1., 1.5, 4294967296.}) {
			auto release = Release();
			release.insert(field, number);
			Check(!Core::ForkUpdates::ParseFeed(Feed(key, release), key.publicPem()), "invalid release integer rejected");
		}
	}
	const auto target = Target{Os::Windows, Arch::X64};
	const auto running = MakeUpdateVersion(7004001, 20000);
	const auto version = MakeUpdateVersion(7004001, 20010);
	const auto blob = Envelope(key, target, version);
	auto verifyError = QString();
	const auto verify = [&](const QByteArray &data, quint64 current) {
		return VerifyUpdate(data, Channel::Stable, false, target, current,
			std::nullopt, key.publicPem(), QDateTime::currentSecsSinceEpoch(), &verifyError);
	};
	const auto verified = verify(blob, running);
	Check(verified.has_value(), "native verifier accepts signed fork revision");
	if (!verified) { std::cerr << "Envelope diagnostic: " << verifyError.toStdString() << std::endl; }
	Check(!verify(blob, version), "native verifier rejects replay");
	auto corrupt = blob;
	corrupt[corrupt.size() - 1] ^= 1;
	Check(!verify(corrupt, running), "native verifier rejects damaged payload");
	Check(!verify(Envelope(key, Target{Os::Windows, Arch::Arm}, version), running), "native verifier rejects other architecture");
	for (const auto &name : {QStringLiteral("Telegram.exe"), QStringLiteral("TelegramForcePortable/tdata/key_data"),
			QStringLiteral("tdata/settings"), QStringLiteral("../Telegram.exe")}) {
		auto payload = QByteArray();
		auto stream = QDataStream(&payload, QIODevice::WriteOnly);
		stream.setVersion(QDataStream::Qt_5_1);
		stream << quint32(7004001) << quint32(1) << name << quint32(3) << QByteArray("abc");
#ifndef Q_OS_WIN
		stream << false;
#endif
		auto temporary = QTemporaryDir();
		const auto accepted = ExtractUpdateFiles(payload, version, temporary.path());
		Check(accepted == (name == QStringLiteral("Telegram.exe")), "native extraction excludes account data and traversal");
	}
}

QByteArray Read(const QString &path, qint64 cap) {
	auto file = QFile(path);
	if (!file.open(QIODevice::ReadOnly) || file.size() > cap) { return {}; }
	return file.readAll();
}

int VerifyRelease(const QString &directory, const QString &commit) {
	auto error = QString();
	const auto release = Core::ForkUpdates::ParseFeed(
		Read(QDir(directory).filePath(QStringLiteral("fork-update.json")), 65536), RootPublicKeyPem(), &error);
	Check(release.has_value(), "published feed verifies against embedded fork root");
	if (!release) { return 1; }
	Check(release->commit == commit, "feed matches exact production source commit");
	const auto package = Read(QDir(directory).filePath(release->filename), kMaxPayloadSize + 512 * 1024);
	Check(package.size() == release->size, "package matches signed feed size");
	Check(QString::fromLatin1(QCryptographicHash::hash(package, QCryptographicHash::Sha256).toHex())
		== release->sha256, "package matches signed feed SHA256");
	const auto embedded = ParseVerifiedManifest(EmbeddedManifest(), EmbeddedManifestSignature(), RootPublicKeyPem());
	const auto verified = VerifyUpdate(package, Channel::Stable, false,
		Target{Os::Windows, Arch::X64}, 0, embedded, RootPublicKeyPem(), QDateTime::currentSecsSinceEpoch(), &error);
	Check(verified.has_value(), "native verifier authenticates Windows x64 envelope");
	if (!verified) { return 1; }
	Check(verified->envelope.version == MakeUpdateVersion(release->baseVersion, release->build), "feed and package revision agree");
	const auto payload = DecompressUpdatePayload(*verified, &error);
	Check(payload.has_value(), "native Windows LZMA decompression succeeds");
	if (!payload) { return 1; }
	auto temporary = QTemporaryDir();
	const auto extracted = ExtractUpdateFiles(*payload, verified->envelope.version, temporary.path(), &error);
	Check(extracted, "native extraction accepts only fork program files");
	if (!extracted) { return 1; }
	const auto info = QJsonDocument::fromJson(Read(QDir(temporary.path()).filePath(QStringLiteral("build-info.json")), 4096)).object();
	Check(info.value(QStringLiteral("commit")).toString() == commit, "payload manifest matches exact commit");
	Check(info.value(QStringLiteral("build_kind")).toString() == QStringLiteral("production"), "payload is production");
	Check(info.value(QStringLiteral("platform")).toString() == QStringLiteral("windows-x64"), "payload is Windows x64");
	Check(info.value(QStringLiteral("version")).toString() == release->version, "payload application version matches feed");
	Check(info.value(QStringLiteral("fork_build")).toDouble() == double(release->build), "payload fork revision matches feed");
	for (const auto &name : {QStringLiteral("Telegram.exe"), QStringLiteral("Updater.exe")}) {
		const auto bytes = Read(QDir(temporary.path()).filePath(name), 1024 * 1024 * 1024);
		const auto field = (name == QStringLiteral("Telegram.exe")) ? QStringLiteral("executable_sha256") : QStringLiteral("updater_sha256");
		Check(QString::fromLatin1(QCryptographicHash::hash(bytes, QCryptographicHash::Sha256).toHex())
			== info.value(field).toString(), "payload executable matches build manifest hash");
	}
	return Failures ? 1 : 0;
}
} // namespace

int main(int argc, char **argv) {
	const auto application = QCoreApplication(argc, argv);
	if (argc == 4 && QByteArray(argv[1]) == "--verify-release") {
		const auto result = VerifyRelease(QString::fromLocal8Bit(argv[2]), QString::fromLatin1(argv[3]));
		std::cout << "Native signed-release checks: " << Checks << ", failures: " << Failures << std::endl;
		return result;
	}
	Units();
	std::cout << "Fork updater checks: " << Checks << ", failures: " << Failures << std::endl;
	return Failures ? 1 : 0;
}
