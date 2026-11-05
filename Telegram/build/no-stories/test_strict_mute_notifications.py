#!/usr/bin/env python3
"""Run the actual strict-mute notification watcher against synthetic queues.

Exercises migrated-group cancellation and deferred alert revisions. This does
not compile Telegram or exercise Qt, native toasts, sound, or Windows.
"""

import argparse
from pathlib import Path
import subprocess
import tempfile

from test_personal_userpics import extract


FIXTURE = r"""
#include <algorithm>
#include <optional>
#include <functional>
#include <iostream>
#include <map>
#include <memory>
#include <set>
#include <stdexcept>
#include <utility>
#include <vector>

using PeerId = unsigned long long;
using uint64 = unsigned long long;
template <typename T> using not_null = T;
template <typename T> using Fn = std::function<T>;
using FullMsgId = uint64;
namespace ranges = std::ranges;

namespace rpl {
struct lifetime {
    std::shared_ptr<bool> alive = std::make_shared<bool>(true);
    std::vector<std::function<void()>> cleanup;
    void add(std::function<void()> callback) {
        cleanup.push_back(std::move(callback));
    }
    ~lifetime() {
        *alive = false;
        for (auto &callback : cleanup) callback();
    }
};
struct Handler {
    std::function<void(PeerId)> callback;
    std::weak_ptr<bool> alive;
};
struct Events {
    std::vector<Handler> handlers;
    void fire(PeerId id) {
        for (auto &handler : handlers) {
            const auto alive = handler.alive.lock();
            if (alive && *alive) handler.callback(id);
        }
    }
};
template <typename F>
Handler on_next(F callback, lifetime &owner) {
    return { callback, owner.alive };
}
void operator|(Events &events, Handler handler) {
    events.handlers.push_back(std::move(handler));
}
} // namespace rpl

namespace Main { struct Session; }
struct PeerData {
    PeerId id;
    Main::Session *owner;
    PeerData *migration = nullptr;
    Main::Session &session() const { return *owner; }
};
struct History {
    PeerData *peer;
    int queued = 1;
    int cleared = 0;
    void clearNotifications() { queued = 0; ++cleared; }
    Main::Session &session() const { return peer->session(); }
};
struct HistoryItem {
    History *owner;
    uint64 id;
    int author;
    History *history() const { return owner; }
    uint64 fullId() const { return id; }
};
struct Timer {
    bool active = false;
    void cancel() { active = false; }
};
struct Policy {
    std::set<PeerId> entries;
    rpl::Events events;
    bool contains(PeerId id) const { return entries.contains(id); }
    rpl::Events &changes() { return events; }
};
struct DataSession {
    std::map<PeerId, History*> histories;
    History *historyLoaded(PeerId id) {
        const auto i = histories.find(id);
        return i == histories.end() ? nullptr : i->second;
    }
};
namespace Main {
struct Session {
    uint64 id;
    Policy policy;
    DataSession storage;
    rpl::lifetime life;
    uint64 uniqueId() const { return id; }
    Policy &strictMute() { return policy; }
    DataSession &data() { return storage; }
    rpl::lifetime &lifetime() { return life; }
};
bool IsStrictMuted(const PeerData *peer) {
    const auto target = peer->migration ? peer->migration : peer;
    return target->session().policy.contains(target->id);
}
} // namespace Main

template <typename T>
struct WatchSet : std::set<T> {
    void remove(T value) { this->erase(value); }
};
struct System {
    WatchSet<Main::Session*> _watchedSessions;
    std::map<std::pair<uint64, PeerId>, uint64> _strictMuteRevisions;
    std::vector<History*> cleared;
    std::map<uint64, Main::Session*> sessions;
    std::set<std::pair<uint64, PeerId>> _groupedHistories;
    int _lastForwardedCount = 0;
    uint64 _lastHistorySessionId = 0;
    FullMsgId _lastHistoryItemId = 0;
    std::optional<uint64> _lastSoundId;
    Timer _waitForAllGroupedTimer;
    Main::Session *findSession(uint64 id) const {
        const auto i = sessions.find(id);
        return i == sessions.end() ? nullptr : i->second;
    }
    void clearFromHistory(History *history) {
        cleared.push_back(history);
        // Model the caller; the matching/bookkeeping/reset methods below
        // are extracted from production rather than reimplemented here.
        if (groupedMatches([&](History *participant) { return participant == history; })) {
            clearGrouped();
        }
    }
    void trackGroupedItem(HistoryItem *item);
    bool groupedMatches(Fn<bool(History*)> predicate) const;
    void clearGrouped();
    void registerSession(Main::Session *session);
    uint64 strictMuteRevision(const PeerData *peer) const;
};

// PRODUCTION_FUNCTIONS

int main() {
    int checks = 0;
    const auto check = [&](bool ok, const char *label) {
        if (!ok) throw std::runtime_error(label);
        ++checks;
    };
    System system;
    {
        Main::Session session{ .id = 1 };
        system.sessions.emplace(session.id, &session);
        PeerData oldPeer{ .id = 10, .owner = &session };
        PeerData newPeer{ .id = 11, .owner = &session };
        PeerData otherPeer{ .id = 12, .owner = &session };
        History oldHistory{ .peer = &oldPeer };
        History newHistory{ .peer = &newPeer };
        History otherHistory{ .peer = &otherPeer };
        session.storage.histories = {
            {10, &oldHistory}, {11, &newHistory}, {12, &otherHistory},
        };
        system.registerSession(&session);
        system.registerSession(&session);
        check(session.policy.events.handlers.size() == 1, "one watcher per session");
        const auto deferredRevision = system.strictMuteRevision(&oldPeer);

        // Policy migration removes the old key, then emits old and new IDs.
        oldPeer.migration = &newPeer;
        session.policy.entries.insert(newPeer.id);
        session.policy.events.fire(oldPeer.id);
        session.policy.events.fire(newPeer.id);
        check(oldHistory.queued == 0, "migrated old history queue cleared");
        check(newHistory.queued == 0, "target history queue cleared");
        check(otherHistory.queued == 1, "unrelated history queue preserved");
        check(system.cleared.size() == 2, "both already-shown histories cleared");
        check(system.strictMuteRevision(&oldPeer) != deferredRevision,
              "old deferred alert invalidated by migration");

        session.policy.entries.clear();
        session.policy.events.fire(newPeer.id);
        check(oldHistory.queued == 0, "rapid unmute does not restore queue");
        check(system.strictMuteRevision(&oldPeer) != deferredRevision,
              "rapid unmute cannot restore deferred alert validity");
        check(system.cleared.size() == 2, "unmute alone does not clear other alerts");

        const auto known = session.storage.histories.size();
        session.policy.entries.insert(99);
        session.policy.events.fire(99);
        check(session.storage.histories.size() == known, "no history fabrication");
        check(system.strictMuteRevision(&otherPeer) == 0, "other peer revision preserved");

        oldPeer.migration = nullptr;
        HistoryItem earlier{ &oldHistory, 101, 5 };
        HistoryItem last{ &newHistory, 102, 5 };
        for (const auto strictPeer : {oldPeer.id, newPeer.id}) {
            session.policy.entries.clear();
            check(earlier.author == last.author, "scenario groups forwards from same author");
            system.trackGroupedItem(&earlier);
            system.trackGroupedItem(&last);
            system._lastForwardedCount = 2;
            system._lastSoundId = 1;
            system._waitForAllGroupedTimer.active = true;
            check(system._lastHistoryItemId == last.id, "last summary item remains final forward");
            check(system._groupedHistories.size() == 2, "summary tracks both contributing histories");
            session.policy.entries.insert(otherPeer.id);
            session.policy.events.fire(otherPeer.id);
            check(system._groupedHistories.size() == 2 && system._waitForAllGroupedTimer.active,
                  "unrelated independent history does not cancel summary");
            session.policy.entries.insert(strictPeer);
            check(system.groupedMatches([](History *history) {
                return Main::IsStrictMuted(history->peer);
            }), "display guard detects strict earlier or last participant");
            session.policy.events.fire(strictPeer);
            check(system._groupedHistories.empty() && !system._waitForAllGroupedTimer.active,
                  "enabling strict on earlier or last participant cancels complete summary");
            check(!system._lastHistoryItemId && !system._lastHistorySessionId
                  && !system._lastForwardedCount && !system._lastSoundId,
                  "summary clear resets all associated state");
            session.policy.entries.clear();
            session.policy.events.fire(strictPeer);
            check(system._groupedHistories.empty(), "unmute never restores grouped summary");
        }
        system.trackGroupedItem(&last);
        system.clearGrouped();
        check(system._groupedHistories.empty(), "normal summary clear removes participants");
        system.sessions.erase(session.id);
    }
    check(system._watchedSessions.empty(), "session cleanup removes watcher");

    {
        Main::Session session{ .id = 2 };
        PeerData peer{ .id = 10, .owner = &session };
        History history{ .peer = &peer };
        session.storage.histories.emplace(peer.id, &history);
        system.registerSession(&session);
        check(system.strictMuteRevision(&peer) == 0, "same peer isolated by account");
        session.policy.entries.insert(peer.id);
        session.policy.events.fire(peer.id);
        check(history.queued == 0, "ordinary enable clears queue");
        check(system.strictMuteRevision(&peer) == 1, "ordinary enable invalidates alert");
    }
    std::cout << "Actual notification watcher: " << checks
              << " behavior checks passed; dependencies mocked.\n";
}
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cxx", default="g++")
    args = parser.parse_args()
    source_root = Path(__file__).resolve().parents[2] / "SourceFiles"
    production = (source_root / "window/notifications_manager.cpp").read_text(encoding="utf-8")
    functions = "\n\n".join(extract(production, signature) for signature in (
        "void System::registerSession(",
        "uint64 System::strictMuteRevision(",
        "void System::trackGroupedItem(",
        "bool System::groupedMatches(",
        "void System::clearGrouped(",
    ))
    combined = FIXTURE.replace("// PRODUCTION_FUNCTIONS", functions)
    with tempfile.TemporaryDirectory(prefix="telegram-strict-notifications-") as directory:
        source = Path(directory) / "watcher.cpp"
        binary = Path(directory) / "watcher"
        source.write_text(combined, encoding="utf-8")
        subprocess.run([
            args.cxx, "-std=c++20", "-Wall", "-Wextra", "-Werror",
            "-Wno-deprecated", "-Wno-missing-field-initializers",
            str(source), "-o", str(binary),
        ], check=True, timeout=45)
        subprocess.run([str(binary)], check=True, timeout=10)


if __name__ == "__main__":
    main()
