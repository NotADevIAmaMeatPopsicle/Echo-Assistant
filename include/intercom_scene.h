#pragma once
#include "control_scene.h"
#include "intercom_state.h"

namespace IntercomScene {
template<class Surface> void render(Surface& g,const IntercomState& intercom,const VoiceScene::Model& system) {
    using namespace ControlScene;
    constexpr uint16_t AMBER=VoiceScene::amber,MINT=VoiceScene::mint,DIM=VoiceScene::dim;
    bool wakeArmed=system.connected,wakeMuted=system.micMuted;
    g.background();
        VoiceScene::header(g,system,intercom.muted?AMBER:MINT,"ROOM INTERCOM");
        centered(g,"Room intercom",123,2);
        if(intercom.busy()) {
            centered(g,intercom.room,172,2,MINT);
            centered(g,intercom.phase==IntercomState::Incoming?"Incoming call":intercom.phase==IntercomState::Outgoing?"Calling...":intercom.muted?"Your microphone is muted":"Connected / live audio",207,1,DIM);
            char elapsed[32];snprintf(elapsed,sizeof(elapsed),"%02lu:%02lu",(unsigned long)intercom.seconds/60,(unsigned long)intercom.seconds%60);
            centered(g,intercom.phase==IntercomState::Active?elapsed:"Microphone stays closed until answered",239,0,DIM);
            pill(g,95,275,132,intercom.phase==IntercomState::Incoming?"Answer":intercom.phase==IntercomState::Outgoing?"Waiting":intercom.muted?"Unmute":"Mute",MINT,intercom.phase!=IntercomState::Outgoing && !wakeMuted);
            pill(g,239,275,132,intercom.phase==IntercomState::Incoming?"Decline":"Hang up",AMBER);
        } else {
            centered(g,!wakeArmed?"Host disconnected":wakeMuted?"Unmute on Home to receive calls":intercom.notice,147,0,DIM);
            if(!intercom.enabled) {
                centered(g,"Call another Echo room",205,1,DIM);centered(g,"Each call needs an answer",234,0,DIM);
                pill(g,125,275,216,"Enable calls here",MINT,wakeArmed && !wakeMuted);
            } else {
                for(unsigned j=0;j<2 && intercom.offset+j<intercom.count;++j) {
                    unsigned i=intercom.offset+j;
                    pill(g,95,164+j*48,276,intercom.rooms[i],MINT,intercom.ready && (intercom.available&(1u<<i)) && (intercom.received&(1u<<i)));
                }
                if(!intercom.count)centered(g,"Assign rooms in the web app",205,1,DIM);
                pill(g,95,274,82,"Prev",DIM,intercom.offset>0);pill(g,183,274,100,"Off",AMBER);pill(g,289,274,82,"Next",DIM,intercom.offset+2<intercom.count);
            }
        }
        Model controls;controls.system=system;controls.micMuted=wakeMuted;controls.micReady=true;controls.page=Page::Intercom;
        if(intercom.busy())centered(g,"Top: mute / bottom: hang up",355,0,DIM);
        else navigation(g,controls);
        VoiceScene::volumeControl(g,system);
}
}
