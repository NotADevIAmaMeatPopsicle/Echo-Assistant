#pragma once
#include <stdint.h>

// A complete short press, never a held startup key or a failed I2C read.
// Time arithmetic remains valid across the millis() rollover.
class MuteButton {
    int candidate=-1, stable=-1;
    uint32_t candidateAt=0, pressedAt=0, lastSample=0;
    bool seen=false, released=false, pressed=false;
public:
    bool update(int level,uint32_t now) {
        if (level<0 || (seen && uint32_t(now-lastSample)>250)) {
            candidate=stable=-1; seen=released=pressed=false;
            if(level<0)return false;
        }
        lastSample=now; seen=true;
        if(level!=candidate) { candidate=level; candidateAt=now; return false; }
        if(uint32_t(now-candidateAt)<30 || stable==candidate)return false;
        stable=candidate;
        if(stable) {
            pressed=released; released=false; pressedAt=candidateAt;
            return false;
        }
        bool tap=pressed && uint32_t(candidateAt-pressedAt)<1000;
        released=true; pressed=false;
        return tap;
    }
};
