#include <cstdint>
#include <iostream>
#include <memory>
#include <stdexcept>
#include <string>
#include <variant>

using InMemoryKey = std::int64_t;
template <typename T> using not_null = T;
constexpr auto kUserpicSize = 160;
namespace Qt { enum TransformationMode { SmoothTransformation }; }

struct QImage {
	int pixels = 0;
	bool isNull() const { return pixels == 0; }
	QImage scaledToWidth(int, Qt::TransformationMode) const { return *this; }
};
namespace Window { QImage LogoNoMargin() { return { 999 }; } }
struct EmptyUserpic {
	InMemoryKey key = -1;
	InMemoryKey uniqueKey() const { return key; }
};
namespace Ui {
struct PeerUserpicView {
	QImage cached = {};
	std::shared_ptr<QImage> cloud;
};
}

struct MockCloud {
	int id = 0;
	int loads = 0;
	std::weak_ptr<QImage> view;
	bool empty() const { return id == 0; }
	int location() const { return id; }
	std::shared_ptr<QImage> activeView() const { return view.lock(); }
	std::shared_ptr<QImage> createView() {
		if (auto active = activeView()) return active;
		auto result = std::make_shared<QImage>();
		view = result;
		return result;
	}
	bool isCurrentView(const std::shared_ptr<QImage> &candidate) const {
		return candidate
			? !candidate.owner_before(view) && !view.owner_before(candidate)
			: empty();
	}
	template <typename Session> void load(Session*, int) { ++loads; }
	void complete(int pixels) {
		if (auto active = activeView()) active->pixels = pixels;
	}
	void replace(int value) { id = value; view.reset(); }
};

class PeerData;
class UserData;
enum class UpdateFlag { Photo };
enum class UserDataFlag { PersonalPhoto };
struct MockChanges {
	int photos = 0;
	void peerUpdated(PeerData*, UpdateFlag) { ++photos; }
};
struct MockSession {
	MockChanges updates;
	MockChanges &changes() { return updates; }
};

class PeerData {
public:
	bool user = false;
	bool self = false;
	bool bot = false;
	bool service = false;
	bool notifications = false;
	bool replies = false;
	bool verify = false;
	bool freeze = false;
	bool hiddenAuthor = false;
	PeerData *broadcast = nullptr;
	mutable MockCloud _userpic;
	mutable std::shared_ptr<EmptyUserpic> _userpicEmpty;
	mutable MockSession runtime;
	bool isUser() const { return user; }
	bool isSelf() const { return self; }
	bool isBot() const { return bot; }
	bool isServiceUser() const { return service; }
	bool isNotificationsUser() const { return notifications; }
	bool isRepliesChat() const { return replies; }
	bool isVerifyCodes() const { return verify; }
	bool isFreezeAppealChat() const { return freeze; }
	bool isSavedHiddenAuthor() const { return hiddenAuthor; }
	const UserData *asUser() const;
	MockSession &session() const { return runtime; }
	int userpicOrigin() const { return 1; }
	int userpicPhotoOrigin() const { return 2; }
	const PeerData *monoforumBroadcast() const { return broadcast; }
	std::shared_ptr<EmptyUserpic> ensureEmptyUserpic() const {
		if (!_userpicEmpty) _userpicEmpty = std::make_shared<EmptyUserpic>();
		return _userpicEmpty;
	}
	QImage *userpicCloudImage(Ui::PeerUserpicView&) const;
	void loadUserpic();
	Ui::PeerUserpicView activeUserpicView();
	Ui::PeerUserpicView createUserpicView();
	bool useEmptyUserpic(Ui::PeerUserpicView&) const;
	InMemoryKey userpicUniqueKey(Ui::PeerUserpicView&) const;

};
InMemoryKey inMemoryKey(int location) { return location; }

struct MTPDuserProfilePhoto {
	int id = 0;
	bool personal = false;
	bool video = false;
	struct Number { int v; };
	bool is_personal() const { return personal; }
	bool is_has_video() const { return video; }
	Number vphoto_id() const { return { id }; }
	Number vdc_id() const { return { 1 }; }
};
struct MTPDuserProfilePhotoEmpty {};
struct MTPUserProfilePhoto {
	std::variant<MTPDuserProfilePhoto, MTPDuserProfilePhotoEmpty> data;
	template <typename Full, typename Empty> void match(Full full, Empty empty) const {
		if (const auto photo = std::get_if<MTPDuserProfilePhoto>(&data)) full(*photo);
		else empty(std::get<MTPDuserProfilePhotoEmpty>(data));
	}
};

class UserData : public PeerData {
public:
	UserData() { user = true; }
	bool personal = false;
	bool video = false;
	bool hasPersonalPhoto() const { return personal; }
	void addFlags(UserDataFlag) { personal = true; }
	void removeFlags(UserDataFlag) { personal = false; }
	void updateUserpic(int id, int, bool hasVideo) {
		if (_userpic.id == id && video == hasVideo) return;
		_userpic.replace(id);
		video = hasVideo;
		runtime.updates.peerUpdated(this, UpdateFlag::Photo);
	}
	void clearUserpic() { updateUserpic(0, 0, false); }
	void setPhoto(const MTPUserProfilePhoto&);

};
const UserData *PeerData::asUser() const {
	return user ? static_cast<const UserData*>(this) : nullptr;
}

// PRODUCTION_FUNCTIONS

int checks = 0;
void Require(bool condition, const std::string &message) {
	++checks;
	if (!condition) throw std::runtime_error(message);
}
void SetPhoto(UserData &user, int id, bool personal) {
	user.setPhoto({ MTPDuserProfilePhoto{ id, personal, false } });
}

void TestExemptions() {
	const auto exemptions = {
		&PeerData::self, &PeerData::bot, &PeerData::service,
		&PeerData::notifications, &PeerData::replies, &PeerData::verify,
		&PeerData::freeze, &PeerData::hiddenAuthor,
	};
	for (const auto field : exemptions) {
		auto peer = UserData();
		peer.*field = true;
		SetPhoto(peer, 17, false);
		Require(!Ui::PersonalUserpicOnly(&peer), "exempt peer classified as human");
		Require(Ui::PeerUserpicPhotoAllowed(&peer), "exempt peer photo blocked");
		auto view = peer.createUserpicView();
		peer._userpic.complete(17);
		Require(peer.userpicCloudImage(view)->pixels == 17, "exempt photo lost");
	}
	auto group = PeerData();
	group._userpic.replace(21);
	auto view = group.createUserpicView();
	group._userpic.complete(21);
	Require(!Ui::PersonalUserpicOnly(&group), "group classified as human");
	Require(group.userpicUniqueKey(view) == 21, "group photo key changed");
	auto mono = PeerData();
	mono.broadcast = &group;
	Require(mono.userpicUniqueKey(view) == 21, "broadcast key not delegated");
}

void TestColdAndSameIdTransitions() {
	auto user = UserData();
	SetPhoto(user, 31, false);
	Require(Ui::PersonalUserpicOnly(&user), "human not covered");
	Require(!Ui::PeerUserpicPhotoAllowed(&user), "remote photo allowed");
	auto view = user.createUserpicView();
	Require(!view.cloud && view.cached.isNull(), "cold hidden view exposed image");
	Require(!user.activeUserpicView().cloud, "cold hidden active view exposed image");
	auto cached = user._userpic.createView();
	user._userpic.complete(31);
	view = { QImage{ 31 }, cached };
	Require(!user.activeUserpicView().cloud, "warm hidden active view exposed image");
	Require(user.useEmptyUserpic(view), "warm hidden photo exposed image");
	Require(!view.cloud && view.cached.isNull(), "hidden cached pixels not cleared");
	const auto initials = user.userpicUniqueKey(view);
	user.loadUserpic();
	Require(user._userpic.loads == 0, "hidden photo triggered loading");
	user.runtime.updates.photos = 0;
	SetPhoto(user, 31, true);
	Require(user.runtime.updates.photos == 1, "same-id personal addition missed event");
	Require(user.userpicCloudImage(view)->pixels == 31, "same-id personal addition hidden");
	Require(user.userpicUniqueKey(view) == 31, "personal key not photo key");
	view.cached = QImage{ 31 };
	user.runtime.updates.photos = 0;
	SetPhoto(user, 31, false);
	Require(user.runtime.updates.photos == 1, "same-id personal removal missed event");
	Require(user.userpicUniqueKey(view) == initials, "removed personal key not initials");
	Require(!view.cloud && view.cached.isNull(), "removed personal pixels remain");
	user.runtime.updates.photos = 0;
	SetPhoto(user, 31, false);
	Require(user.runtime.updates.photos == 0, "unchanged photo emitted extra event");
	const auto loads = user._userpic.loads;
	SetPhoto(user, 32, false);
	Require(user.userpicUniqueKey(view) == initials, "remote change changed initials key");
	user.loadUserpic();
	Require(user._userpic.loads == loads, "remote change loaded hidden image");
}

void TestPendingAndRemoval() {
	auto user = UserData();
	SetPhoto(user, 41, true);
	auto view = user.createUserpicView();
	Require(view.cloud && view.cloud->isNull(), "personal async view not created");
	Require(user._userpic.loads == 1, "personal download not requested");
	Require(user.useEmptyUserpic(view), "unloaded personal photo should use initials");
	const auto initials = user.userpicUniqueKey(view);
	user._userpic.complete(41);
	Require(!user.useEmptyUserpic(view), "completed personal photo remains hidden");
	Require(user.userpicCloudImage(view)->pixels == 41, "completed personal pixels wrong");
	Require(user.userpicUniqueKey(view) != initials, "completion did not change key");
	view.cached = QImage{ 41 };
	SetPhoto(user, 42, true);
	Require(user.useEmptyUserpic(view), "replacement retained old personal photo");
	Require(view.cached.isNull(), "replacement retained old cached pixels");
	auto pending = view.cloud;
	SetPhoto(user, 42, false);
	Require(user.useEmptyUserpic(view), "removed pending personal photo not hidden");
	pending->pixels = 42;
	Require(user.useEmptyUserpic(view), "late download resurrected removed photo");
	Require(!view.cloud, "late download retained hidden cloud view");
	SetPhoto(user, 43, true);
	user.runtime.updates.photos = 0;
	user.setPhoto({ MTPDuserProfilePhotoEmpty{} });
	Require(!user.hasPersonalPhoto(), "empty photo retained personal flag");
	Require(user.runtime.updates.photos > 0, "empty photo missed change event");
	Require(user.userpicUniqueKey(view) == initials, "empty photo not initials");
}

int main() {
	try {
		TestExemptions();
		TestColdAndSameIdTransitions();
		TestPendingAndRemoval();
		std::cout << "PASS: " << checks << " avatar model checks; no Qt/GUI coverage.\n";
		return 0;
	} catch (const std::exception &error) {
		std::cerr << "FAIL: " << error.what() << '\n';
		return 1;
	}
}
