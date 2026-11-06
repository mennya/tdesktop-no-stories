/*
This file is part of Telegram Desktop,
the official desktop application for the Telegram messaging service.

For license and copyright information please follow this link:
https://github.com/telegramdesktop/tdesktop/blob/master/LEGAL
*/
#include "main/main_strict_mute.h"

#include "main/main_session.h"
#include "storage/storage_account.h"
#include "data/data_peer.h"
#include "data/data_chat.h"
#include "data/data_channel.h"
#include "data/data_session.h"
#include "data/data_changes.h"
#include "data/data_chat_filters.h"
#include "data/data_histories.h"
#include "data/data_forum.h"
#include "data/data_forum_topic.h"
#include "dialogs/dialogs_main_list.h"
#include "dialogs/dialogs_indexed_list.h"
#include "dialogs/dialogs_row.h"
#include "core/application.h"
#include "core/core_settings.h"
#include "mtproto/mtp_instance.h"
#include "mtproto/facade.h"
#include "base/weak_ptr.h"
#include "history/history.h"

#include <QtCore/QJsonDocument>
#include <QtCore/QJsonObject>

namespace Main {
namespace {

constexpr auto kPreference = "fork.strict-mute.v1";

} // namespace

StrictMute::StrictMute(not_null<Session*> session)
: _session(session) {
	// Account prefs are decrypted before Session construction. Load before
	// Data::Session so the first dialog paint/order already sees this policy.
	const auto json = QJsonDocument::fromJson(
		session->local().readPref<QString>(kPreference).toUtf8()).object();
	if (json.value(u"version"_q).toInt() != 1) {
		return;
	}
	const auto peers = json.value(u"peers"_q).toObject();
	for (auto i = peers.begin(); i != peers.end(); ++i) {
		auto peerOk = false;
		auto anchorOk = false;
		const auto serialized = i.key().toULongLong(&peerOk);
		const auto sortKey = i.value().toString().toULongLong(&anchorOk);
		const auto peer = DeserializePeerId(serialized);
		if (peerOk && anchorOk && peer && sortKey
			&& (peerIsUser(peer) || peerIsChat(peer) || peerIsChannel(peer))
			&& !(sortKey & 0x8000000000000000ULL)) {
			_entries.emplace(peer, sortKey);
		}
	}
}

void StrictMute::start() {
	_session->changes().peerUpdates(
		Data::PeerUpdate::Flag::Migration
		| Data::PeerUpdate::Flag::FullInfo
		| Data::PeerUpdate::Flag::Name
	) | rpl::on_next([=](const Data::PeerUpdate &update) {
		migrate(update.peer);
		hydrate(update.peer->migrateToOrMe()->id);
	}, _lifetime);
	Core::App().settings().proxy().connectionTypeChanges(
	) | rpl::on_next([=] {
		refreshConnection();
	}, _lifetime);
	// Data::Session is fully constructed before issuing any dialog requests.
	crl::on_main(_session, [=] {
		refreshConnection();
	});
}

void StrictMute::refreshConnection() {
	const auto connected = (_session->mtp().dcstate() == MTP::ConnectedState);
	if (std::exchange(_connected, connected) == connected || !connected) {
		return;
	}
	_hydrationRequested.clear();
	// Migration can replace keys; never iterate the map while mutating it.
	const auto entries = _entries;
	for (const auto &[id, key] : entries) {
		if (const auto peer = _session->data().peerLoaded(id)) {
			migrate(peer);
			hydrate(peer->migrateToOrMe()->id);
		}
	}
}

void StrictMute::hydrate(PeerId id) {
	if (!_connected || !contains(id) || _hydrationRequested.contains(id)) {
		return;
	}
	const auto peer = _session->data().peerLoaded(id);
	if (!peer || !peer->isLoaded()) {
		// Retry when normal updates supply metadata/access hashes. Never
		// fabricate an inputPeer or fetch unrelated chats just for a badge.
		return;
	}
	_hydrationRequested.emplace(id);
	const auto weak = base::make_weak(_session.get());
	_session->data().histories().requestDialogEntry(
		_session->data().history(peer),
		[=] {
			if (weak) {
				// Also fires after failure. Projection keeps unknown counts
				// hidden; this is invalidation, not evidence of hydration.
				refresh(id);
			}
		});
}

bool StrictMute::contains(PeerId peer) const {
	return _entries.contains(peer);
}

uint64 StrictMute::anchor(PeerId peer) const {
	const auto i = _entries.find(peer);
	return (i != end(_entries)) ? i->second : 0;
}

const base::flat_map<PeerId, uint64> &StrictMute::entries() const {
	return _entries;
}

rpl::producer<PeerId> StrictMute::changes() const {
	return _changes.events();
}

void StrictMute::save() {
	auto peers = QJsonObject();
	for (const auto &[peer, anchor] : _entries) {
		// Decimal strings preserve all 64 bits; JSON numbers do not.
		peers.insert(
			QString::number(SerializePeerId(peer)),
			QString::number(anchor));
	}
	_session->local().writePref<QString>(kPreference, QString::fromUtf8(
		QJsonDocument(QJsonObject{
			{ u"version"_q, 1 },
			{ u"peers"_q, peers },
		}).toJson(QJsonDocument::Compact)));
}

void StrictMute::refresh(PeerId peer) {
	_changes.fire_copy(peer);
	if (const auto history = _session->data().historyLoaded(peer)) {
		history->updateChatListSortPosition();
		history->updateChatListEntry();
		_session->data().chatsFilters().refreshHistory(history);
		_session->changes().historyUpdated(
			history,
			Data::HistoryUpdate::Flag::UnreadView);
		if (const auto forum = history->peer->forum()) {
			for (const auto &row : forum->topicsList()->indexed()->all()) {
				if (const auto topic = row->topic()) {
					topic->updateChatListEntry();
					_session->changes().topicUpdated(
						topic,
						Data::TopicUpdate::Flag::UnreadView);
				}
			}
		}
	}
}

void StrictMute::set(not_null<PeerData*> peer, bool enabled) {
	peer = peer->migrateToOrMe();
	if (!CanStrictMute(peer)) {
		return;
	}
	migrate(peer);
	if (contains(peer->id) == enabled) {
		return;
	}
	if (enabled) {
		const auto history = _session->data().history(peer);
		_entries.emplace(peer->id, history->chronologicalSortKey());
	} else {
		_entries.remove(peer->id);
	}
	save();
	refresh(peer->id);
	if (enabled) {
		hydrate(peer->id);
	}
}

void StrictMute::migrate(not_null<PeerData*> peer) {
	const auto target = peer->migrateToOrMe();
	const auto previous = target->migrateFrom();
	if (!previous || !contains(previous->id)) {
		return;
	}
	const auto key = anchor(previous->id);
	_entries.emplace(target->id, key);
	_entries.remove(previous->id);
	save();
	refresh(previous->id);
	refresh(target->id);
}

bool CanStrictMute(not_null<const PeerData*> peer) {
	return (peer->isUser()
			&& !peer->isSelf()
			&& !peer->isBot()
			&& !peer->isServiceUser()
			&& !peer->isNotificationsUser()
			&& !peer->isRepliesChat()
			&& !peer->isVerifyCodes()
			&& !peer->isFreezeAppealChat()
			&& !peer->isSavedHiddenAuthor())
		|| peer->isChat()
		|| peer->isMegagroup();
}

uint64 StrictMuteAnchor(not_null<const PeerData*> peer) {
	const auto &policy = peer->session().strictMute();
	const auto target = peer->migrateToOrMe();
	if (const auto key = policy.anchor(target->id)) {
		return key;
	}
	if (const auto previous = target->migrateFrom()) {
		return policy.anchor(previous->id);
	}
	return 0;
}

bool IsStrictMuted(not_null<const PeerData*> peer) {
	return StrictMuteAnchor(peer) != 0;
}

} // namespace Main
