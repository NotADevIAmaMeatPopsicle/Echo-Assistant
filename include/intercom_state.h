#pragma once
#include <stdint.h>
#include <string.h>
#include <stdio.h>

// Consent is local, volatile and tied to one call. Host status cannot grant it.
struct IntercomState {
    enum Phase { Idle, Incoming, Outgoing, Active } phase=Idle;
    bool enabled=false,ready=false,muted=true,localMuted=true;
    bool awaiting=false;
    uint32_t requestedAt=0;
    uint32_t at=0,seconds=0,received=0;
    unsigned count=0,offset=0;
    char id[33]="",consent[33]="",binding[17]="",room[33]="",notice[33]="Calls off";
    char rooms[32][33]{};
    uint32_t available=0;
    bool busy() const { return phase!=Idle; }
    bool capture(bool globalMuted) const {
        return enabled && !globalMuted && phase==Active && !muted && id[0] && strcmp(id,consent)==0;
    }
    static bool identifier(const char* s) {return strlen(s)==32 && strspn(s,"0123456789abcdef")==32;}
    bool authorize(const char* value) {
        if(!enabled || !identifier(value))return false;
        snprintf(consent,sizeof(consent),"%s",value);localMuted=false;return true;
    }
    void clear(bool disable=false) {
        phase=Idle;id[0]=consent[0]=0;muted=localMuted=true;seconds=0;awaiting=false;
        if(disable){enabled=ready=false;count=received=available=0;at=0;}
    }
    void state(const char* value,Phase next,bool mute,uint32_t now) {
        // A heartbeat already in the transport can still say idle just after
        // the local Call tap. Retain that consent until acknowledged or timed out.
        if(next==Idle){if(awaiting && uint32_t(now-requestedAt)<3000)return;clear();at=now;return;}
        if(!identifier(value))return;
        if(strcmp(id,value)!=0 && strcmp(consent,value)!=0)consent[0]=0;
        snprintf(id,sizeof(id),"%s",value);phase=next;muted=mute || localMuted;at=now;awaiting=false;
    }
};
