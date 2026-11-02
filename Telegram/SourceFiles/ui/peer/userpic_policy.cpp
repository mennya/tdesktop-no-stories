/*
This file is part of Telegram Desktop,
the official desktop application for the Telegram messaging service.

For license and copyright information please follow this link:
https://github.com/telegramdesktop/tdesktop/blob/master/LEGAL
*/
#include "ui/userpic_view.h"

#include "data/data_user.h"

namespace Ui {

bool PersonalUserpicOnly(not_null<const PeerData*> peer) {
	return peer->isUser()
		&& !peer->isSelf()
		&& !peer->isBot()
		&& !peer->isServiceUser()
		&& !peer->isNotificationsUser()
		&& !peer->isRepliesChat()
		&& !peer->isVerifyCodes()
		&& !peer->isFreezeAppealChat()
		&& !peer->isSavedHiddenAuthor();
}

bool PeerUserpicPhotoAllowed(not_null<const PeerData*> peer) {
	return !PersonalUserpicOnly(peer) || peer->asUser()->hasPersonalPhoto();
}

} // namespace Ui
