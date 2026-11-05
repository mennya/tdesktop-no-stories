// Synthetic dependencies only. Production functions are injected verbatim.
#include <cstdlib>
#include <iostream>
#include <map>
#include <vector>
#include <algorithm>
#include <set>
#include <stdexcept>
[[noreturn]] void Unexpected(const char *text) { throw std::runtime_error(text); }
template <typename T> using not_null = T;
namespace Core {
struct Settings {
    bool includeMuted = true, countMessages = true;
    bool includeMutedCounter() const { return includeMuted; }
    bool countUnreadMessages() const { return countMessages; }
};
struct Application { Settings value; Settings &settings() { return value; } };
Application &App() { static Application app; return app; }
}
namespace Main { class Session; }
namespace Data { class Session; class Folder; class Forum; }
struct UserData {
    bool bot = false, contact = true;
    bool isBot() const { return bot; }
    bool isContact() const { return contact; }
};
struct ChannelData {
    bool community = false, broadcast = false;
    bool isCommunity() const { return community; }
    bool isBroadcast() const { return broadcast; }
};
class History;
struct PeerData {
    int id; Main::Session *session;
    UserData *user = nullptr;
    ChannelData *channel = nullptr;
    Data::Forum *forumValue = nullptr;
    UserData *asUser() const { return user; }
    ChannelData *asChannel() const { return channel; }
    bool isChat() const { return !user && !channel; }
    Data::Forum *forum() const { return forumValue; }
};
namespace Dialogs {
// PRODUCTION_STATE
struct BadgesState { bool unread = false, mention = false; };
class Entry {
public:
    virtual ~Entry() = default;
    UnreadState state;
    bool inList = true;
    virtual UnreadState chatListUnreadState() const { return state; }
    bool inChatList() const { return inList; }
};
class Key {
public:
    Key(Entry *value = nullptr) : value(value) {}
    explicit operator bool() const { return value != nullptr; }
    Entry *entry() const { return value; }
    PeerData *peer() const;
    History *owningHistory() const;
    Data::Folder *folder() const;
    Entry *value;
};
struct Row { Key value; Key key() const { return value; } };
struct Rows : std::vector<Row*> {
    using std::vector<Row*>::vector;
    bool contains(Entry *entry) const {
        return std::any_of(begin(), end(), [=](Row *row) { return row->key().entry() == entry; });
    }
};
class MainList {
public:
    Main::Session *_session = nullptr;
    Rows _all;
    UnreadState _unreadState, _cloudUnreadState;
    bool _allAreMuted = false, _loaded = true;
    bool loaded() const { return _loaded; }
    UnreadState unreadState() const;
    UnreadState attentionUnreadState() const;
};
}
class History : public Dialogs::Entry {
public:
    PeerData *peer;
    Data::Folder *folderValue = nullptr;
    bool folderIsKnown = true;
    bool nativeMuted = false, fakeUnread = false;
    bool muted() const { return nativeMuted; }
    bool fakeUnreadWhileOpened() const { return fakeUnread; }
    Dialogs::BadgesState chatListBadgesState() const { return {state.messages > 0 || state.marks > 0, state.mentions > 0}; }
    History(PeerData *peer) : peer(peer) {}
    bool folderKnown() const { return folderIsKnown; }
    Data::Folder *folder() const { return folderValue; }
};
namespace Data {
class Forum {
public:
    Dialogs::MainList list;
    Dialogs::MainList *topicsList() { return &list; }
};
class ChatFilter {
public:
    struct Flag { enum { Bots=1, Contacts=2, NonContacts=4, Groups=8, Channels=16, NoRead=32, NoMuted=64, NoArchived=128 }; };
    int _flags = Flag::Groups;
    std::set<History*> _always, _never;
    bool contains(not_null<History*> history, bool ignoreFakeUnread) const;
};
class Folder : public Dialogs::Entry {
public:
    static constexpr int kId = 1;
    Dialogs::MainList list;
    Dialogs::MainList *chatsList() { return &list; }
    Dialogs::UnreadState chatListUnreadState() const override { return list.unreadState(); }
};
class Session {
public:
    Dialogs::MainList &_chatsList;
    std::map<int, History*> histories;
    Folder *archive = nullptr;
    explicit Session(Dialogs::MainList &list) : _chatsList(list) {}
    History *historyLoaded(int id) const {
        auto i = histories.find(id);
        return (i == histories.end()) ? nullptr : i->second;
    }
    Folder *folderLoaded(int) const { return archive; }
    int computeUnreadBadge(const Dialogs::UnreadState &state) const;
    bool computeUnreadBadgeMuted(const Dialogs::UnreadState &state) const;
    int unreadBadge() const;
    int unreadBadgeIgnoreOne(Dialogs::Key key) const;
    bool unreadBadgeMutedIgnoreOne(Dialogs::Key key) const;
};
Dialogs::UnreadState AttentionUnreadState(Dialogs::Key key);
}
namespace Main {
class StrictMute {
public:
    std::map<int, unsigned long long> values;
    const auto &entries() const { return values; }
};
class Session {
public:
    StrictMute strict;
    Data::Session *store = nullptr;
    StrictMute &strictMute() { return strict; }
    Data::Session &data() { return *store; }
};
bool IsStrictMuted(PeerData *peer) { return peer->session->strict.values.contains(peer->id); }
}
PeerData *Dialogs::Key::peer() const {
    const auto history = dynamic_cast<History*>(value);
    return history ? history->peer : nullptr;
}
History *Dialogs::Key::owningHistory() const { return dynamic_cast<History*>(value); }
Data::Folder *Dialogs::Key::folder() const { return dynamic_cast<Data::Folder*>(value); }
// PRODUCTION_FUNCTIONS
namespace {
int checks = 0;
void check(bool value, const char *label) {
    ++checks;
    if (!value) { std::cerr << "FAIL: " << label << '\n'; std::exit(1); }
}
bool equal(Dialogs::UnreadState a, Dialogs::UnreadState b) {
    return a.messages == b.messages && a.messagesMuted == b.messagesMuted
        && a.chats == b.chats && a.chatsMuted == b.chatsMuted
        && a.marks == b.marks && a.marksMuted == b.marksMuted
        && a.mentions == b.mentions && a.reactions == b.reactions
        && a.reactionsMuted == b.reactionsMuted && a.polls == b.polls
        && a.pollsMuted == b.pollsMuted && a.known == b.known;
}
Dialogs::UnreadState count(int messages, bool muted = false) {
    auto result = Dialogs::UnreadState();
    result.messages = messages;
    result.chats = (messages > 0);
    result.messagesMuted = muted ? messages : 0;
    result.chatsMuted = muted ? result.chats : 0;
    result.known = true;
    return result;
}
}
int main() {
    Main::Session session;
    Dialogs::MainList list;
    Data::Session data(list);
    session.store = &data;
    list._session = &session;
    PeerData p1{1, &session}, p2{2, &session}, p3{3, &session};
    History quiet(&p1), normal(&p2), outside(&p3);
    data.histories = {{1, &quiet}, {2, &normal}, {3, &outside}};
    quiet.state = count(7);
    quiet.state.mentions = quiet.state.reactions = quiet.state.polls = 1;
    normal.state = count(3, true);
    normal.state.marks = normal.state.marksMuted = 1;
    Dialogs::Row r1{&quiet}, r2{&normal};
    list._all = {&r1, &r2};
    list._unreadState = quiet.state + normal.state;
    const auto raw = list.unreadState();
    check(equal(list.attentionUnreadState(), raw), "no rule is identity");
    session.strict.values[1] = 42;
    auto shown = list.attentionUnreadState();
    check(equal(shown, normal.state), "strict peer removes all attention fields");
    check(equal(list.unreadState(), raw), "projection preserves raw aggregate");
    check(equal(quiet.state, count(7) + Dialogs::UnreadState{.reactions=1,.mentions=1,.polls=1}), "projection preserves raw peer unread");
    check(data.unreadBadge() == 4, "account badge uses projected count");
    check(data.unreadBadgeIgnoreOne(&quiet) == 4, "ignore strict current does not subtract twice");
    check(data.unreadBadgeIgnoreOne(&normal) == 0, "ignore normal current subtracts normal contribution");
    check(data.unreadBadgeIgnoreOne({}) == 4, "empty current leaves badge intact");
    normal.inList = false;
    check(data.unreadBadgeIgnoreOne(&normal) == 4, "out-of-list current does not subtract");
    normal.inList = true;
    for (int i = 0; i != 8; ++i) {
        session.strict.values.clear();
        check(equal(list.attentionUnreadState(), raw), "disable restores raw projection");
        session.strict.values[1] = 42;
        check(equal(list.attentionUnreadState(), normal.state), "repeated toggle does not accumulate subtraction");
    }
    quiet.state = count(0);
    quiet.state.marks = 1;
    list._unreadState = quiet.state + normal.state;
    check(equal(list.attentionUnreadState(), normal.state), "manual unread mark hidden only from display");
    check(quiet.state.marks == 1, "manual unread mark retained");

    Data::Folder archive;
    archive.list._session = &session;
    archive.list._allAreMuted = true;
    archive.list._loaded = false;
    archive.list._cloudUnreadState = count(10, true);
    archive.list._cloudUnreadState.chats = archive.list._cloudUnreadState.chatsMuted = 2;
    archive.list._unreadState.known = true;
    quiet.state = count(7);
    quiet.state.marks = quiet.state.mentions = quiet.state.reactions = quiet.state.polls = 1;
    quiet.folderValue = &archive;
    normal.folderValue = &archive;
    data.archive = &archive;
    const auto cloud = archive.list.unreadState();
    shown = archive.list.attentionUnreadState();
    check(shown.messages == 3 && shown.chats == 1, "cold archive subtracts hydrated non-row peer exactly once");
    check(shown.messagesMuted == 3 && shown.chatsMuted == 1, "archive retains muted presentation");
    check(shown.marks == 0 && shown.mentions == 0 && shown.reactions == 0 && shown.polls == 0, "non-row local-only fields not subtracted from cloud");
    check(equal(cloud, archive.list.unreadState()), "cold archive cloud counters untouched");
    archive.list._all = {&r1, &r2};
    archive.list._unreadState = quiet.state + normal.state;
    shown = archive.list.attentionUnreadState();
    check(shown.marks == normal.state.marks && shown.mentions == 0 && shown.reactions == 0 && shown.polls == 0,
        "cloud message totals combine with projected loaded local-only fields");
    archive.list._all.clear();
    archive.list._unreadState = Dialogs::UnreadState{.known=true};
    quiet.folderIsKnown = false;
    check(!archive.list.attentionUnreadState().known && archive.list.attentionUnreadState().messages == 0, "unknown membership hides archive only");
    quiet.folderIsKnown = true;
    quiet.state.known = false;
    check(!archive.list.attentionUnreadState().known, "unknown strict count hides cloud archive");
    quiet.state.known = true;
    data.histories.erase(1);
    check(!archive.list.attentionUnreadState().known, "missing cold strict history hides archive");
    data.histories[1] = &quiet;
    check(archive.list.attentionUnreadState().messages == 3, "hydration restores known archive projection");
    quiet.folderValue = nullptr;
    check(equal(archive.list.attentionUnreadState(), cloud), "known non-archive peer leaves archive intact");
    quiet.folderValue = &archive;
    Data::Forum forum;
    forum.list._loaded = false;
    quiet.peer->forumValue = &forum;
    check(!archive.list.attentionUnreadState().known, "incomplete strict forum topics are not a full server dialog count");
    forum.list._loaded = true;
    check(archive.list.attentionUnreadState().messages == 3, "complete forum topics permit cloud subtraction");
    quiet.peer->forumValue = nullptr;
    quiet.state.messages = 11;
    check(!archive.list.attentionUnreadState().known, "unreconciled server snapshots never show negative counts");
    quiet.state.messages = 7;
    Dialogs::Row folderRow{&archive};
    outside.state = count(2);
    Dialogs::Row r3{&outside};
    list._all = {&folderRow, &r3};
    list._unreadState = cloud + outside.state;
    quiet.folderIsKnown = false;
    check(list.attentionUnreadState().messages == 2, "unknown archive does not hide unrelated account count");
    check(data.unreadBadgeIgnoreOne(&normal) == 2, "open ordinary archived chat is not subtracted from already excluded archive");
    check(Data::MainListMapUnreadState(&session, list.attentionUnreadState()).messages == 2, "main tab excludes unknown archive consistently");
    quiet.folderIsKnown = true;
    check(list.attentionUnreadState().messages == 5, "account replaces archive raw with projection");
    check(Data::MainListMapUnreadState(&session, list.attentionUnreadState()).messages == 2, "main tab excludes known projected archive");
    check(data.unreadBadgeIgnoreOne(&archive) == 2, "ignore archive uses projected contribution");
    archive.list._loaded = true;
    archive.list._all = {&r1, &r2};
    archive.list._unreadState = quiet.state + normal.state;
    shown = archive.list.attentionUnreadState();
    check(shown.messages == 3 && shown.marks == 1, "fully loaded archive removes strict and retains normal marks");
    check(shown.mentions == 0 && shown.reactions == 0 && shown.polls == 0, "fully loaded archive hides mention/reaction/poll attention");
    check(quiet.state.marks == 1 && quiet.state.mentions == 1, "archive projection does not read or clear strict state");
    session.strict.values.clear();
    check(equal(archive.list.attentionUnreadState(), archive.list.unreadState()), "disable restores loaded archive raw state");
    Data::ChatFilter filter;
    quiet.folderValue = nullptr;
    quiet.fakeUnread = true;
    quiet.nativeMuted = false;
    quiet.state = count(7);
    session.strict.values[1] = 42;
    for (const auto flag : {int(Data::ChatFilter::Flag::NoRead), int(Data::ChatFilter::Flag::NoMuted),
            Data::ChatFilter::Flag::NoRead | Data::ChatFilter::Flag::NoMuted}) {
        filter._flags = Data::ChatFilter::Flag::Groups | flag;
        check(!filter.contains(&quiet, false), "strict automatic folder match excluded, including fake unread");
        check(!filter.contains(&quiet, true), "strict automatic exclusion independent of fake unread option");
        filter._always.insert(&quiet);
        check(filter.contains(&quiet, false), "explicit folder inclusion preserved");
        filter._never.insert(&quiet);
        check(!filter.contains(&quiet, false), "explicit exclusion retains precedence");
        filter._always.clear(); filter._never.clear();
        session.strict.values.clear();
        check(filter.contains(&quiet, false), "disabling strict mute restores native folder matching");
        session.strict.values[1] = 42;
    }
    filter._flags = Data::ChatFilter::Flag::Groups;
    check(filter.contains(&quiet, false), "ordinary group folder matching unchanged");
    normal.state = count(10); // Native unmuted chat in archive.
    normal.state.marks = 1;
    outside.state = count(3);
    outside.state.marks = 1;
    archive.list._unreadState = quiet.state + normal.state;
    list._unreadState = archive.list.unreadState() + outside.state;
    const auto aggregateBefore = list.unreadState();
    const auto archivedBefore = normal.state;
    for (const auto includeMuted : {false, true}) {
        for (const auto countMessages : {false, true}) {
            Core::App().settings().includeMuted = includeMuted;
            Core::App().settings().countMessages = countMessages;
            const auto outsideBadge = countMessages ? 4 : 2;
            const auto archivedBadge = countMessages ? 11 : 2;
            check(data.unreadBadge() == outsideBadge + (includeMuted ? archivedBadge : 0),
                "production account badge respects muted and message/chat settings");
            check(data.unreadBadgeIgnoreOne(&normal) == outsideBadge,
                "ignoring archived native-unmuted chat preserves unrelated unmuted messages/chats/marks");
            check(!data.unreadBadgeMutedIgnoreOne(&normal),
                "ignoring archived chat retains unmuted badge classification");
            check(data.unreadBadgeIgnoreOne(&quiet) == data.unreadBadge(),
                "ignoring strict archived chat does not subtract twice in either count mode");
            check(equal(list.unreadState(), aggregateBefore) && equal(normal.state, archivedBefore),
                "archive removal normalization leaves raw aggregate and native mute state untouched");
        }
    }
    std::cout << checks << " strict-mute unread model checks passed (no Qt GUI/RPC coverage).\n";
}
