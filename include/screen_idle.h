#pragma once
#include <stdint.h>

// Screen-only idle state; audio and networking never enter MCU sleep.
class ScreenIdle {
public:
    enum class Level { Awake, Dim, Off };
    uint32_t dimSeconds=120,offSeconds=600;
    Level level=Level::Awake;
    static bool allowed(uint32_t value) { return value==0 || value==60 || value==120 || value==300 || value==600 || value==900; }
    bool configure(uint32_t dim,uint32_t off) {
        if(!allowed(dim) || !allowed(off) || (off && dim>=off))return false;
        dimSeconds=dim;offSeconds=off;return true;
    }
    bool activity(uint32_t now) {
        bool wasOff=level==Level::Off;lastActivity=now;manual=false;level=Level::Awake;return wasOff;
    }
    void sleep() { manual=true;level=Level::Off; }
    Level update(uint32_t now,bool engaged) {
        if(engaged)activity(now);
        uint32_t elapsed=uint32_t(now-lastActivity)/1000;
        level=manual || (offSeconds && elapsed>=offSeconds)?Level::Off:
              dimSeconds && elapsed>=dimSeconds?Level::Dim:Level::Awake;
        return level;
    }
private:
    uint32_t lastActivity=0;
    bool manual=false;
};
