#!/usr/bin/env python3
"""Execute actual strict-mute call methods with synthetic dependencies.

Covers ringing suppression, per-attempt latching, account/peer isolation,
outgoing/established calls, and subscription teardown. This is not a Qt build
or a GUI, network-signaling, audio-device, or Windows integration test.
"""

import argparse
from pathlib import Path
import subprocess
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cxx", default="g++")
    args = parser.parse_args()
    r = Path(__file__).resolve().parents[2] / "SourceFiles"
    s=(r/'calls/calls_call.cpp').read_text()
    def function(signature):
        start=s.index(signature); begin=s.index('{',start); depth=1; end=begin+1
        while depth:
            depth += (s[end]=='{')-(s[end]=='}'); end+=1
        return s[start:end]
    code=r'''
    #include <functional>
    #include <memory>
    #include <string>
    #include <vector>
    #include <iostream>
    #include <stdexcept>
    using PeerId = long long;
    using QString = std::u16string;
    QString operator""_q(const char16_t *p, std::size_t n) { return QString(p,n); }
    namespace rpl {
    struct lifetime { std::shared_ptr<bool> live=std::make_shared<bool>(true); ~lifetime(){*live=false;} };
    struct Next { std::function<void(PeerId)> fn; std::weak_ptr<bool> live; };
    template<class F> Next on_next(F f, lifetime &l) { return {f,l.live}; }
    struct Events { std::vector<Next> handlers; void fire(PeerId id){ for(auto &h:handlers) if(auto l=h.live.lock(); l&&*l) h.fn(id); } };
    void operator|(Events &e, Next n) { e.handlers.push_back(std::move(n)); }
    template<class T> struct variable { T value{}; T current() const { return value; } variable&operator=(T v){value=v;return *this;} };
    }
    struct StrictMute { bool enabled=false; rpl::Events changed; rpl::Events &changes(){return changed;} };
    struct Session { StrictMute strict; StrictMute &strictMute(){return strict;} };
    struct User { PeerId id=1; Session *s; Session &session() const {return *s;} };
    namespace Main { bool IsStrictMuted(User *u){return u->session().strict.enabled;} }
    namespace Media::Audio {
    struct Track { void samplePeakEach(int){} void fillFromFile(const QString&){} void playInLoop(){++played;} static inline int played=0; };
    struct Audio { std::unique_ptr<Track> createTrack(){return std::make_unique<Track>();} };
    Audio &Current(){static Audio a;return a;}
    }
    namespace Core { struct Settings {QString getSoundPath(QString p){return p;}}; struct AppType {Settings &settings(){static Settings s;return s;}}; AppType &App(){static AppType a;return a;} }
    struct Call {
     enum class Type { Incoming,Outgoing };
     enum State { Starting,WaitingIncoming,Established,ExchangingKeys,Ended };
     Type _type=Type::Incoming; State _state=Starting; User *_user=nullptr;
     rpl::variable<bool> _incomingNotificationsSuppressed;
     std::unique_ptr<Media::Audio::Track> _waitingTrack;
     rpl::lifetime _lifetime;
     static constexpr int kSoundSampleMs=100;
     Type type() const{return _type;} State state()const{return _state;}
     rpl::lifetime &lifetime(){return _lifetime;}
     bool isIncomingWaiting()const;
     void setupIncomingNotifications(); void startWaitingTrack();
    };
    '''
    code += '\n'.join(function(x) for x in ['bool Call::isIncomingWaiting() const', 'void Call::setupIncomingNotifications()', 'void Call::startWaitingTrack()'])
    code += r'''
    int main(){
     int checks=0;
     auto check=[&](bool b,const char*n){if(!b)throw std::runtime_error(n);++checks;};
     {
     Session s; User u{1,&s}; s.strict.enabled=true;
     Call c; c._user=&u; c.setupIncomingNotifications(); c.startWaitingTrack();
     check(c._incomingNotificationsSuppressed.current(),"incoming muted initially latched");
     check(!c._waitingTrack,"initial ringtone omitted");
     s.strict.enabled=false;s.strict.changed.fire(1);
     check(c._incomingNotificationsSuppressed.current(),"unmute does not unlatch");
     c.startWaitingTrack();check(!c._waitingTrack,"late start cannot replay muted attempt");
     Call next; next._user=&u; next.setupIncomingNotifications();next.startWaitingTrack();
     check(!next._incomingNotificationsSuppressed.current()&&bool(next._waitingTrack),"new unmuted attempt rings");
     }
     for(auto state:{Call::Starting,Call::WaitingIncoming}) {
     Session s; User u{1,&s}; Call c;c._user=&u;c._state=state;c.setupIncomingNotifications();c.startWaitingTrack();
     check(bool(c._waitingTrack),"normal incoming rings");
     s.strict.enabled=true;s.strict.changed.fire(2);
     check(bool(c._waitingTrack)&&!c._incomingNotificationsSuppressed.current(),"unrelated peer unaffected");
     s.strict.changed.fire(1);
     check(!c._waitingTrack&&c._incomingNotificationsSuppressed.current(),"enable stops waiting ring");
     s.strict.enabled=false;s.strict.changed.fire(1);c.startWaitingTrack();
     check(!c._waitingTrack,"disable cannot replay current attempt");
     }
     {
     Session s;User u{1,&s};Call c;c._type=Call::Type::Outgoing;c._user=&u;s.strict.enabled=true;c.setupIncomingNotifications();c.startWaitingTrack();
     check(!c._incomingNotificationsSuppressed.current()&&bool(c._waitingTrack),"outgoing unaffected by strict");
     s.strict.changed.fire(1);check(bool(c._waitingTrack),"outgoing not stopped on change");
     }
     {
     Session s;User u{1,&s};Call c;c._user=&u;c.setupIncomingNotifications();c._state=Call::Established;
     s.strict.enabled=true;s.strict.changed.fire(1);
     check(!c._incomingNotificationsSuppressed.current()&&c._state==Call::Established,"established not suppressed or ended");
     }
     {
     Session s;Session other;User u{1,&s};Call c;c._user=&u;c.setupIncomingNotifications();c.startWaitingTrack();other.strict.enabled=true;other.strict.changed.fire(1);
     check(bool(c._waitingTrack)&&!c._incomingNotificationsSuppressed.current(),"other account same peer unaffected");
     }
     {
     Session s;User u{1,&s}; {Call c;c._user=&u;c.setupIncomingNotifications();} s.strict.enabled=true;s.strict.changed.fire(1);
     check(true,"subscription lifetime safely released");
     }
     std::cout<<"Actual Call methods: "<<checks<<" behavior checks passed; dependencies mocked, not a Qt/Windows runtime test.\n";
    }
    '''
    with tempfile.TemporaryDirectory(prefix='strict-call-check-') as td:
        source=Path(td)/'check.cpp'; exe=Path(td)/'check'; source.write_text(code)
        subprocess.run([args.cxx,'-std=c++20','-Wall','-Wextra','-Werror','-Wno-deprecated',str(source),'-o',str(exe)],check=True,timeout=45)
        subprocess.run([str(exe)],check=True,timeout=10)


if __name__ == "__main__":
    main()
