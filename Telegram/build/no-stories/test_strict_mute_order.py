#!/usr/bin/env python3
"""Exercise production sorting methods with synthetic dialogs.

Checks exact tie stability, unread priority, pin precedence and restoration.
Does not simulate Qt, encrypted storage, server updates or the application UI.
"""
import argparse
from pathlib import Path
import subprocess
import tempfile
from test_personal_userpics import extract


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cxx', default='g++')
    args = parser.parse_args()
    sources = Path(__file__).resolve().parents[2] / 'SourceFiles'
    source = (sources / 'dialogs/dialogs_entry.cpp').read_text()
    helpers = '\n'.join(extract(source, sig) for sig in (
        'uint64 DialogPosFromDate(', 'uint64 FixedOnTopDialogPos(',
        'uint64 PinnedDialogPos(', 'uint64 UnreadOnTopDialogPos(',
    ))
    methods = '\n'.join(extract(source, sig) for sig in (
        'uint64 Entry::chronologicalSortKey() const',
        'void Entry::updateChatListSortPosition()',
        'uint64 Entry::computeSortPosition(',
        'bool Entry::hasUnreadUnmutedForSort() const',
    ))
    fixture = r'''
#include <algorithm>
#include <cstdint>
#include <iostream>
#include <stdexcept>
using uint64=std::uint64_t; using TimeId=std::int64_t; using FilterId=int;
int DialogsPosToTopShift=0;
// HELPERS
struct Peer { uint64 anchor=0; };
namespace Main {
uint64 StrictMuteAnchor(Peer *p){return p->anchor;}
bool IsStrictMuted(Peer *p){return p->anchor!=0;}
}
struct Thread { Peer *p; Peer *peer()const{return p;} };
struct History { Peer *peer; };
struct Settings { bool supportFixChatsOrder()const{return false;} };
struct Session { bool supportMode()const{return false;} Settings settings()const{return {};} };
struct Owner { bool unreadOnTop=false; bool dialogsUnreadOnTop()const{return unreadOnTop;} };
struct State { int messages=0,messagesMuted=0,marks=0,marksMuted=0,reactions=0,reactionsMuted=0,mentions=0; };
struct Entry {
    Peer peer; History history{&peer}; Thread thread{&peer}; Owner ownerValue;
    State raw; uint64 _sortKeyInChatList=0,_sortKeyByDate=0;
    TimeId date=100; int pin=0,folderPin=0,fixed=0; bool exists=true;
    Session session()const{return {};}
    Owner &owner(){return ownerValue;}
    const Owner &owner()const{return ownerValue;}
    History *asHistory(){return &history;}
    const Thread *asThread()const{return &thread;}
    State chatListUnreadState()const{return raw;}
    int lookupPinnedIndex(FilterId f)const{return f?folderPin:pin;}
    virtual TimeId adjustedChatListTimeId()const{return date;}
    int fixedOnTopIndex()const{return fixed;}
    bool needUpdateInChatList()const{return exists;}
    void setChatListExistence(bool){} void updateChatListEntry(){}
    void updateChatListSortPosition(); uint64 computeSortPosition(FilterId)const;
    bool hasUnreadUnmutedForSort()const;
    uint64 chronologicalSortKey() const;
};
struct DraftDialog : Entry {
    TimeId draftDate = 110;
private:
    TimeId adjustedChatListTimeId() const override { return draftDate; }
};
// METHODS
int main(){
    int checks=0;
    auto check=[&](bool b,const char *name){if(!b)throw std::runtime_error(name);++checks;};
    DraftDialog pending;
    check(pending.chronologicalSortKey() == (uint64(110) << 32),
        "unpositioned dialog uses virtual adjusted date including drafts");
    pending.draftDate = 0;
    check(pending.chronologicalSortKey() == (uint64(1) << 32),
        "empty unpositioned dialog gets a nonzero anchor");
    Entry a,b; a.updateChatListSortPosition(); b.updateChatListSortPosition();
    check(b._sortKeyInChatList>a._sortKeyInChatList,"normal same-second bump retained");
    const auto original=a.chronologicalSortKey(); a.peer.anchor=original;
    for (int event=0;event<5;++event){
        // New message, own send, cloud draft, local draft and reaction all
        // eventually invoke the same production ordering path.
        a.date=200+event; a.raw.messages=event+1; a.raw.mentions=1;
        a.ownerValue.unreadOnTop=true; a.updateChatListSortPosition();
        check(a._sortKeyInChatList==original,"strict activity cannot bump row");
        check(a.chronologicalSortKey()==original,"full low-bit tie retained");
    }
    b.date=300;b.updateChatListSortPosition();
    check(b._sortKeyInChatList>a._sortKeyInChatList,"ordinary newer chat may pass strict chat");
    check(!a.hasUnreadUnmutedForSort(),"strict removes unread-sort priority");
    check(a.raw.messages==5&&a.raw.mentions==1,"sorting preserves actual unread data");
    a.pin=2;a.folderPin=3;a.updateChatListSortPosition();
    check(a._sortKeyInChatList==PinnedDialogPos(2),"explicit main pin retained");
    check(a.computeSortPosition(1)==PinnedDialogPos(3),"explicit folder pin retained");
    check(a.chronologicalSortKey()==original,"pin does not replace stored chronology");
    a.pin=0;a.folderPin=0;a.updateChatListSortPosition();
    check(a._sortKeyInChatList==original,"unpin returns to strict anchor");
    a.fixed=1;a.updateChatListSortPosition();
    check(a._sortKeyInChatList==FixedOnTopDialogPos(1),"fixed system priority retained");
    a.fixed=0;a.peer.anchor=0;a.updateChatListSortPosition();
    check(a._sortKeyInChatList&0x8000000000000000ULL,"disable restores unread priority");
    check((a.chronologicalSortKey()>>32)==204,"disable restores latest actual date");
    check(!(a.chronologicalSortKey()&0x8000000000000000ULL),"anchor excludes unread priority bit");
    a.ownerValue.unreadOnTop=false;a.updateChatListSortPosition();
    check(!(a._sortKeyInChatList&0x8000000000000000ULL),"normal option remains respected");
    Entry secondAccount;secondAccount.date=400;secondAccount.updateChatListSortPosition();
    check(secondAccount.peer.anchor==0,"separate account policy unaffected");
    // A restored anchor from persisted preferences is consumed identically.
    Entry restored;restored.peer.anchor=original;restored.date=500;
    restored.updateChatListSortPosition();
    check(restored._sortKeyInChatList==original,"restored exact key remains stable");
    restored.exists=false;restored.updateChatListSortPosition();
    check(restored._sortKeyInChatList==0,"policy does not resurrect removed dialog");
    std::cout<<"PASS: "<<checks<<" production sorting checks\n";
}
'''
    code = fixture.replace('// HELPERS', helpers).replace('// METHODS', methods)
    with tempfile.TemporaryDirectory(prefix='telegram-strict-order-') as directory:
        source = Path(directory) / 'model.cpp'
        binary = Path(directory) / 'model'
        source.write_text(code)
        subprocess.run([args.cxx, '-std=c++20', '-Wall', '-Wextra', '-Werror', str(source), '-o', str(binary)], check=True, timeout=45)
        subprocess.run([str(binary)], check=True, timeout=10)


if __name__ == '__main__':
    main()
