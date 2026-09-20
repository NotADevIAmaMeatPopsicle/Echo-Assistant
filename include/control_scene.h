#pragma once
#include "voice_scene.h"
#include "touch_targets.h"
#include "music_ui.h"

namespace ControlScene {
constexpr int brightnessMinimum=20,brightnessMaximum=255;
enum class Page { Voice, Home, Thermostat, ThermostatMode, Soundbar, SoundbarVolume, Weather, Music, Settings, Network, Timer, NewTimer, Lights, SpeakerPicker, Intercom, Screen, Calendar };
inline Page swipePage(Page page,bool left) {
    Page parent=page==Page::ThermostatMode?Page::Thermostat:page==Page::SoundbarVolume || page==Page::SpeakerPicker?Page::Soundbar:page==Page::Network || page==Page::Screen?Page::Settings:page==Page::NewTimer?Page::Timer:page;
    if(!left && parent!=page)return parent;
    const Page pages[]={Page::Voice,Page::Home,Page::Soundbar,Page::Thermostat,Page::Lights,Page::Music,Page::Weather,Page::Timer,Page::Intercom,Page::Settings};
    for(int i=0;i<10;++i)if(pages[i]==parent)return pages[(i+(left?1:9))%10];
    return Page::Home;
}
inline const char* physicalAction(Page page,bool upper) {
    if(page==Page::Soundbar || page==Page::SoundbarVolume || page==Page::SpeakerPicker)return upper?"sound_up":"sound_down";
    if(page==Page::Thermostat || page==Page::ThermostatMode)return upper?"temp_up":"temp_down";
    return upper?"mic_toggle":"";
}
struct Model {
    Page page=Page::Home;
    VoiceScene::Model system;
    bool temperatureReady=false,modesReady=false,soundReady=false,weatherReady=false,timersReady=false;
    float temperature=0,target=0,low=0,high=0,weather=0;
    char unit='-',weatherUnit='-';
    const char *mode="unknown",*soundState="unknown",*condition="",*result="";
    unsigned modes=0,soundFeatures=0;
    const char* speakerName="Bose soundbar";
    const char* speakerChoices[32]{};
    int speakerCount=0,speakerSelected=-1,speakerOffset=0;
    bool speakerListFresh=false;
    uint32_t speakerReceived=0,speakerAvailable=0;
    bool lightsFresh=false;
    unsigned lightsReady=0,lightsOn=0,lightsMixed=0,lightsConfigured=0;
    int soundVolume=-1,soundMuted=-1,humidity=-1;
    bool micMuted=false,micReady=true,wifi=false,sdReady=false,timerBusy=false,timerFinished=false,musicConnected=false;
    bool homePending=false,homeFailed=false;
    int brightness=120,timerCount=0,timerSeconds=0,timerMinutes=5;
    unsigned screenDim=120,screenOff=600;
    unsigned sdMegabytes=0;
    const char *connection="Connection unavailable",*timerLabel="",*timerResult="",*musicTitle="",*musicArtist="",*musicState="";
};
inline const char* name(Page p) {
    static const char* names[]={"voice","home","thermostat","thermostat-modes","bose","bose-volume","weather","music-controls","settings","connection","timers","new-timer","lights","speakers","intercom","screen","calendar"};
    return names[unsigned(p)];
}
template<class Surface> void fitted(Surface& g,const char* value,int cx,int y,unsigned size,uint16_t color,int width) {
    char s[160];snprintf(s,sizeof(s),"%s",value);
    size_t n=strlen(s);
    if(g.width(s,size)>width) {
        while(n && g.width(s,size)>width-g.width("...",size))s[--n]=0;
        if(n<156)strcat(s,"...");
    }
    g.text(s,cx,y,size,color);
}
template<class Surface> void centered(Surface& g,const char* s,int y,unsigned size=1,uint16_t color=VoiceScene::text) {
    fitted(g,s,233,y,size,color,330);
}
template<class Surface> void pill(Surface& g,int x,int y,int w,const char* s,uint16_t color,bool enabled=true,bool selected=false) {
    uint16_t base=VoiceScene::blend(0x0863,color,enabled?selected?38:15:5);
    g.roundRect(x,y,w,42,21,base,true);
    g.roundRect(x,y,w,42,21,VoiceScene::blend(base,color,enabled?selected?120:45:20),false);
    fitted(g,s,x+w/2,y+27,1,enabled?color:VoiceScene::dim,w-20);
}
template<class Surface> void navigation(Surface& g,const Model& m) {
    for(int j=0;j<3;++j) {
        int x=122+j*111;
        bool mic=j==1,selected=(j==0 && m.page==Page::Home)||(j==2 && m.page==Page::Music);
        bool active=mic && m.system.connected && !m.micMuted && m.micReady;
        uint16_t accent=j==2?VoiceScene::violet:m.micMuted && mic?VoiceScene::amber:VoiceScene::mint;
        g.circle(x,354,21,active?accent:VoiceScene::blend(0x0863,accent,selected?48:15));
        VoiceScene::icon(g,x,353,j,active?0x1126:mic?VoiceScene::dim:accent);
        if(mic && m.micMuted)g.line(x-10,343,x+10,363,VoiceScene::amber);
    }
}
template<class Surface> void pill(Surface& g,const TouchTargets::Rect& r,const char* s,uint16_t color,bool enabled=true,bool selected=false) {
    pill(g,r.x,r.y,r.w,s,color,enabled,selected);
}
template<class Surface> void render(Surface& g,const Model& m) {
    using namespace VoiceScene;
    g.background();header(g,m.system,m.homePending || m.timerBusy || m.micMuted?amber:mint,m.homePending?"UPDATING HOME":m.timerBusy?"STARTING TIMER":nullptr);
    const uint16_t resultColor=m.homePending || m.homeFailed?amber:mint;
    char value[160];
    const bool tf=m.temperatureReady,sf=m.soundReady;
    switch(m.page) {
        case Page::Home:
            centered(g,"Your home",120,2);
            for(int j=0;j<2;++j) {
                auto r=j?TouchTargets::homeThermostat:TouchTargets::homeBose;
                uint16_t color=j?mint:violet,base=VoiceScene::blend(0x0863,color,20);
                g.roundRect(r.x,r.y,r.w,r.h,20,base,true);
                g.roundRect(r.x,r.y,r.w,r.h,20,VoiceScene::blend(base,color,65),false);
                fitted(g,j?"Thermostat":m.speakerName,r.x+r.w/2,r.y+25,1,color,r.w-12);
                if(j) { if(tf)snprintf(value,sizeof(value),"%.0f %c",m.temperature,m.unit);else strcpy(value,"--"); }
                else { if(sf && m.soundVolume>=0)snprintf(value,sizeof(value),"%d%%",m.soundVolume);else strcpy(value,"--"); }
                fitted(g,value,r.x+r.w/2,r.y+62,2,text,r.w-18);
                if(j) { if(tf)snprintf(value,sizeof(value),"Set %.0f %c / %s",m.target,m.unit,m.mode);else snprintf(value,sizeof(value),"%s",m.modesReady?m.mode:"Unavailable"); }
                else snprintf(value,sizeof(value),"%s",sf?(m.soundMuted==1?"Sound muted":m.soundState):"Unavailable");
                fitted(g,value,r.x+r.w/2,r.y+83,0,dim,r.w-12);
            }
            pill(g,TouchTargets::homeLights,"Room lights",amber);
            for(int j=0;j<3;++j) {
                auto r=j==0?TouchTargets::homeWeather:j==1?TouchTargets::homeTimers:TouchTargets::homeSettings;
                g.roundRect(r.x,r.y,r.w,r.h,18,VoiceScene::blend(0x0863,dim,18),true);
                fitted(g,j==0?"Weather":j==1?"Timers":"Settings",r.x+r.w/2,r.y+23,0,dim,r.w-10);
            }
            break;
        case Page::Lights: {
            centered(g,"Room lights",121,2);
            const char* names[]={"Bedroom","Living room","Dining room","Patio"};
            for(int j=0;j<4;++j) {
                auto r=TouchTargets::roomLights[j];unsigned bit=1u<<j;
                bool ready=m.lightsFresh && (m.lightsReady&bit),on=ready && (m.lightsOn&bit);
                uint16_t color=ready?(on?amber:mint):dim,base=VoiceScene::blend(0x0863,color,on?35:14);
                g.roundRect(r.x,r.y,r.w,r.h,19,base,true);
                g.roundRect(r.x,r.y,r.w,r.h,19,VoiceScene::blend(base,color,ready?85:30),false);
                fitted(g,names[j],r.x+r.w/2,r.y+28,1,color,r.w-14);
                const char* state=!m.lightsFresh?"Host unavailable":!(m.lightsConfigured&bit)?"Assign in web app":!ready?"Unavailable":m.homePending?"Updating...":(m.lightsMixed&bit)?"Mixed / turn off":on?"On / turn off":"Off / turn on";
                fitted(g,state,r.x+r.w/2,r.y+53,0,color,r.w-12);
            }
            centered(g,m.result,324,0,resultColor);break;
        }
        case Page::Weather:
            centered(g,"Weather",132,2);
            if(m.weatherReady)snprintf(value,sizeof(value),"%.1f %c",m.weather,m.weatherUnit);else strcpy(value,"Unavailable");
            centered(g,value,192,m.weatherReady?3:2,m.weatherReady?mint:dim);
            centered(g,m.weatherReady?m.condition:"Waiting for Home Assistant",231,1,dim);
            if(m.weatherReady){if(m.humidity>=0)snprintf(value,sizeof(value),"Humidity  %d%%",m.humidity);else strcpy(value,"Humidity unavailable");centered(g,value,267,1,dim);}
            pill(g,125,287,216,"Back to Home",dim);break;
        case Page::Thermostat: {
            centered(g,"Thermostat",132,2);
            bool off=m.modesReady && strcmp(m.mode,"off")==0;
            if(tf)snprintf(value,sizeof(value),m.unit=='C'?"%.1f %c":"%.0f %c",m.target,m.unit);
            else if(off)strcpy(value,"Off");
            else strcpy(value,m.modesReady?"No target":"Unavailable");
            centered(g,value,182,tf||off?3:2,tf?mint:off?amber:dim);
            if(tf)snprintf(value,sizeof(value),"%.1f indoors / %s",m.temperature,m.mode);
            else if(off)strcpy(value,"No target temperature while off");
            else if(m.modesReady)snprintf(value,sizeof(value),"Target not reported / %s",m.mode);
            else strcpy(value,"Waiting for thermostat data");
            centered(g,value,210,1,dim);
            bool adjustable=tf && strcmp(m.mode,"heat_cool")!=0 && !m.homePending;
            pill(g,125,226,80,"-",mint,adjustable && m.target>m.low);pill(g,261,226,80,"+",mint,adjustable && m.target<m.high);
            pill(g,142,275,182,"Change mode",amber,m.modesReady && m.modes);centered(g,m.result,329,0,resultColor);break;
        }
        case Page::ThermostatMode: {
            centered(g,"Thermostat mode",112,2);
            const char* names[]={"off","heat","cool","auto","heat_cool","dry","fan_only"};
            const char* labels[]={"Off","Heat","Cool","Auto","Heat / cool","Dry","Fan only"};
            for(int i=0;i<7;++i){bool active=strcmp(m.mode,names[i])==0;
                pill(g,i%2?239:95,125+(i/2)*48,132,labels[i],active?amber:mint,m.modesReady && (m.modes&(1u<<i)) && !m.homePending,active);}
            pill(g,239,269,132,"Back",dim);centered(g,m.result,329,0,resultColor);break;
        }
        case Page::Soundbar: {
            pill(g,83,96,300,m.speakerName,violet);centered(g,"Tap name to choose / buttons adjust volume",151,0,dim);
            centered(g,sf?m.soundState:"Unavailable",184,2,sf?violet:dim);
            if(!sf)strcpy(value,"Waiting for Home Assistant");else if(m.soundMuted==1)strcpy(value,"Muted");else if(m.soundVolume>=0)snprintf(value,sizeof(value),"Volume %d%%",m.soundVolume);else strcpy(value,"Volume unavailable");
            centered(g,value,209,1,dim);
            bool playing=strcmp(m.soundState,"playing")==0,on=strcmp(m.soundState,"off")!=0;
            pill(g,95,220,128,playing?"Pause":"Play",violet,sf && (m.soundFeatures&(playing?1:16384)) && !m.homePending);
            pill(g,243,220,128,on?"Turn off":"Turn on",mint,sf && (m.soundFeatures&(on?256:128)) && !m.homePending);
            pill(g,132,273,202,"Volume / mute",violet,sf);centered(g,m.result,329,0,resultColor);break;
        }
        case Page::SoundbarVolume: {
            centered(g,m.speakerName,132,1);
            if(sf && m.soundVolume>=0)snprintf(value,sizeof(value),"%d%%",m.soundVolume);else strcpy(value,"Unavailable");
            centered(g,value,184,sf && m.soundVolume>=0?3:2,sf?violet:dim);
            bool adjustable=sf && m.soundVolume>=0 && (m.soundFeatures&4) && !m.homePending;
            pill(g,125,207,80,"-",violet,adjustable && m.soundVolume>0);pill(g,261,207,80,"+",violet,adjustable && m.soundVolume<100);
            pill(g,95,265,132,m.soundMuted==1?"Unmute":"Mute",amber,sf && m.soundMuted>=0 && (m.soundFeatures&8) && !m.homePending);pill(g,239,265,132,"Back",dim);
            centered(g,m.result,329,0,resultColor);break;
        }
        case Page::SpeakerPicker: {
            centered(g,"Choose speaker",123,2);
            for(int j=0;m.speakerListFresh && j<3;++j) {
                int i=m.speakerOffset+j;
                if(i>=m.speakerCount)break;
                bool received=m.speakerListFresh && (m.speakerReceived&(1u<<i));
                const char* name=received && m.speakerChoices[i]?m.speakerChoices[i]:"Loading...";
                bool selected=m.speakerSelected==i;
                uint16_t color=selected?mint:violet,base=VoiceScene::blend(0x0863,color,selected?38:15);
                int y=142+j*46;
                g.roundRect(83,y,300,42,21,base,true);g.roundRect(83,y,300,42,21,VoiceScene::blend(base,color,selected?120:45),false);
                fitted(g,name,233,y+20,1,received?color:dim,275);
                fitted(g,!received?"Waiting":selected?"Selected":(m.speakerAvailable&(1u<<i))?"Available":"Offline",233,y+35,0,dim,275);
            }
            if(!m.speakerListFresh || !m.speakerCount)centered(g,"Waiting for Home Assistant",202,1,dim);
            pill(g,90,282,83,"Prev",dim,m.speakerOffset>0);pill(g,181,282,104,"Back",dim);pill(g,293,282,83,"Next",dim,m.speakerOffset+3<m.speakerCount);
            centered(g,m.result,329,0,resultColor);break;
        }
        case Page::Settings:
            centered(g,"Your device",126,2);
            centered(g,!m.micReady?"Microphone unavailable":m.micMuted?"Software mute / capture off":"Software microphone control",146,0,!m.micReady || m.micMuted?amber:dim);
            pill(g,TouchTargets::microphone,m.micMuted?"Unmute microphone":"Mute microphone",m.micMuted?amber:mint);
            centered(g,"Brightness",222,1,dim);pill(g,TouchTargets::brightnessDown,"-",dim,m.brightness>brightnessMinimum);pill(g,TouchTargets::brightnessUp,"+",dim,m.brightness<brightnessMaximum);
            snprintf(value,sizeof(value),"%d%%",m.brightness*100/255);centered(g,value,263,1,dim);
            pill(g,90,280,91,"Screen",mint);pill(g,188,280,91,"Wi-Fi",mint);pill(g,286,280,91,"Calls",mint);break;
        case Page::Screen:
            centered(g,"Screen comfort",128,2);
            centered(g,"Tap a timer to change it",151,0,dim);
            if(m.screenDim)snprintf(value,sizeof(value),"Dim after %u min",m.screenDim/60);else strcpy(value,"Dimming off");
            pill(g,99,165,268,value,mint);
            if(m.screenOff)snprintf(value,sizeof(value),"Dark after %u min",m.screenOff/60);else strcpy(value,"Automatic dark off");
            pill(g,99,214,268,value,mint);
            centered(g,"Touch once to wake. Music stays on.",277,0,dim);
            pill(g,95,287,132,"Sleep now",mint);pill(g,239,287,132,"Back",dim);break;
        case Page::Network:
            centered(g,"Connection",132,2);centered(g,m.wifi?"Paired Wi-Fi":m.system.connected?"USB / local host":"Host disconnected",184,2,m.system.connected?mint:dim);centered(g,m.connection,225,1,dim);
            centered(g,"Use USB to pair with your host",269,1,dim);
            if(m.sdReady)snprintf(value,sizeof(value),"SD  %.1f GB",m.sdMegabytes/1024.0);else strcpy(value,"SD not detected");centered(g,value,309,1,dim);break;
        case Page::Timer:
            centered(g,"Your timers",132,2);
            if(!m.timersReady)strcpy(value,"Unavailable");else if(!m.timerCount)strcpy(value,"No timers");else if(m.timerFinished)strcpy(value,"Time's up");else snprintf(value,sizeof(value),"%02d:%02d",m.timerSeconds/60,m.timerSeconds%60);
            centered(g,value,190,m.timersReady && m.timerCount && !m.timerFinished?3:2,amber);
            centered(g,!m.timersReady?"Waiting for the timer service":m.timerResult[0]?m.timerResult:m.timerCount?m.timerLabel:"Start one below",223,1,dim);
            if(m.timerCount && m.timersReady){pill(g,100,239,128,"Dismiss",amber);snprintf(value,sizeof(value),m.timerCount>1?"Next (%d)":"Next",m.timerCount);pill(g,240,239,126,value,dim,m.timerCount>1);}
            pill(g,125,287,216,m.timersReady && m.timerCount>=16?"16-timer limit reached":"New timer",mint,m.timersReady && m.timerCount<16);break;
        case Page::NewTimer: {
            centered(g,"New timer",126,2);
            centered(g,!m.timersReady?"Timer service unavailable":m.timerCount>=16?"Dismiss a timer to make room":m.timerBusy?"Waiting for confirmation":"Choose a duration",147,0,!m.timersReady || m.timerCount>=16?amber:dim);
            snprintf(value,sizeof(value),"%d %s",m.timerMinutes,m.timerMinutes==1?"minute":"minutes");centered(g,value,181,2,amber);
            pill(g,95,190,132,"-",amber,!m.timerBusy && m.timerMinutes>1);pill(g,239,190,132,"+",amber,!m.timerBusy && m.timerMinutes<120);
            pill(g,95,239,84,"5 min",dim,!m.timerBusy,m.timerMinutes==5);pill(g,191,239,84,"15 min",dim,!m.timerBusy,m.timerMinutes==15);pill(g,287,239,84,"30 min",dim,!m.timerBusy,m.timerMinutes==30);
            pill(g,95,287,132,m.timerBusy?"Starting...":!m.timersReady?"Unavailable":m.timerCount>=16?"Limit reached":"Start",mint,m.timersReady && !m.timerBusy && m.timerCount<16);pill(g,239,287,132,"Back",dim);break;
        }
        case Page::Music: {
            auto state=MusicUi::resolve(m.musicConnected,m.musicState);
            bool track=MusicUi::canSkip(state);
            centered(g,"Your music",132,2);
            centered(g,track && m.musicTitle[0]?m.musicTitle:"Spotify Connect",204,2,violet);
            centered(g,track && m.musicArtist[0]?m.musicArtist:MusicUi::subtitle(state),235,1,dim);
            centered(g,MusicUi::detail(state,m.system.volume),270,1,dim);
            pill(g,TouchTargets::musicPrevious,"Prev",violet,MusicUi::canSkip(state));
            pill(g,TouchTargets::musicToggle,state==MusicUi::State::Playing?"Pause":"Play",violet,MusicUi::canToggle(state));
            pill(g,TouchTargets::musicNext,"Next",violet,MusicUi::canSkip(state));break;
        }
        default:break;
    }
    navigation(g,m);volumeControl(g,m.system);
}
}
