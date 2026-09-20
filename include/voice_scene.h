#pragma once
// Shared by the board and the desktop raster preview. No audio or transport side effects.
#include <stdint.h>
#include <math.h>
#include <string.h>
#include <stdio.h>

namespace VoiceScene {
constexpr uint16_t mint=0xA7BA, violet=0xC55F, amber=0xF632, text=0xEF7D, dim=0x8D53;
inline uint16_t blend(uint16_t a,uint16_t b,unsigned alpha) {
    if(alpha>=255)return b;
    unsigned inverse=256-alpha;
    return uint16_t(((((a>>11)*inverse+(b>>11)*alpha)>>8)<<11)|
        (((((a>>5)&63)*inverse+((b>>5)&63)*alpha)>>8)<<5)|(((a&31)*inverse+(b&31)*alpha)>>8));
}
inline uint16_t backgroundColor(int x,int y) {
    float r=float((x-233)*(x-233)+(y-233)*(y-233))/(232*232);
    if(r>1)r=1;r*=r;
    // Stable ordered dithering keeps this very dark RGB565 ramp from banding.
    static const unsigned char bayer[]={0,8,2,10,12,4,14,6,3,11,1,9,15,7,13,5};
    float d=bayer[(y&3)*4+(x&3)]/16.0f;
    unsigned red=unsigned((2+10*r)*31/255+d),green=unsigned((5+24*r)*63/255+d),blue=unsigned((13+42*r)*31/255+d);
    return uint16_t((red<<11)|(green<<5)|blue);
}
struct OrbPixel { uint16_t x,y,angle,radius; };
struct OrbCache { OrbPixel* pixels=nullptr;unsigned count=0;uint8_t alpha[3073]={0}; };
constexpr unsigned orbCapacity=44000,orbSamples=512;
inline void prepareOrb(OrbCache& cache,OrbPixel* pixels) {
    cache.pixels=pixels;cache.count=0;if(!pixels)return;
    for(int y=74;y<=354;++y)for(int x=93;x<=373;++x) {
        int dx=x-233,dy=y-214,rr=dx*dx+dy*dy;
        if(rr<84*84 || rr>140*140)continue;
        float angle=atan2f(float(dy),float(dx));if(angle<0)angle+=6.28318530718f;
        OrbPixel& p=cache.pixels[cache.count++];p.x=x;p.y=y;
        p.angle=uint16_t(angle*(65536.0f/6.28318530718f));p.radius=uint16_t(sqrtf(float(rr))*256+.5f);
    }
    for(int i=0;i<=3072;++i){float d=i/256.0f,core=(2.15f-d)/.9f;
        if(core<0)core=0;if(core>1)core=1;
        float glow=.19f*expf(-d*d/18.0f);
        cache.alpha[i]=uint8_t((1-(1-core*.90f)*(1-glow))*255+.5f);
    }
}
enum class State { Ready, Listening, Thinking, Speaking, Muted, Offline, Reply, Notice, Music, Alarm, Recording, Playback, Chime, MicUnavailable };
struct Input {
    bool connected=false, muted=false, micReady=true, listening=false, thinking=false;
    bool reply=false, notice=false, music=false, alarm=false;
    // Same order as AudioMode, deliberately independent of the driver headers.
    unsigned mode=0;
};
inline State resolve(const Input& i) {
    if (i.mode==4) return i.music?State::Music:i.alarm?State::Alarm:State::Speaking;
    if (i.mode==2) return State::Playback;
    if (i.mode==3) return State::Chime;
    if (i.muted) return State::Muted;
    if (i.mode==1) return State::Recording;
    if (!i.connected) return State::Offline;
    if (!i.micReady) return State::MicUnavailable;
    if (i.listening) return State::Listening;
    if (i.thinking) return State::Thinking;
    if (i.notice) return State::Notice;
    if (i.reply) return State::Reply;
    return State::Ready;
}
inline const char* name(State s) {
    static const char* names[]={"ready","listening","thinking","speaking","muted","offline","reply","notice","music","alarm","recording","playback","chime","mic_unavailable"};
    return names[unsigned(s)];
}
inline bool busy(State s) {
    return s==State::Listening || s==State::Thinking || s==State::Speaking || s==State::Music || s==State::Alarm || s==State::Recording || s==State::Playback || s==State::Chime;
}
inline uint16_t mix(uint16_t a,uint16_t b,float f) {
    if(f<0)f=0; if(f>1)f=1;
    int r=int((a>>11)*(1-f)+(b>>11)*f+.5f);
    int g=int(((a>>5)&63)*(1-f)+((b>>5)&63)*f+.5f);
    int bl=int((a&31)*(1-f)+(b&31)*f+.5f);
    return uint16_t((r<<11)|(g<<5)|bl);
}
inline uint16_t accent(State s) {
    if(s==State::Thinking || s==State::Speaking || s==State::Music || s==State::Playback)return violet;
    if(s==State::Muted || s==State::Alarm || s==State::Notice)return amber;
    if(s==State::Offline || s==State::MicUnavailable)return dim;
    return mint;
}
struct Model {
    State state=State::Offline;
    bool connected=false, powerKnown=false, battery=false, charging=false, micMuted=false,guest=false;
    int percent=-1, volume=0;
    float peak=0;
    const char* response="";const char* personalName="";
};
struct Animation {
    float level=0, motion=0, red=0, green=0, blue=0;
    bool initialized=false;
};
template<class Surface> void label(Surface& g,const char* s,int y,uint16_t c) { g.text(s,233,y,0,c); }
template<class Surface> void fit(Surface& g,const char* s,int y,int width,uint16_t c) {
    char value[128]; size_t n=strlen(s); if(n>127)n=127; memcpy(value,s,n);value[n]=0;
    if(g.width(value,1)>width) {
        while(n && g.width(value,1)>width-16)value[--n]=0;
        if(n<=124)strcat(value,"...");
    }
    g.text(value,233,y,1,c);
}
template<class Surface> void response(Surface& g,const char* s,uint16_t c) {
    // Wrap complete words, with an ellipsis on overflow. Never run text into the orb or controls.
    char line[128]={0}; size_t n=0,split=0;
    while(s[n] && n<126) {
        line[n]=s[n];line[n+1]=0;
        if(g.width(line,1)>198)break;
        if(s[n]==' ')split=n;
        ++n;
    }
    if(!s[n]) { fit(g,line,238,198,c);return; }
    if(split)n=split;
    line[n]=0;fit(g,line,230,198,c);
    while(s[n]==' ')++n;
    fit(g,s+n,254,194,c);
}
template<class Surface> void icon(Surface& g,int x,int y,int type,uint16_t c) {
    if(type==0) { // Home
        g.line(x-9,y-1,x,y-9,c);g.line(x,y-9,x+9,y-1,c);
        g.line(x-6,y-3,x-6,y+8,c);g.line(x+6,y-3,x+6,y+8,c);g.line(x-6,y+8,x+6,y+8,c);
        g.line(x-2,y+8,x-2,y+2,c);g.line(x-2,y+2,x+2,y+2,c);g.line(x+2,y+2,x+2,y+8,c);
    } else if(type==1) { // Microphone
        g.roundRect(x-3,y-10,7,14,3,c,false);
        g.line(x-7,y-1,x-7,y+4,c);g.line(x+7,y-1,x+7,y+4,c);
        g.line(x-7,y+4,x-3,y+8,c);g.line(x+7,y+4,x+3,y+8,c);g.line(x-3,y+8,x+3,y+8,c);
        g.line(x,y+8,x,y+12,c);g.line(x-4,y+12,x+4,y+12,c);
    } else { // Music
        g.line(x-3,y+6,x-3,y-8,c);g.line(x-3,y-8,x+8,y-10,c);g.line(x+8,y-10,x+8,y+4,c);
        g.line(x-3,y-4,x+8,y-6,c);g.circle(x-6,y+7,3,c);g.circle(x+5,y+5,3,c);
    }
}
template<class Surface> void header(Surface& g,const Model& m,uint16_t color,const char* status=nullptr) {
    if(m.micMuted || m.state==State::Muted) { status="MICROPHONE MUTED"; color=amber; }
    const char* heading=status?status:m.connected?(m.personalName[0]?m.personalName:m.guest?"ECHO / GUEST":"ECHO ASSISTANT"):"HOST OFFLINE";
    g.circle(233-g.width(heading,0)/2-10,49,2,m.connected?color:dim);
    g.text(heading,233,53,0,m.micMuted || m.state==State::Muted?amber:dim);
    char power[40];
    if(!m.powerKnown)strcpy(power,"POWER UNKNOWN");
    else if(!m.battery)strcpy(power,"EXTERNAL POWER");
    else if(m.percent<0)strcpy(power,m.charging?"BATTERY / CHARGING":"BATTERY / --");
    else snprintf(power,sizeof(power),m.charging?"%d%% / CHARGING":"BATTERY / %d%%",m.percent);
    label(g,power,77,dim);
    // Draw a charging bolt instead of relying on unsupported font glyphs.
    if(m.charging) { int bx=233-g.width(power,0)/2-14;
        g.line(bx+5,65,bx,72,mint);g.line(bx,72,bx+5,72,mint);g.line(bx+5,72,bx,79,mint); }

}
template<class Surface> void volumeControl(Surface& g,const Model& m) {
    g.roundRect(154,382,45,42,21,0x10E3,true);g.roundRect(267,382,45,42,21,0x10E3,true);
    g.line(171,402,181,402,dim);g.line(284,402,294,402,dim);g.line(289,397,289,407,dim);
    char volume[12];snprintf(volume,sizeof(volume),"%d%%",m.volume);g.text(volume,233,409,1,dim);
    label(g,m.micMuted || m.state==State::Muted?"SOFTWARE MIC MUTE":m.volume==0?"SOUND OFF / TOUCH TO ADJUST":"ECHO VOLUME",440,dim);
}
template<class Surface> void render(Surface& g,const Model& m,float t,Animation& a) {
    const State state=m.state;
    uint16_t target=accent(state);
    float targetMotion=state==State::Muted || state==State::Offline || state==State::MicUnavailable?0:
        state==State::Listening || state==State::Recording?2.4f+7*m.peak:
        state==State::Speaking?4.5f:state==State::Thinking?3.0f:1.4f;
    if(!a.initialized) { a.red=target>>11;a.green=(target>>5)&63;a.blue=target&31;a.motion=targetMotion;a.initialized=true; }
    a.red+=((target>>11)-a.red)*.22f;a.green+=(((target>>5)&63)-a.green)*.22f;a.blue+=((target&31)-a.blue)*.22f;
    a.motion+=(targetMotion-a.motion)*.2f;a.level+=(m.peak-a.level)*.28f;
    uint16_t color=uint16_t((int(a.red+.5f)<<11)|(int(a.green+.5f)<<5)|int(a.blue+.5f));
    const bool quiet=state==State::Muted || state==State::Offline || state==State::MicUnavailable;
    const float clock=quiet?0:t;
    g.background();
    uint16_t radii[orbSamples+1],colors[orbSamples];
    for(unsigned j=0;j<=orbSamples;++j) {
        float angle=j*6.28318530718f/orbSamples;
        float r=112+a.motion*(sinf(angle*5+clock*1.7f)+.6f*sinf(angle*3-clock*.9f));
        radii[j]=uint16_t(r*256+.5f);
        if(j<orbSamples) {
            float shimmer=.5f+.5f*sinf(angle-clock*.8f);
            colors[j]=mix(color,quiet?color:state==State::Thinking?violet:mint,shimmer*.26f);
        }
    }
    const auto& cache=g.orb();
    // Polar geometry is cached once in PSRAM. Per frame, interpolate the curve
    // and sample an antialiased 3px core plus its soft underglow, once per pixel.
    for(unsigned j=0;j<cache.count;++j) {
        const auto& p=cache.pixels[j];unsigned n=p.angle>>7,fraction=p.angle&127;
        int r=(int(radii[n])*(128-fraction)+int(radii[n+1])*fraction)>>7;
        int distance=int(p.radius)-r;if(distance<0)distance=-distance;
        if(distance>3072)continue;
        unsigned alpha=cache.alpha[distance];if(quiet)alpha=alpha*3/5;
        if(alpha)g.alphaPixel(p.x,p.y,colors[n],alpha);
    }
    if(!cache.count) { // Retain a visible ring if optional scene-cache allocation fails.
        for(unsigned n=0;n<orbSamples;++n){float angle=n*6.28318530718f/orbSamples;
            g.circle(int(233+cosf(angle)*radii[n]/256),int(214+sinf(angle)*radii[n]/256),1,color);}
    }
    if(state==State::Thinking) {
        float angle=fmodf(t*.16f,1.0f)*6.28318530718f;unsigned n=unsigned(fmodf(t*.16f,1.0f)*orbSamples);
        int x=int(233+cosf(angle)*radii[n]/256),y=int(214+sinf(angle)*radii[n]/256);
        g.circle(x,y,2,text);
    }
    header(g,m,color);

    const char *micro="READY WHEN YOU ARE",*title="Hello, there.",*one="Say \"Hey Echo\"",*two="or \"Okay Echo\".";
    switch(state) {
        case State::Listening:micro="LISTENING";title="Go ahead.";one="I'm listening.";two="";break;
        case State::Thinking:micro="WORKING ON IT";title="One moment.";one="Working on";two="your reply.";break;
        case State::Speaking:micro=m.volume?"SPEAKING":"REPLY / SOUND OFF";title="Your reply.";one="";two="";break;
        case State::Muted:micro="MICROPHONE MUTED";title="A little quiet.";one="Voice capture is off.";two="Tap PWR to unmute.";break;
        case State::Offline:micro="ASSISTANT OFFLINE";title="Still here.";one="Waiting for your host.";two="Settings are available.";break;
        case State::Reply:micro="REPLY";title="Your reply.";one="";two="";break;
        case State::Notice:micro="TRY AGAIN";title="Let's try again.";one="";two="";break;
        case State::Music:micro=m.volume?"SPOTIFY CONNECT":"MUSIC / SOUND OFF";title="Your music.";one="Open Music for";two="playback controls.";break;
        case State::Alarm:micro="TIMER FINISHED";title="Time's up.";one=m.volume?"Your timer has finished.":"Sound is turned off.";two="";break;
        case State::Recording:micro="MICROPHONE TEST";title="Test recording.";one="Eight-second RAM test";two="";break;
        case State::Playback:micro="SPEAKER TEST";title="Test playback.";one=m.volume?"Playing the RAM sample.":"Sound is turned off.";two="";break;
        case State::Chime:micro="READY FOR YOU";title="I'm here.";one="Go ahead in a moment.";two="";break;
        case State::MicUnavailable:micro="MIC UNAVAILABLE";title="Still here.";one="Microphone isn't ready.";two="Touch is still available.";break;
        default:break;
    }
    label(g,micro,158,color);
    g.text(title,233,201,g.width(title,2)<=246?2:1,text);
    if(state==State::Reply || state==State::Notice || state==State::Speaking)response(g,m.response[0]?m.response:"Request received.",dim);
    else {fit(g,one,234,206,dim);fit(g,two,257,206,dim);}
    if(state==State::Listening || state==State::Recording) {
        for(int j=0;j<9;++j) {
            float envelope=.35f+.65f*(1-fabsf(j-4)/5);
            int h=3+int(17*a.level*envelope*(.7f+.3f*sinf(t*7+j*.8f)));
            g.roundRect(201+j*8,279-h/2,3,h,1,color,true);
        }
    } else if(state==State::Thinking) {
        for(int j=0;j<3;++j)g.circle(221+j*12,282,2,mix(0,color,.25f+.55f*(.5f+.5f*sinf(t*4-j))));
    } else { g.line(221,282,245,282,mix(0,color,.4f)); }
    if(busy(state)) {
        g.roundRect(177,333,112,42,21,mix(0,color,.11f),true);
        g.roundRect(177,333,112,42,21,mix(0,color,.32f),false);
        g.text("Stop",233,360,1,color);
    } else {
        for(int j=0;j<3;++j) {
            int bx=122+j*111;bool active=j==1 && state!=State::Muted && state!=State::Offline && state!=State::MicUnavailable;
            uint16_t fg=active?0x1126:j==1?dim:color;
            g.circle(bx,354,21,active?color:mix(0,color,.09f));
            icon(g,bx,353,j,fg);
            if(j==1 && state==State::Muted)g.line(bx-10,343,bx+10,363,amber);
        }
    }
    volumeControl(g,m);
}
} // namespace VoiceScene
