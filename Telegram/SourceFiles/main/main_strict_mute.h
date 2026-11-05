/*
This file is part of Telegram Desktop,
the official desktop application for the Telegram messaging service.

For license and copyright information please follow this link:
https://github.com/telegramdesktop/tdesktop/blob/master/LEGAL
*/
#pragma once

#include "base/flat_map.h"
#include "base/flat_set.h"
#include "data/data_peer_id.h"
#include <rpl/event_stream.h>

class PeerData;

namespace Main {

class Session;

// Local attention policy. Never changes server mute or read state.
class StrictMute final {
public:
	explicit StrictMute(not_null<Session*> session);
	void start();

	[[nodiscard]] bool contains(PeerId peer) const;
	[[nodiscard]] uint64 anchor(PeerId peer) const;
	[[nodiscard]] const base::flat_map<PeerId, uint64> &entries() const;
	[[nodiscard]] rpl::producer<PeerId> changes() const;

	void set(not_null<PeerData*> peer, bool enabled);

private:
	void save();
	void refresh(PeerId peer);
	void migrate(not_null<PeerData*> peer);
	void hydrate(PeerId peer);
	void refreshConnection();

	const not_null<Session*> _session;
	base::flat_map<PeerId, uint64> _entries;
	base::flat_set<PeerId> _hydrationRequested;
	bool _connected = false;
	rpl::event_stream<PeerId> _changes;
	rpl::lifetime _lifetime;
};

[[nodiscard]] bool CanStrictMute(not_null<const PeerData*> peer);
[[nodiscard]] bool IsStrictMuted(not_null<const PeerData*> peer);
[[nodiscard]] uint64 StrictMuteAnchor(not_null<const PeerData*> peer);

} // namespace Main
