#pragma once
#include <stdint.h>
#include <stdlib.h>

// Buttons commit only after release. A drag can never also emit a tap.
class TouchGesture {
public:
    enum class Kind { None, Tap, Left, Right };
    struct Event { Kind kind=Kind::None; int x=0,y=0; };
    bool tracking() const { return active; }
    Event update(bool down,int x,int y,uint32_t now) {
        if(down) {
            if(!active) {active=true;moved=false;startX=x;startY=y;started=now;}
            releasing=false;lastX=x;lastY=y;
            if(abs(x-startX)>14 || abs(y-startY)>14)moved=true;
            return {};
        }
        if(!active)return {};
        if(!releasing) {releasing=true;released=now;return {};}
        if(uint32_t(now-released)<30)return {};
        active=releasing=false;
        uint32_t duration=released-started;
        int dx=lastX-startX,dy=lastY-startY;
        if(duration<=1500 && abs(dx)>=70 && abs(dx)*2>abs(dy)*3)
            return {dx<0?Kind::Left:Kind::Right,startX,startY};
        if(!moved && duration<=650)return {Kind::Tap,startX,startY};
        return {};
    }
private:
    bool active=false,releasing=false,moved=false;
    int startX=0,startY=0,lastX=0,lastY=0;
    uint32_t started=0,released=0;
};
