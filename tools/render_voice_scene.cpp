// Silent desktop rendering of the same C++ scene and font bitmaps as the board.
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <vector>
#include <string>
#include <algorithm>
#include <assert.h>
#define PROGMEM
#include "../lib/ArduinoGFX/src/gfxfont.h"
#include "../lib/ArduinoGFX/src/font/glcdfont.h"
#include "../include/fonts/FreeSans9pt7b.h"
#include "../include/fonts/FreeSans18pt7b.h"
#include "../include/voice_scene.h"
#include "../include/control_scene.h"
#include "../include/home_action_state.h"
#include "../include/ui_type.h"
#include "../include/mute_button.h"
#include "../include/touch_gesture.h"

struct Raster {
    std::vector<uint16_t> pixels=std::vector<uint16_t>(466*466,0);
    unsigned clipped=0;
    std::vector<std::string> labels;
    void background() {
        static std::vector<uint16_t> image;
        if(image.empty()){image.resize(466*466);for(int y=0;y<466;++y)for(int x=0;x<466;++x)image[y*466+x]=VoiceScene::backgroundColor(x,y);}
        pixels=image;
    }
    const VoiceScene::OrbCache& orb() {
        static std::vector<VoiceScene::OrbPixel> points(VoiceScene::orbCapacity);
        static VoiceScene::OrbCache cache;
        if(!cache.pixels)VoiceScene::prepareOrb(cache,points.data());
        assert(cache.count<VoiceScene::orbCapacity);return cache;
    }
    void alphaPixel(int x,int y,uint16_t c,unsigned a) {
        if(x<0 || x>=466 || y<0 || y>=466){++clipped;return;}
        pixels[y*466+x]=VoiceScene::blend(pixels[y*466+x],c,a);
    }
    void pixel(int x,int y,uint16_t c) {
        if(x<0 || x>=466 || y<0 || y>=466){++clipped;return;}
        pixels[y*466+x]=c;
    }
    void line(int x,int y,int xx,int yy,uint16_t c) {
        int dx=abs(xx-x),sx=x<xx?1:-1,dy=-abs(yy-y),sy=y<yy?1:-1,err=dx+dy;
        for(;;){pixel(x,y,c);if(x==xx && y==yy)break;int e=2*err;if(e>=dy){err+=dy;x+=sx;}if(e<=dx){err+=dx;y+=sy;}}
    }
    void circle(int x,int y,int r,uint16_t c) {
        for(int yy=-r;yy<=r;++yy){int w=int(sqrtf(float(r*r-yy*yy)));line(x-w,y+yy,x+w,y+yy,c);}
    }
    void roundRect(int x,int y,int w,int h,int r,uint16_t c,bool fill) {
        r=std::min(r,std::min(w,h)/2);
        for(int j=0;j<h;++j)for(int i=0;i<w;++i) {
            int dx=i<r?r-i:i>=w-r?i-(w-r-1):0;
            int dy=j<r?r-j:j>=h-r?j-(h-r-1):0;
            if(dx*dx+dy*dy>r*r)continue;
            bool edge=i==0 || j==0 || i==w-1 || j==h-1 || ((dx || dy) && dx*dx+dy*dy>(r-1)*(r-1));
            if(fill || edge)pixel(x+i,y+j,c);
        }
    }
    int width(const char* s,unsigned size) { return UiType::width(s,size); }
    void text(const char* s,int cx,int baseline,unsigned size,uint16_t color) { labels.emplace_back(s);UiType::draw(*this,s,cx,baseline,size,color); }
    bool has(const char* s) const { return std::find(labels.begin(),labels.end(),s)!=labels.end(); }
    void checkBounds() const {
        assert(clipped==0);
        for(int y=0;y<466;++y)for(int x=0;x<466;++x)
            if(pixels[y*466+x]!=VoiceScene::backgroundColor(x,y))assert((x-233)*(x-233)+(y-233)*(y-233)<=232*232);
    }
    void save(const char* file) {
        FILE* out=fopen(file,"wb");assert(out);fprintf(out,"P6\n466 466\n255\n");
        for(auto c:pixels){fputc((c>>11)*255/31,out);fputc(((c>>5)&63)*255/63,out);fputc((c&31)*255/31,out);}fclose(out);
    }
};
static void checkStates() {
    using namespace VoiceScene;Input i;
    assert(resolve(i)==State::Offline);
    i.connected=true;assert(resolve(i)==State::Ready);
    i.listening=true;assert(resolve(i)==State::Listening); // command capture while AudioMode is Idle
    i.listening=false;i.thinking=true;assert(resolve(i)==State::Thinking);
    i.mode=4;assert(resolve(i)==State::Speaking);
    i.music=true;assert(resolve(i)==State::Music);
    i.muted=true;assert(resolve(i)==State::Music); // mic mute does not stop music
    i.mode=0;assert(resolve(i)==State::Muted);
    i.muted=false;i.connected=false;assert(resolve(i)==State::Offline); // stale thinking cannot mask disconnect
    i.connected=true;i.micReady=false;assert(resolve(i)==State::MicUnavailable);
    i.micReady=true;i.thinking=false;i.reply=true;assert(resolve(i)==State::Reply);
    i.notice=true;assert(resolve(i)==State::Notice);
    i.mode=1;assert(resolve(i)==State::Recording);
    i.mode=2;assert(resolve(i)==State::Playback);
    i.mode=3;assert(resolve(i)==State::Chime);
    i.mode=4;i.music=false;i.alarm=true;assert(resolve(i)==State::Alarm);
    HomeActionState action;
    assert(action.begin(100));uint32_t first=action.request;
    assert(!action.begin(150));assert(action.pending());
    assert(!action.acknowledge(first+1,"accepted",200));
    assert(!action.acknowledge(first,"invented",200));
    assert(action.acknowledge(first,"pending",5000));
    action.tick(15100,true);assert(action.phase==HomeActionState::Phase::Unconfirmed);
    assert(!action.acknowledge(first,"accepted",15101));
    assert(action.begin(16000));assert(!action.acknowledge(first,"accepted",16001));
    assert(action.acknowledge(action.request,"accepted",16002));
    action.tick(24002,true);assert(action.phase==HomeActionState::Phase::Idle);
    assert(action.begin(0xfffffff0));action.tick(0x3a88,true);assert(action.phase==HomeActionState::Phase::Unconfirmed);
    assert(action.begin(100));action.tick(101,false);assert(action.phase==HomeActionState::Phase::Unconfirmed);
    action.request=0xffffffff;assert(action.begin(200));assert(action.request==1);
    using namespace TouchTargets;
    assert(microphone.contains(233,174));
    for(int x:{0,50,98,367,400,465})assert(!microphone.contains(x,174));
    assert(!microphone.contains(233,152));assert(!microphone.contains(233,195));
    assert(brightnessDown.contains(150,250));assert(brightnessUp.contains(290,250));
    for(int x:{0,100,233,400,465}){assert(!brightnessDown.contains(x,250));assert(!brightnessUp.contains(x,250));}
    assert(musicPrevious.contains(140,303));assert(musicToggle.contains(233,303));assert(musicNext.contains(320,303));
    for(int x:{0,100,182,284,360,465}){assert(!musicPrevious.contains(x,303));assert(!musicToggle.contains(x,303));assert(!musicNext.contains(x,303));}
    assert(navHome.contains(122,354));assert(navTalk.contains(233,354));assert(navMusic.contains(344,354));
    assert(!navHome.contains(30,354));assert(!navMusic.contains(440,354));
    assert(homeBose.contains(160,185) && homeThermostat.contains(300,185));
    assert(!homeBose.contains(233,185) && !homeThermostat.contains(233,185));
    for(int j=0;j<4;++j) {auto r=roomLights[j];assert(r.contains(r.x+60,r.y+35));assert(!r.contains(233,r.y+35));}
    using MusicUi::State;
    for(const char* status:{"not_configured","runtime_missing","unavailable","disconnected","discoverable","unexpected",""}) {
        auto state=MusicUi::resolve(true,status);
        assert(!MusicUi::canToggle(state) && !MusicUi::canSkip(state));
    }
    assert(MusicUi::resolve(true,"playing")==State::Playing);
    assert(MusicUi::resolve(true,"paused")==State::Paused);
    assert(MusicUi::resolve(true,"stopped")==State::Stopped);
    auto connected=MusicUi::resolve(true,"connected");
    assert(MusicUi::canToggle(connected) && !MusicUi::canSkip(connected));
    for(const char* status:{"connected","playing","paused","stopped"}) {
        auto stale=MusicUi::resolve(false,status);
        assert(stale==State::Offline && !MusicUi::canToggle(stale) && !MusicUi::canSkip(stale));
    }
    for(auto state:{State::Playing,State::Paused,State::Stopped})assert(MusicUi::canToggle(state) && MusicUi::canSkip(state));
}
int main(int argc,char** argv) {
    using namespace VoiceScene;
    checkStates();
    for(auto p:{ControlScene::Page::Soundbar,ControlScene::Page::SoundbarVolume,ControlScene::Page::SpeakerPicker}) {
        assert(strcmp(ControlScene::physicalAction(p,true),"sound_up")==0);
        assert(strcmp(ControlScene::physicalAction(p,false),"sound_down")==0);
    }
    for(auto p:{ControlScene::Page::Thermostat,ControlScene::Page::ThermostatMode}) {
        assert(strcmp(ControlScene::physicalAction(p,true),"temp_up")==0);
        assert(strcmp(ControlScene::physicalAction(p,false),"temp_down")==0);
    }
    for(auto p:{ControlScene::Page::Home,ControlScene::Page::Voice}) {
        assert(strcmp(ControlScene::physicalAction(p,true),"mic_toggle")==0);
        assert(strcmp(ControlScene::physicalAction(p,false),"")==0);
    }
    assert(ControlScene::swipePage(ControlScene::Page::SpeakerPicker,false)==ControlScene::Page::Soundbar);
    {
        using K=TouchGesture::Kind;
        auto release=[](TouchGesture& g,uint32_t t) {assert(g.update(false,0,0,t).kind==K::None);return g.update(false,0,0,t+35);};
        TouchGesture g;
        assert(g.update(true,320,170,0).kind==K::None);
        g.update(true,160,172,200);assert(release(g,240).kind==K::Left);
        assert(g.update(false,0,0,300).kind==K::None); // no trailing tap
        g.update(true,140,170,400);g.update(true,280,180,500);assert(release(g,540).kind==K::Right);
        g.update(true,150,170,600);g.update(true,150,270,700);assert(release(g,740).kind==K::None);
        g.update(true,150,170,800);g.update(true,180,170,830);g.update(true,150,170,860);assert(release(g,900).kind==K::None);
        g.update(true,150,170,1000);assert(g.update(false,0,0,1020).kind==K::None);
        g.update(true,153,172,1030);auto tap=release(g,1100);assert(tap.kind==K::Tap && tap.x==150 && tap.y==170);
        g.update(true,150,170,1200);assert(release(g,2100).kind==K::None); // held button
        g.update(true,150,170,0xfffffff0);assert(release(g,0x40).kind==K::Tap);
        using P=ControlScene::Page;
        assert(ControlScene::swipePage(P::Voice,true)==P::Home);
        assert(ControlScene::swipePage(P::Home,true)==P::Soundbar);
        assert(ControlScene::swipePage(P::Lights,false)==P::Thermostat);
        assert(ControlScene::swipePage(P::NewTimer,false)==P::Timer);
        assert(ControlScene::swipePage(P::ThermostatMode,false)==P::Thermostat);
        assert(ControlScene::swipePage(P::Voice,false)==P::Settings);
        assert(ControlScene::swipePage(P::Settings,true)==P::Voice);
        puts("PASS: swipe navigation, release-only taps, drag/hold rejection, touch dropout and rollover");
    }
    // Same button state machine as firmware: no GPIO emulation or hardware IO.
    {
        MuteButton key; uint32_t now=0; unsigned taps=0;
        auto hold=[&](int level,int ms) { for(int n=0;n<ms;n+=10) { taps+=key.update(level,now);now+=10; } };
        hold(1,300);hold(0,100);assert(taps==0); // Held at boot: ignore release.
        hold(1,10);hold(0,10);hold(1,10);hold(0,100);assert(taps==0); // Bounce.
        hold(1,120);hold(0,100);assert(taps==1);
        hold(0,200);assert(taps==1); // No repeats after release.
        hold(1,1600);hold(0,100);assert(taps==1); // Long hold is power, not mute.
        hold(1,80);hold(-1,10);hold(1,100);hold(0,100);assert(taps==1); // Bus fault.
        hold(1,120);hold(0,100);assert(taps==2); // Recovers after release.
        hold(1,80);now+=1000;hold(0,100);assert(taps==2); // Lost observation.
        key=MuteButton{};now=0xffffff80;taps=0;
        hold(0,80);hold(1,120);hold(0,100);assert(taps==1); // millis rollover.
        puts("PASS: mute button bounce, startup, hold, repeat, bus-fault and rollover cases");
    }
    const char* directory=argc>1?argv[1]:".";
    {
        Raster raster;ControlScene::Model m;m.page=ControlScene::Page::Music;
        m.system.connected=true;m.system.powerKnown=true;m.system.volume=2;
        m.system.state=State::Music;m.system.micMuted=true;m.micMuted=true;
        m.musicConnected=true;m.musicState="playing";m.musicTitle="Crab Rave";m.musicArtist="Noisestorm";
        ControlScene::render(raster,m);raster.checkBounds();
        assert(raster.has("MICROPHONE MUTED") && raster.has("SOFTWARE MIC MUTE") && raster.has("Pause"));
        char file[1024];snprintf(file,sizeof(file),"%s/music-muted.ppm",directory);raster.save(file);
    }
    const char* musicStatuses[]={"not_configured","runtime_missing","unavailable","disconnected","discoverable","connected","playing","stopped","unexpected"};
    for(const char* status:musicStatuses) {
        Raster raster;ControlScene::Model m;m.page=ControlScene::Page::Music;
        m.system.connected=true;m.system.powerKnown=true;m.musicConnected=true;
        m.musicState=status;m.musicTitle="Crab Rave";m.musicArtist="Noisestorm";
        ControlScene::render(raster,m);raster.checkBounds();
        auto state=MusicUi::resolve(true,status);
        assert(raster.has(MusicUi::detail(state,0)));
        assert(raster.has("Crab Rave")==MusicUi::canSkip(state));
        assert(raster.has("Noisestorm")==MusicUi::canSkip(state));
        if(state==MusicUi::State::Playing)assert(raster.has("Pause") && raster.has("Playing / sound off"));
        char file[1024];snprintf(file,sizeof(file),"%s/spotify-%s.ppm",directory,status);raster.save(file);
    }
    const char* edgeNames[]={"timers-empty","timers-stale","timers-full","timers-finished-silent","new-timer-pending","new-timer-full","settings-muted","settings-mic-unavailable","settings-dim","settings-bright","connection-usb","connection-retrying"};
    for(unsigned scenario=0;scenario<sizeof(edgeNames)/sizeof(edgeNames[0]);++scenario) {
        Raster raster;ControlScene::Model m;m.page=ControlScene::Page::Timer;
        m.system.connected=true;m.system.powerKnown=true;m.timersReady=true;
        m.timerLabel="Old timer label";m.timerSeconds=600;
        switch(scenario) {
            case 0:break;
            case 1:m.timersReady=false;m.timerCount=3;m.timerResult="Timer started";break;
            case 2:m.timerCount=16;break;
            case 3:m.timerCount=1;m.timerFinished=true;m.timerSeconds=0;break;
            case 4:m.page=ControlScene::Page::NewTimer;m.timerBusy=true;break;
            case 5:m.page=ControlScene::Page::NewTimer;m.timerCount=16;break;
            case 6:m.page=ControlScene::Page::Settings;m.micMuted=true;m.system.state=State::Muted;break;
            case 7:m.page=ControlScene::Page::Settings;m.micReady=false;break;
            case 8:m.page=ControlScene::Page::Settings;m.brightness=ControlScene::brightnessMinimum;break;
            case 9:m.page=ControlScene::Page::Settings;m.brightness=ControlScene::brightnessMaximum;break;
            case 10:m.page=ControlScene::Page::Network;m.connection="USB connected";break;
            case 11:m.page=ControlScene::Page::Network;m.system.connected=false;m.connection="Waiting for your host";break;
        }
        ControlScene::render(raster,m);raster.checkBounds();
        switch(scenario) {
            case 0:assert(raster.has("No timers") && raster.has("Start one below") && !raster.has("Old timer label"));break;
            case 1:assert(raster.has("Unavailable") && raster.has("Waiting for the timer service") && !raster.has("Timer started") && !raster.has("Old timer label"));break;
            case 2:assert(raster.has("16-timer limit reached"));break;
            case 3:assert(raster.has("Time's up") && raster.has("SOUND OFF / TOUCH TO ADJUST"));break;
            case 4:assert(raster.has("STARTING TIMER") && raster.has("Waiting for confirmation") && raster.has("Starting..."));break;
            case 5:assert(raster.has("Dismiss a timer to make room") && raster.has("Limit reached"));break;
            case 6:assert(raster.has("Software mute / capture off") && raster.has("Unmute microphone"));break;
            case 7:assert(raster.has("Microphone unavailable"));break;
            case 10:assert(raster.has("USB / local host") && raster.has("USB connected"));break;
            case 11:assert(raster.has("Host disconnected") && !raster.has("USB / local host"));break;
        }
        char file[1024];snprintf(file,sizeof(file),"%s/%s.ppm",directory,edgeNames[scenario]);raster.save(file);
    }
    // A missing target in a reachable thermostat is not a disconnected service.
    const char* thermostatMissing[]={"thermostat-off-no-target","thermostat-auto-no-target","thermostat-no-data"};
    for(int scenario=0;scenario<3;++scenario) {
        Raster raster;ControlScene::Model m;m.page=ControlScene::Page::Thermostat;
        m.system.connected=true;m.system.powerKnown=true;m.temperatureReady=false;
        m.modesReady=scenario<2;m.mode=scenario==0?"off":"auto";m.modes=15;
        ControlScene::render(raster,m);raster.checkBounds();
        if(scenario==0)assert(raster.has("Off") && raster.has("No target temperature while off") && !raster.has("Unavailable"));
        if(scenario==1)assert(raster.has("No target") && raster.has("Target not reported / auto") && !raster.has("Unavailable"));
        if(scenario==2)assert(raster.has("Unavailable") && raster.has("Waiting for thermostat data") && !raster.has("Off"));
        assert(!raster.has("Waiting for Home Assistant"));
        char file[1024];snprintf(file,sizeof(file),"%s/%s.ppm",directory,thermostatMissing[scenario]);raster.save(file);
    }
    // Battery absence, unknown measurements and charging must remain distinct.
    for(int scenario=0;scenario<4;++scenario) {
        Raster raster;Model m;m.connected=true;m.state=State::Ready;
        m.powerKnown=scenario>0;m.battery=scenario>1;m.charging=scenario>=2;m.percent=scenario==3?72:-1;
        Animation a;render(raster,m,0,a);raster.checkBounds();
        const char* expected[]={"POWER UNKNOWN","EXTERNAL POWER","BATTERY / CHARGING","72% / CHARGING"};
        assert(raster.has(expected[scenario]));assert(!raster.has("BATTERY / 0%"));
        char file[1024];snprintf(file,sizeof(file),"%s/power-%d.ppm",directory,scenario);raster.save(file);
    }
    for(int scenario=0;scenario<3;++scenario) {
        Raster raster;ControlScene::Model m;m.page=ControlScene::Page::Thermostat;
        m.system.connected=true;m.system.powerKnown=true;m.temperatureReady=m.modesReady=true;
        m.target=70;m.temperature=68;m.low=45;m.high=99;m.unit='F';m.mode="cool";m.modes=15;
        m.homePending=scenario==0;m.homeFailed=scenario>0;
        m.result=scenario==0?"Sending request...":scenario==1?"Request failed":"No confirmation. Check status";
        ControlScene::render(raster,m);assert(raster.clipped==0);
        char file[1024];snprintf(file,sizeof(file),"%s/thermostat-%s.ppm",directory,scenario==0?"pending":scenario==1?"failed":"unconfirmed");raster.save(file);
    }
    for(int scenario=0;scenario<3;++scenario) {
        Raster raster;ControlScene::Model m;m.page=ControlScene::Page::Lights;
        m.system.connected=true;m.system.powerKnown=true;m.system.volume=2;m.lightsFresh=true;
        if(scenario) {m.lightsConfigured=15;m.lightsReady=7;m.lightsOn=3;m.lightsMixed=2;}
        if(scenario==2) {m.homePending=true;m.result="Sending request...";}
        ControlScene::render(raster,m);raster.checkBounds();
        assert(raster.has(scenario==0?"Assign in web app":scenario==1?"Mixed / turn off":"Updating..."));
        const char* suffix[]={"unassigned","partial","pending"};char file[1024];
        snprintf(file,sizeof(file),"%s/lights-%s.ppm",directory,suffix[scenario]);raster.save(file);
    }
    for(unsigned page=1;page<=unsigned(ControlScene::Page::SpeakerPicker);++page)for(int online=0;online<2;++online) {
        Raster raster;ControlScene::Model m;m.page=ControlScene::Page(page);
        m.system.connected=online;m.system.powerKnown=true;
        m.temperatureReady=m.modesReady=m.soundReady=m.weatherReady=m.timersReady=m.musicConnected=online;
        m.temperature=68;m.target=70;m.low=45;m.high=99;m.unit='F';m.mode="cool";m.modes=15;
        m.soundState="paused";m.soundVolume=10;m.soundMuted=0;m.soundFeatures=16384|128|256|4|8;
        m.speakerListFresh=online;m.speakerCount=3;m.speakerReceived=7;m.speakerSelected=1;
        m.speakerChoices[0]="Bedroom speaker";m.speakerChoices[1]="Bose soundbar";m.speakerChoices[2]="Living room speaker";
        m.weather=69;m.weatherUnit='F';m.humidity=49;m.condition="Partly cloudy";
        m.lightsFresh=online;m.lightsReady=m.lightsConfigured=15;m.lightsOn=5;
        m.timerCount=1;m.timerSeconds=278;m.timerLabel="Five-minute timer";
        m.musicTitle="Crab Rave";m.musicArtist="Noisestorm";m.musicState="paused";
        m.wifi=online;m.connection=online?"Connected":"Waiting for your host";m.sdReady=true;m.sdMegabytes=29818;
        ControlScene::render(raster,m);assert(raster.clipped==0);
        if(m.page==ControlScene::Page::Home)assert(raster.has("Weather") && raster.has("Timers") && raster.has("Settings"));
        if(m.page==ControlScene::Page::SpeakerPicker && !online)assert(raster.has("Waiting for Home Assistant") && !raster.has("Loading..."));
        for(int y=0;y<466;++y)for(int x=0;x<466;++x)if(raster.pixels[y*466+x]!=backgroundColor(x,y))assert((x-233)*(x-233)+(y-233)*(y-233)<=232*232);
        char file[1024];snprintf(file,sizeof(file),"%s/%s%s.ppm",directory,ControlScene::name(m.page),online?"":"-offline");raster.save(file);
    }
    for(unsigned state=0;state<=unsigned(State::MicUnavailable);++state) {
        Raster raster;Model model;model.state=State(state);model.connected=state!=unsigned(State::Offline);
        model.powerKnown=true;model.peak=.62f;model.response="Your five-minute timer is running.";
        if(model.state==State::Notice)model.response="Didn't catch that. Try again.";
        Animation animation;
        render(raster,model,2.4f,animation);
        assert(raster.clipped==0);
        // Verify all lit pixels fit the actual circular glass, not just the square framebuffer.
        for(int y=0;y<466;++y)for(int x=0;x<466;++x)if(raster.pixels[y*466+x]!=backgroundColor(x,y))assert((x-233)*(x-233)+(y-233)*(y-233)<=232*232);
        char file[1024];snprintf(file,sizeof(file),"%s/%s.ppm",directory,name(model.state));raster.save(file);
    }
    Raster longReply;Model reply;reply.state=State::Reply;reply.response="This unusually long response must wrap and end in an ellipsis without crossing the orb or the touch navigation controls.";
    Animation animation;render(longReply,reply,1,animation);assert(longReply.clipped==0);
    char file[1024];snprintf(file,sizeof(file),"%s/long-reply.ppm",directory);longReply.save(file);
    for(int frame=0;frame<28;++frame) {
        Raster raster;Model m;m.state=State::Listening;m.connected=true;m.powerKnown=true;m.peak=.3f+.25f*sinf(frame*.4f);
        render(raster,m,frame*.1f,animation);snprintf(file,sizeof(file),"%s/motion-%02d.ppm",directory,frame);raster.save(file);
    }
    puts("PASS: state precedence, real-font raster fixtures, circular bounds, and response overflow");
}
