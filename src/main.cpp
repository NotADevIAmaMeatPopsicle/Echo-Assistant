#include <Arduino.h>
#include <Arduino_GFX_Library.h>
#include <Wire.h>
#include <SD_MMC.h>
#include <Preferences.h>
#include <math.h>
#include <esp_log.h>
#include "touch/TouchDrvCST92xx.h"
#include "board.h"
#include "host_transport.h"
#include "audio_engine.h"
#include "fonts/FreeSans18pt7b.h"
#include "fonts/FreeSans9pt7b.h"
#include "voice_scene.h"
#include "control_scene.h"
#include "home_action_state.h"
#include "ui_type.h"
#include "mute_button.h"
#include "touch_gesture.h"
#include "screen_idle.h"
#include "intercom_state.h"
#include "intercom_scene.h"

// CO5300 setup from YouAndEye's accepted AMOLED surface. See THIRD_PARTY_NOTICES.md.
static Arduino_DataBus* bus=new Arduino_ESP32QSPI(Board::lcdCs,Board::lcdClock,Board::lcdD0,Board::lcdD1,Board::lcdD2,Board::lcdD3);
static Arduino_CO5300* panel=new Arduino_CO5300(bus,Board::lcdReset,0,466,466,7,0,0,0);
static Arduino_Canvas* canvas=new Arduino_Canvas(466,466,panel);
static TouchDrvCST92xx touch;
static bool displayReady=false,touchReady=false,sdReady=false;
static bool pmuReady=false,batteryPresent=false,powerKnown=false,charging=false;
static int batteryPercent=-1,volumeShown=1;
static uint32_t sdMegabytes=0,lastFrame=0,lastPower=0,lastReport=0;
static String serialLine,usbPairLine;
static unsigned transportEpoch=0;
static bool discardLine=false,discardUsbLine=false;
static bool wakeArmed=false,wakeMuted=false;
static MuteButton muteButton;
static MuteButton lowerButton;
static bool muteButtonReady=false;
static int muteButtonLevel=-1, muteButtonPolarity=0;
static uint32_t muteButtonAt=0,muteButtonToggles=0,muteButtonErrors=0;
static uint32_t buttonRetryAt=0,upperPresses=0,lowerPresses=0;
static int lowerLevel=0;
static uint32_t wakeHeartbeat=0,listenUntil=0,micSequence=0,usbDrops=0;
static bool cuePending=false;
static uint32_t cueRequest=0,cueBefore=0;
static String voiceResult;
static uint32_t voiceResultAt=0,renderLastUs=0,renderMaxUs=0,renderFrames=0;
static uint32_t composeLastUs=0,flushLastUs=0;
static bool voiceNotice=false;
using Page=ControlScene::Page;
static Page page=Page::Voice;
static Page touchPage=Page::Voice;
static TouchGesture touchGesture;
static Page upperPressPage=Page::Voice,lowerPressPage=Page::Voice;
static Preferences preferences;
static int brightness=120;
static ScreenIdle screenIdle;
static int appliedBrightness=-1;
static bool discardWakeTouch=false;
static uint32_t wakeReleaseAt=0;
static void applyScreenBrightness() {
    int value=screenIdle.level==ScreenIdle::Level::Off?0:screenIdle.level==ScreenIdle::Level::Dim?max(1,brightness/5):brightness;
    if(value!=appliedBrightness) {panel->setBrightness(value);appliedBrightness=value;lastFrame=millis()-100;}
}
static bool wakeScreen() {bool off=screenIdle.activity(millis());applyScreenBrightness();return off;}
static bool thinking=false,tempReady=false,soundReady=false;
static float tempCurrent=0,tempTarget=0,tempMin=0,tempMax=0;
static char tempUnit='-',tempMode[16]="unknown",soundState[16]="unknown";
static int soundVolume=-1,soundMuted=-1;
static unsigned soundFeatures=0;
static String speakerName="Speaker",speakerChoices[32];
static char speakerBinding[65]="",speakerRevision[65]="";
static int speakerCount=0,speakerSelected=-1,speakerOffset=0;
static uint32_t speakerListAt=0,speakerReceived=0,speakerAvailable=0;
static bool weatherReady=false;
static float weatherTemperature=0;
static char weatherUnit='-';
static int weatherHumidity=-1;
static String weatherCondition;
static uint32_t weatherAt=0;
static unsigned tempModes=0;
static bool modesReady=false;
static uint32_t modesAt=0;
static const char* modeNames[]={"off","heat","cool","auto","heat_cool","dry","fan_only"};
static const char* modeLabels[]={"Off","Heat","Cool","Auto","Heat / cool","Dry","Fan only"};
static uint32_t homeAt=0,soundAt=0,preferenceAt=0;
static int savedVolume=1;
static String homeResult;
static HomeActionState homeActionState;
static uint32_t homeLegacyAt=0;
static bool remoteIsMusic=false,remoteIsAlarm=false;
static bool remoteIsIntercom=false,intercomCapture=false;
static IntercomState intercom;
static String musicState="not_configured",musicTitle,musicArtist;
static uint32_t musicAt=0;
static int timerCount=0,timerSeconds=0;
static bool timerFinished=false;
static bool timerAvailable=false;
static uint32_t timerAt=0;
static int timerMinutes=5;
static bool timerBusy=false;
static uint32_t timerRequestAt=0;
static uint32_t timerResultAt=0;
static unsigned lightsReady=0,lightsOn=0,lightsMixed=0,lightsConfigured=0;
static uint32_t lightsAt=0;
static char lightsBinding[65]="";
static String timerLabel,timerResult;
static uint32_t audioSession=0,lastAudioReport=0;
static uint8_t incoming[527];
static size_t incomingSize=0;
static uint32_t incomingAt=0;
static constexpr uint16_t INK=0x0000,TEXT=0xEFBE,DIM=0x8CF1,MINT=0x8FF8,LILAC=0xBCDF,AMBER=0xFDD0,CARD=0x10E3;
static uint16_t* voiceBackground=nullptr;
static VoiceScene::OrbCache voiceOrb;
static void receiveHost();
static void sendMic();
static void pollMuteButton();
static void syncIntercomCapture() {
    bool capture=intercom.capture(wakeMuted) && wakeArmed;
    if(capture==intercomCapture)return;
    intercomCapture=capture;
    audioCommand(capture?AudioCommand::StreamOn:AudioCommand::StreamOff);
    if(capture) {audioCommand(AudioCommand::DuplexOn);Host.printf("EVENT intercom_capture=%s\n",intercom.id);}
}
static void endIntercom(bool disable=false) {
    if(intercom.busy())Host.printf("EVENT intercom_action=hangup id=%s\n",intercom.id);
    if(remoteIsIntercom || intercom.busy()){audioRemoteStop();audioCommand(AudioCommand::Stop);}
    intercom.clear(disable);syncIntercomCapture();remoteIsIntercom=false;
    if(wakeArmed && !wakeMuted)audioCommand(AudioCommand::StreamOn);
    if(disable)Host.println("EVENT intercom_enabled=0");
}
static void muteIntercom() {
    intercom.localMuted=!intercom.localMuted;intercom.muted=intercom.localMuted;
    Host.printf("EVENT intercom_action=%s id=%s\n",intercom.muted?"mute":"unmute",intercom.id);
    syncIntercomCapture();
}

struct VoiceSurface {
    void pixel(int x,int y,uint16_t c) { canvas->drawPixel(x,y,c); }
    void alphaPixel(int x,int y,uint16_t c,unsigned alpha) {
        if(x<0 || y<0 || x>=466 || y>=466)return;
        uint16_t* p=canvas->getFramebuffer()+y*466+x;*p=VoiceScene::blend(*p,c,alpha);
    }
    const VoiceScene::OrbCache& orb() { return voiceOrb; }
    void background() {
        if(voiceBackground)memcpy(canvas->getFramebuffer(),voiceBackground,466*466*sizeof(uint16_t));
        else canvas->fillScreen(0x0022);
    }
    void line(int x,int y,int x2,int y2,uint16_t c) { canvas->drawLine(x,y,x2,y2,c); }
    void circle(int x,int y,int r,uint16_t c) { canvas->fillCircle(x,y,r,c); }
    void roundRect(int x,int y,int w,int h,int r,uint16_t c,bool fill) {
        if(fill)canvas->fillRoundRect(x,y,w,h,r,c);else canvas->drawRoundRect(x,y,w,h,r,c);
    }
    int width(const char* s,unsigned size) { return UiType::width(s,size); }
    void text(const char* s,int cx,int baseline,unsigned size,uint16_t c) {
        UiType::draw(*this,s,cx,baseline,size,c);
    }
};
static VoiceScene::Animation voiceAnimation;
static VoiceScene::Input voiceInput(const AudioStatus& audio) {
    VoiceScene::Input i;
    i.connected=wakeArmed;i.muted=wakeMuted;i.micReady=audio.micReady;
    i.listening=listenUntil && int32_t(listenUntil-millis())>0;
    i.thinking=thinking;i.mode=unsigned(audio.mode);i.music=remoteIsMusic;i.alarm=remoteIsAlarm;
    i.reply=voiceResult.length() && millis()-voiceResultAt<10000;
    i.notice=i.reply && voiceNotice;
    return i;
}
static void finishFrame(uint32_t started) {
    uint32_t composed=micros();composeLastUs=composed-started;
    // Composition and the full QSPI transfer can together outlast the initial
    // audio queue. Service both directions between them and after the transfer;
    // drawing itself remains on this task and the completed canvas is unchanged.
    pollMuteButton(); sendMic(); receiveHost();
    uint32_t flushing=micros();canvas->flush();flushLastUs=micros()-flushing;
    pollMuteButton(); sendMic(); receiveHost();renderLastUs=micros()-started;
    renderMaxUs=max(renderMaxUs,renderLastUs);++renderFrames;
}

static int readRegister(uint8_t addr,uint8_t reg) {
    Wire.beginTransmission(addr); Wire.write(reg);
    if (Wire.endTransmission(false)!=0 || Wire.requestFrom(int(addr),1)!=1) return -1;
    return Wire.read();
}
static void updatePower() {
    int s0=readRegister(0x34,0),s1=readRegister(0x34,1);
    powerKnown=pmuReady && s0>=0 && s1>=0;
    batteryPresent=powerKnown && (s0&8);
    charging=batteryPresent && (s1>>5)==1;
    int percent=batteryPresent?readRegister(0x34,0xA4):-1;
    batteryPercent=percent>=0 && percent<=100?percent:-1;
    // Read-only PMIC integration: leave charge voltage/current and power rails unchanged.
}
static bool homeFresh() { return wakeArmed && tempReady && millis()-homeAt<20000; }
static bool soundFresh() { return wakeArmed && soundReady && millis()-soundAt<20000; }
static bool modesFresh() { return wakeArmed && modesReady && millis()-modesAt<20000; }
static bool timersFresh() { return wakeArmed && timerAvailable && millis()-timerAt<5000; }
static bool weatherFresh() { return wakeArmed && weatherReady && millis()-weatherAt<20000; }
static void homeAction(const char* action) {
    if(strncmp(action,"sound_",6)==0 && (strlen(speakerBinding)!=64 || strspn(speakerBinding,"0")==64))return;
    if(!homeActionState.begin(millis()))return;
    homeResult="";
    if(strncmp(action,"sound_",6)==0)Host.printf("EVENT speaker_action=%s request=%lu binding=%s\n",action+6,(unsigned long)homeActionState.request,speakerBinding);
    else Host.printf("EVENT home_action=%s request=%lu\n",action,(unsigned long)homeActionState.request);
}
static void draw() {
    if(screenIdle.level==ScreenIdle::Level::Off)return;
    uint32_t started=micros();
    auto audio=audioStatus(); volumeShown=audio.volume;
    if(page==Page::Intercom) {
        using namespace ControlScene;
        VoiceSurface g;g.background();VoiceScene::Model system;system.connected=wakeArmed;system.micMuted=wakeMuted;system.volume=audio.volume;
        system.powerKnown=powerKnown;system.battery=batteryPresent;system.percent=batteryPercent;system.charging=charging;
        IntercomScene::render(g,intercom,system);finishFrame(started);return;
    }
    if(page==Page::Voice) {
        VoiceScene::Model m;
        m.state=VoiceScene::resolve(voiceInput(audio));m.connected=wakeArmed;
        m.micMuted=wakeMuted;
        m.powerKnown=powerKnown;m.battery=batteryPresent;m.percent=batteryPercent;m.charging=charging;
        m.volume=audio.volume;m.peak=min(1.0f,audio.peak/12000.0f);m.response=voiceResult.c_str();
        VoiceSurface surface;VoiceScene::render(surface,m,millis()/1000.0f,voiceAnimation);
        finishFrame(started);return;
    }
    ControlScene::Model m;
    m.page=page;m.system.state=VoiceScene::resolve(voiceInput(audio));m.system.connected=wakeArmed;
    m.system.micMuted=wakeMuted;
    m.system.powerKnown=powerKnown;m.system.battery=batteryPresent;m.system.percent=batteryPercent;m.system.charging=charging;m.system.volume=audio.volume;
    m.temperatureReady=homeFresh();m.modesReady=modesFresh();m.soundReady=soundFresh();m.weatherReady=weatherFresh();m.timersReady=timersFresh();
    m.temperature=tempCurrent;m.target=tempTarget;m.low=tempMin;m.high=tempMax;m.unit=tempUnit;m.mode=tempMode;m.modes=tempModes;
    m.soundState=soundState;m.soundVolume=soundVolume;m.soundMuted=soundMuted;m.soundFeatures=soundFeatures;
    m.speakerName=speakerName.c_str();m.speakerCount=speakerCount;m.speakerSelected=speakerSelected;m.speakerOffset=speakerOffset;
    m.speakerListFresh=wakeArmed && speakerListAt && millis()-speakerListAt<20000;
    m.speakerReceived=speakerReceived;m.speakerAvailable=speakerAvailable;
    for(int i=0;i<32;++i)m.speakerChoices[i]=speakerChoices[i].c_str();
    m.homePending=homeActionState.pending();m.homeFailed=homeActionState.failed();
    m.result=homeActionState.phase!=HomeActionState::Phase::Idle?homeActionState.message():millis()-homeLegacyAt<8000?homeResult.c_str():"";
    m.weather=weatherTemperature;m.weatherUnit=weatherUnit;m.humidity=weatherHumidity;m.condition=weatherCondition.c_str();
    m.micMuted=wakeMuted;m.micReady=audio.micReady;m.brightness=brightness;m.wifi=networkConnected();m.sdReady=sdReady;m.sdMegabytes=sdMegabytes;
    m.screenDim=screenIdle.dimSeconds;m.screenOff=screenIdle.offSeconds;
    m.connection=wakeArmed?(networkConnected()?"Connected":"USB connected"):strcmp(networkState(),"not_paired")==0?"Wi-Fi not paired":strcmp(networkState(),"connecting_wifi")==0?"Connecting to Wi-Fi":strcmp(networkState(),"waiting_host")==0?"Waiting for your host":networkConnected()?"Waiting for your host":"Connection unavailable";
    m.timerBusy=timerBusy;m.timerCount=timerCount;m.timerFinished=timerFinished;m.timerSeconds=max(0,timerSeconds-int((millis()-timerAt)/1000));m.timerMinutes=timerMinutes;
    m.timerResult=millis()-timerResultAt<8000?timerResult.c_str():"";m.timerLabel=timerLabel.c_str();
    m.musicConnected=wakeArmed && millis()-musicAt<5000;m.musicTitle=musicTitle.c_str();m.musicArtist=musicArtist.c_str();m.musicState=musicState.c_str();
    m.lightsFresh=wakeArmed && lightsAt && millis()-lightsAt<20000;
    m.lightsReady=lightsReady;m.lightsOn=lightsOn;m.lightsMixed=lightsMixed;m.lightsConfigured=lightsConfigured;
    VoiceSurface surface;ControlScene::render(surface,m);finishFrame(started);

}
static void report(unsigned query=0) {
    auto s=audioStatus();
    auto net=networkStats();
    auto usb=usbStats();
    Host.printf("STATUS product=round-voice version=0.15.0 protocol=1 duplex=1 intercom=1 cue_ready=1 role=local-voice display=%d touch=%d psram=%u sd=%d sd_mb=%lu pmu=%d battery=%d percent=%d charging=%d mic=%d speaker=%d mode=%u samples=%lu peak=%u volume=%d audio_errors=%lu heap=%u wake=%d muted=%d stream=%d stream_drops=%lu usb_drops=%lu transport=%s network=%s rssi=%d query=%u uptime_ms=%lu heartbeat_ms=%lu\n",
        displayReady,touchReady,ESP.getPsramSize(),sdReady,(unsigned long)sdMegabytes,pmuReady,
        batteryPresent,batteryPercent,charging,s.micReady,s.speakerReady,unsigned(s.mode),
        (unsigned long)s.recordedSamples,s.peak,s.volume,(unsigned long)s.errors,ESP.getFreeHeap(),
        wakeArmed,wakeMuted,s.streaming,(unsigned long)s.streamDrops,(unsigned long)usbDrops,networkConnected()?"wifi":"usb",networkState(),networkRssi(),query,(unsigned long)millis(),(unsigned long)(millis()-wakeHeartbeat));
    Host.printf("BUTTON ready=%d level=%d toggles=%lu errors=%lu lower_level=%d upper_presses=%lu lower_presses=%lu\n",muteButtonReady,muteButtonLevel,(unsigned long)muteButtonToggles,(unsigned long)muteButtonErrors,lowerLevel,(unsigned long)upperPresses,(unsigned long)lowerPresses);
    Host.printf("NETWORK disconnects=%lu reason=%u tx_full=%lu write_errors=%lu max_write_ms=%lu tx_high=%u rx_high=%u\n",
        (unsigned long)net.disconnects,net.reason,(unsigned long)net.txFull,(unsigned long)net.writeErrors,
        (unsigned long)net.maxWriteMs,unsigned(net.txHigh),unsigned(net.rxHigh));
    Host.printf("USB skipped=%lu partial=%lu max_write_ms=%lu\n",(unsigned long)usb.skipped,(unsigned long)usb.partial,(unsigned long)usb.maxWriteMs);
    Host.printf("UI page=%u thermostat=%d soundbar=%d weather=%d timers=%d timer_count=%d brightness=%d home_pending=%d\n",
        unsigned(page),homeFresh() || modesFresh(),soundFresh(),weatherFresh(),timersFresh(),timerCount,brightness,homeActionState.pending());
    Host.printf("RENDER state=%s last_us=%lu max_us=%lu frames=%lu compose_us=%lu flush_us=%lu cache_pixels=%u background=%d\n",VoiceScene::name(VoiceScene::resolve(voiceInput(s))),
        (unsigned long)renderLastUs,(unsigned long)renderMaxUs,(unsigned long)renderFrames,(unsigned long)composeLastUs,(unsigned long)flushLastUs,voiceOrb.count,voiceBackground!=nullptr);
}
static void setWakeMuted(bool muted) {
    if(muted && intercom.busy())endIntercom();
    wakeMuted=muted; cuePending=false; listenUntil=0; voiceResult=""; thinking=false;
    if (!((remoteIsMusic||remoteIsAlarm) && audioRemoteStatus().active)) { audioRemoteStop(); audioCommand(AudioCommand::Stop); }
    audioCommand(!muted && wakeArmed?AudioCommand::StreamOn:AudioCommand::StreamOff);
    preferences.putBool("mic_muted",muted);
    Host.printf("EVENT mic_muted=%d\n",muted);
}
static bool prepareMuteButton() {
    int config=readRegister(Board::keyExpander,3);
    int polarity=readRegister(Board::keyExpander,2);
    if(config<0 || polarity<0)return false;
    // Set only EXIO4 to input, preserving every other pin and all PMIC settings.
    if(!(config&Board::powerKeyMask)) {
        Wire.beginTransmission(Board::keyExpander); Wire.write(3);
        Wire.write(uint8_t(config|Board::powerKeyMask));
        if(Wire.endTransmission()!=0)return false;
        config=readRegister(Board::keyExpander,3);
        if(config<0 || !(config&Board::powerKeyMask))return false;
    }
    muteButtonPolarity=polarity;
    return true;
}
static void pollMuteButton() {
    uint32_t now=millis();
    if(now-muteButtonAt<10)return;
    muteButtonAt=now;
    auto press=[&](bool upper,Page startPage) {
        if(upper)++upperPresses;else ++lowerPresses;
        // Microphone mute remains immediately accessible on Home/Voice.
        if(wakeScreen() && !(upper && (startPage==Page::Home || startPage==Page::Voice)))return;
        if(page!=startPage)return;
        if(intercom.busy()) {if(upper && intercom.phase==IntercomState::Active)muteIntercom();else if(!upper)endIntercom();return;}
        const char* action=ControlScene::physicalAction(page,upper);
        if(strncmp(action,"sound_",6)==0) {
            if(soundFresh() && (soundFeatures&4) && soundVolume>=0 && (upper?soundVolume<100:soundVolume>0))homeAction(action);
        } else if(strncmp(action,"temp_",5)==0) {
            if(homeFresh() && strcmp(tempMode,"heat_cool")!=0 && (upper?tempTarget<tempMax:tempTarget>tempMin))homeAction(action);
        } else if(strcmp(action,"mic_toggle")==0) {++muteButtonToggles;setWakeMuted(!wakeMuted);}
        lastFrame=now-100;
    };
    int lower=digitalRead(Board::bootButton)==LOW?1:0;
    if(lower && !lowerLevel)lowerPressPage=page;
    lowerLevel=lower;
    if(lowerButton.update(lower,now))press(false,lowerPressPage);
    if(!muteButtonReady && now-buttonRetryAt>=1000) {buttonRetryAt=now;muteButtonReady=prepareMuteButton();}
    int input=muteButtonReady?readRegister(Board::keyExpander,0):-1;
    int level=input<0?-1:((input^muteButtonPolarity)&Board::powerKeyMask?1:0);
    if(level==1 && muteButtonLevel!=1)upperPressPage=page;
    muteButtonLevel=level;
    if(input<0 && muteButtonReady) { muteButtonReady=false; ++muteButtonErrors; }
    if(muteButton.update(muteButtonLevel,now)) {
        press(true,upperPressPage);
    }
}
static void handleCommand(const String& command) {
    if (!networkConnected() && networkCommand(command)) return;
    if(command=="CALL_RESET") {endIntercom(true);return;}
    if(command.startsWith("CALL_LIST ")) {
        char binding[17],notice[33];unsigned count;int enabled,ready;
        if(sscanf(command.c_str()+10,"%16s %u %d %d %32[^\n]",binding,&count,&enabled,&ready,notice)==5 && strlen(binding)==16 && strspn(binding,"0123456789abcdef")==16 && count<=32) {
            if(strcmp(binding,intercom.binding)!=0){intercom.received=intercom.available=0;intercom.offset=0;}
            strcpy(intercom.binding,binding);strcpy(intercom.notice,notice);intercom.count=count;intercom.ready=enabled && ready;
        }
        return;
    }
    if(command.startsWith("CALL_ROOM ")) {
        char binding[17],name[33];unsigned index;int ready;
        if(sscanf(command.c_str()+10,"%16s %u %d %32[^\n]",binding,&index,&ready,name)==4 && strcmp(binding,intercom.binding)==0 && index<intercom.count) {
            strcpy(intercom.rooms[index],name);intercom.received|=1u<<index;
            if(ready)intercom.available|=1u<<index;else intercom.available&=~(1u<<index);
        }
        return;
    }
    if(command.startsWith("CALL_STATE ")) {
        char id[33],phase[12],room[33];int muted;unsigned long seconds;
        if(sscanf(command.c_str()+11,"%32s %11s %d %lu %32[^\n]",id,phase,&muted,&seconds,room)!=5)return;
        if(strcmp(phase,"idle")==0) {
            bool wasBusy=intercom.busy();intercom.state("",IntercomState::Idle,true,millis());syncIntercomCapture();
            if(wasBusy && !intercom.busy()){audioRemoteStop();remoteIsIntercom=false;if(wakeArmed && !wakeMuted)audioCommand(AudioCommand::StreamOn);}
        } else if(intercom.enabled && wakeArmed && !wakeMuted && IntercomState::identifier(id)) {
            auto next=strcmp(phase,"incoming")==0?IntercomState::Incoming:strcmp(phase,"outgoing")==0?IntercomState::Outgoing:IntercomState::Active;
            if(strcmp(phase,"active")!=0 && next==IntercomState::Active)return;
            if(!intercom.busy())audioCommand(AudioCommand::StreamOff);
            intercom.state(id,next,muted!=0,millis());intercom.seconds=min(seconds,900ul);strcpy(intercom.room,room);
            page=Page::Intercom;cuePending=false;listenUntil=0;thinking=false;syncIntercomCapture();
        }
        return;
    }
    if (command=="STATUS") report();
    else if (command.startsWith("STATUS ")) report(strtoul(command.c_str()+7,nullptr,10));
    else if (command=="VOICE_ARM") { wakeArmed=true; wakeHeartbeat=millis(); if (!wakeMuted && !intercom.busy()) audioCommand(AudioCommand::StreamOn); report(); }
    else if (command=="VOICE_PING") { wakeHeartbeat=millis(); }
    else if (command=="VOICE_OFF") { wakeArmed=false; endIntercom(true); cuePending=false; thinking=false; listenUntil=0; audioRemoteStop(); audioCommand(AudioCommand::StreamOff); }
    else if (command=="MUTE") setWakeMuted(true);
    else if (command=="UNMUTE" && wakeArmed) setWakeMuted(false);
    else if(command.startsWith("HOME_SELECTED ")) {
        char binding[65],name[49],extra;
        if(sscanf(command.c_str()+14,"%64s %48s %c",binding,name,&extra)==2 && strlen(binding)==64 && strspn(binding,"0123456789abcdef")==64) {
            strcpy(speakerBinding,binding);speakerName=name;speakerName.replace('_',' ');
        }
    }
    else if(command.startsWith("HOME_SPEAKERS ")) {
        char revision[65],extra;int count,selected;
        if(sscanf(command.c_str()+14,"%64s %d %d %c",revision,&count,&selected,&extra)==3 && strlen(revision)==64 && strspn(revision,"0123456789abcdef")==64 && count>=0 && count<=32 && selected>=-1 && selected<count) {
            strcpy(speakerRevision,revision);speakerCount=count;speakerSelected=selected;speakerReceived=speakerAvailable=0;
            speakerOffset=min(speakerOffset,max(0,((count-1)/3)*3));speakerListAt=strspn(revision,"0")==64?0:millis();
        }
    }
    else if(command.startsWith("HOME_SPEAKER ")) {
        char revision[65],name[49],extra;int index,available;
        if(sscanf(command.c_str()+13,"%64s %d %d %48s %c",revision,&index,&available,name,&extra)==4 && strcmp(revision,speakerRevision)==0 && index>=0 && index<speakerCount && (available==0 || available==1)) {
            speakerChoices[index]=name;speakerChoices[index].replace('_',' ');speakerReceived|=1u<<index;
            if(available)speakerAvailable|=1u<<index;
        }
    }
    else if (command.startsWith("HOME_LIGHTS ")) {
        unsigned ready,on,mixed,configured;char binding[65],extra;
        if(sscanf(command.c_str()+12,"%u %u %u %u %64s %c",&ready,&on,&mixed,&configured,binding,&extra)==5 &&
           ready<=15 && on<=15 && mixed<=15 && configured<=15 && strlen(binding)==64 && strspn(binding,"0123456789abcdef")==64) {
            lightsReady=ready;lightsOn=on;lightsMixed=mixed;lightsConfigured=configured;
            strcpy(lightsBinding,binding);lightsAt=strspn(binding,"0")==64?0:millis();
        }
    }
    else if (command.startsWith("HOME_TEMP ")) {
        int ready; float current,target,low,high; char unit,mode[16];
        if (sscanf(command.c_str()+10,"%d %f %f %c %15s %f %f",&ready,&current,&target,&unit,mode,&low,&high)==7) {
            tempReady=ready==1 && isfinite(current) && isfinite(target) && isfinite(low) && isfinite(high) && low<=high && (unit=='F'||unit=='C');
            tempCurrent=current; tempTarget=target; tempMin=low; tempMax=high; tempUnit=unit;
            strncpy(tempMode,mode,sizeof(tempMode)); homeAt=millis();
        }
    }
    else if (command.startsWith("HOME_MODES ")) {
        int ready; unsigned modes;
        if (sscanf(command.c_str()+11,"%d %u",&ready,&modes)==2) {
            modesReady=ready==1; tempModes=modes&127; modesAt=millis();
        }
    }
    else if (command.startsWith("HOME_SOUND ")) {
        int ready,volume,muted=-1; unsigned features; char state[16];
        if (sscanf(command.c_str()+11,"%d %15s %d %u %d",&ready,state,&volume,&features,&muted)>=4) {
            soundReady=ready==1; soundVolume=volume>=0 && volume<=100?volume:-1; soundFeatures=features;
            soundMuted=muted==0 || muted==1?muted:-1;
            strncpy(soundState,state,sizeof(soundState)); soundAt=millis();
        }
    }
    else if (command.startsWith("HOME_ACK ")) {
        unsigned long request;char status[16];
        if(sscanf(command.c_str()+9,"%lu %15s",&request,status)==2)homeActionState.acknowledge(request,status,millis());
    }
    else if (command.startsWith("HOME_RESULT ")) {
        if(!homeActionState.pending()) { homeResult=command.substring(12,40);homeLegacyAt=millis(); }
    }
    else if (command.startsWith("HOME_WEATHER ")) {
        int ready,humidity; float temperature; char unit; char condition[24];
        if (sscanf(command.c_str()+13,"%d %f %c %d %23s",&ready,&temperature,&unit,&humidity,condition)==5) {
            weatherReady=ready==1 && isfinite(temperature) && (unit=='C' || unit=='F');
            weatherTemperature=temperature; weatherUnit=unit;
            weatherHumidity=humidity>=0 && humidity<=100?humidity:-1;
            weatherCondition=condition; weatherCondition.replace('_',' '); weatherAt=millis();
        }
    }
    else if (command.startsWith("MUSIC_STATE ")) { musicState=command.substring(12,40); musicAt=millis(); }
    else if (command.startsWith("MUSIC_TITLE ")) musicTitle=command.substring(12,40);
    else if (command.startsWith("MUSIC_ARTIST ")) musicArtist=command.substring(13,41);
    else if (command=="TIMER_UNAVAILABLE") timerAvailable=false;
    else if (command.startsWith("TIMER_LABEL ")) timerLabel=command.substring(12,40);
    else if (command.startsWith("TIMER_RESULT ")) {
        timerResult=command.substring(13,41);timerResultAt=millis();timerBusy=false;
        if (page==Page::NewTimer) page=Page::Timer;
    }
    else if (command.startsWith("TIMER_STATE ")) {
        int count,remaining,finished;
        if (sscanf(command.c_str()+12,"%d %d %d",&count,&remaining,&finished)==3 && count>=0 && count<=16 && remaining>=0 && remaining<=86400) {
            if (finished && !timerFinished) {wakeScreen();page=Page::Timer;}
            timerCount=count; timerSeconds=remaining; timerFinished=finished==1; timerAt=millis(); timerAvailable=true;
        }
    }
    else if ((command=="WAKE" || command.startsWith("WAKE ")) && wakeArmed && !wakeMuted && !intercom.busy() && !listenUntil) {
        wakeScreen();
        page=Page::Voice; thinking=false;
        cueRequest=command=="WAKE"?1:strtoul(command.c_str()+5,nullptr,10);
        cueBefore=audioStatus().cueCompletions; cuePending=true;
        audioCommand(AudioCommand::Chime); listenUntil=millis()+9000; voiceResult="";
        Host.println("EVENT wake_accepted=1");
    }
    else if (command=="VOICE_DONE") { listenUntil=0; thinking=false; voiceResult="Command received"; voiceResultAt=millis(); voiceNotice=false; }
    else if (command=="VOICE_THINKING") { listenUntil=0; voiceResult=""; thinking=true; }
    else if (command.startsWith("AUDIO_BEGIN ") && wakeArmed) {
        audioSession=strtoul(command.c_str()+12,nullptr,10);
        remoteIsMusic=command.endsWith(" M");
        bool alarm=command.endsWith(" A");
        remoteIsIntercom=command.endsWith(" I");
        remoteIsAlarm=alarm;
        bool callAllowed=intercom.enabled && intercom.phase==IntercomState::Active && strcmp(intercom.id,intercom.consent)==0;
        if (audioSession && (remoteIsIntercom?callAllowed:!intercom.busy()) && (!wakeMuted||remoteIsMusic||alarm) && audioRemoteBegin(remoteIsIntercom)) {
            if (remoteIsMusic) page=Page::Music;
            if (alarm) page=Page::Timer;
            Host.printf("EVENT audio_ready=%lu capacity=%lu\n",(unsigned long)audioSession,(unsigned long)remoteCapacity);
        }
        else Host.println("ERROR audio_begin");
    }
    else if (command=="MIC_MONITOR 1" && wakeArmed && !wakeMuted) { audioCommand(AudioCommand::MonitorOn); Host.println("EVENT mic_monitor=1"); }
    else if (command=="MIC_MONITOR 0") { audioCommand(AudioCommand::MonitorOff); Host.println("EVENT mic_monitor=0"); }
    else if (command=="MIC_DUPLEX 1" && wakeArmed && !wakeMuted) { audioCommand(AudioCommand::DuplexOn); Host.println("EVENT mic_duplex=1"); }
    else if (command=="MIC_DUPLEX 0") { audioCommand(AudioCommand::MonitorOff); Host.println("EVENT mic_duplex=0"); }
    else if (command=="AUDIO_END") audioRemoteEnd();
    else if (command=="AUDIO_STOP") audioRemoteStop();
    else if (command.startsWith("VOICE_REPLY ") && wakeArmed && !wakeMuted) {
        listenUntil=0; thinking=false; voiceResult=command.substring(12,132); voiceResultAt=millis(); voiceNotice=false;
    }
    else if (command=="VOICE_UNKNOWN") { listenUntil=0; thinking=false; voiceResult="Try a supported command"; voiceResultAt=millis(); voiceNotice=true; }
    else if (command=="VOICE_TIMEOUT") { cuePending=false; listenUntil=0; thinking=false; voiceResult="Didn't catch that. Try again."; voiceResultAt=millis(); voiceNotice=true; }
    else if (command=="RECORD" && !wakeMuted && !intercom.busy()) audioCommand(AudioCommand::Record);
    else if (command=="STOP") { if(intercom.busy())endIntercom();audioRemoteStop(); audioCommand(AudioCommand::Stop); }
    else if (command=="PLAY" && !intercom.busy()) audioCommand(AudioCommand::Playback);
    else if (command=="CHIME" && !intercom.busy()) audioCommand(AudioCommand::Chime);
    else if (command=="VOL+") { audioCommand(AudioCommand::VolumeUp); preferenceAt=millis(); }
    else if (command=="VOL-") { audioCommand(AudioCommand::VolumeDown); preferenceAt=millis(); }
    else Host.println("ERROR unknown command");
}
static uint32_t crc32(const uint8_t* bytes,size_t count) {
    uint32_t crc=0xFFFFFFFF;
    while(count--) { crc^=*bytes++; for(int bit=0;bit<8;++bit) crc=(crc>>1)^((crc&1)?0xEDB88320:0); }
    return ~crc;
}
static void receiveHost() {
    unsigned currentEpoch=networkEpoch();
    if (currentEpoch!=transportEpoch) {
        homeActionState.tick(millis(),false);
        transportEpoch=currentEpoch; wakeArmed=false; endIntercom(true); cuePending=false; thinking=false; listenUntil=0;
        serialLine=""; incomingSize=0; discardLine=false; audioSession=0;
        audioRemoteStop(); audioCommand(AudioCommand::StreamOff); audioCommand(AudioCommand::Stop);
    }
    // USB pairing is never exposed through the network transport.
    if (networkConnected()) for (int n=0;n<1024 && Serial.available();++n) {
        char c=Serial.read();
        if (c=='\n') { if (!discardUsbLine) networkCommand(usbPairLine); usbPairLine=""; discardUsbLine=false; }
        else if (c!='\r' && !discardUsbLine) { if (usbPairLine.length()<192) usbPairLine+=c; else { usbPairLine=""; discardUsbLine=true; } }
    }
    // Bound work so a sender cannot starve touch or the heartbeat watchdog.
    for (int n=0;n<16384 && transportEpoch==networkEpoch() && Host.available();++n) {
        uint8_t c=Host.read(); incomingAt=millis();
        if (incomingSize) {
            incoming[incomingSize++]=c;
            if (incomingSize<11) continue;
            uint16_t length; memcpy(&length,incoming+5,2);
            if (incoming[4]!=2 || length!=512) {
                incomingSize=0; audioRemoteStop(); Host.println("ERROR audio_header"); continue;
            }
            if (incomingSize<15+length) continue;
            uint32_t expected,sequence;
            memcpy(&expected,incoming+11+length,4); memcpy(&sequence,incoming+7,4);
            int16_t samples[256]; memcpy(samples,incoming+11,512);
            uint32_t actual=crc32(incoming,11+length);
            if (actual!=expected || !audioRemoteWrite(samples,256,sequence)) {
                auto status=audioRemoteStatus();
                audioRemoteStop(); Host.printf("ERROR audio_frame seq=%lu received=%lu active=%d ended=%d crc=%d\n",
                    (unsigned long)sequence,(unsigned long)status.received,status.active,status.ended,actual==expected);
            }
            incomingSize=0;
        } else if (c=='\n') {
            serialLine.trim(); if (!discardLine && serialLine.length()) handleCommand(serialLine); serialLine=""; discardLine=false;
        } else if (c!='\r' && !discardLine) {
            if (serialLine.length()<192) serialLine+=char(c); else { serialLine=""; discardLine=true; }
            if (serialLine=="RV1!") { memcpy(incoming,"RV1!",4); incomingSize=4; serialLine=""; }
        }
    }
    if (incomingSize && millis()-incomingAt>500) { incomingSize=0; audioRemoteStop(); Host.println("ERROR audio_fragment_timeout"); }
    if (audioSession && millis()-lastAudioReport>=25) {
        lastAudioReport=millis(); auto r=audioRemoteStatus();
        Host.printf("EVENT audio_session=%lu received=%lu consumed=%lu active=%d underruns=%lu\n",
            (unsigned long)audioSession,(unsigned long)r.received,(unsigned long)r.consumed,r.active,(unsigned long)r.underruns);
        if (!r.active) audioSession=0;
    }
}
static void sendMic() {
    if (cuePending) {
        if (!wakeArmed || wakeMuted) { cuePending=false; return; }
        if (audioStatus().cueCompletions==cueBefore) return;
        cuePending=false; listenUntil=millis()+9000;
        // This precedes the first captured command packet on the same stream.
        Host.printf("EVENT listening_ready=%lu\n",(unsigned long)cueRequest);
    }
    MicBlock block;
    // Limit each pass so UI, touch, heartbeat expiry, and Stop stay responsive.
    for (int n=0;n<8 && audioReadMic(block,false);++n) {
        if (!wakeArmed || wakeMuted || transportEpoch!=networkEpoch()) { audioReadMic(block); continue; }
        uint8_t packet[1039]; uint16_t micLength=block.count*2;
        uint16_t length=micLength*(block.duplex?2:1); uint32_t sequence=micSequence;
        size_t total=15+length;
        // A transient USB-not-ready result is backpressure, not a reason to
        // discard a microphone frame. Keep it in the bounded capture queue.
        if (Host.availableForWrite()<int(total)) break;
        memcpy(packet,"RV1!",4); packet[4]=block.duplex?3:1;
        memcpy(packet+5,&length,2); memcpy(packet+7,&sequence,4);
        memcpy(packet+11,block.samples,micLength);
        if (block.duplex) memcpy(packet+11+micLength,block.reference,micLength);
        uint32_t crc=crc32(packet,11+length); memcpy(packet+11+length,&crc,4);
        size_t written=Host.write(packet,total);
        if (!written) break; // Nothing was sent; retry this frame on the next loop.
        audioReadMic(block); ++micSequence;
        if (written!=total) { ++usbDrops; break; } // A partial frame cannot be retried intact.
    }
}
void setup() {
    Serial.setTxBufferSize(32768); Serial.setTxTimeoutMs(25);
    Serial.setRxBufferSize(65536);
    Serial.begin(115200);
    // USB carries binary audio and structured status, never free-form logs.
    // NetworkClientSecure retry logs otherwise interleave with mic frames.
    // CORE_DEBUG_LEVEL=0 also removes Arduino's direct ROM logging path.
    Serial.setDebugOutput(false);
    esp_log_level_set("*",ESP_LOG_NONE);
    delay(350);
    pinMode(Board::ampEnable,OUTPUT); digitalWrite(Board::ampEnable,LOW);
    pinMode(Board::bootButton,INPUT_PULLUP);
    if (!psramFound()) { Host.println("ERROR PSRAM unavailable"); return; }
    displayReady=canvas->begin();
    if (!displayReady) { Host.println("ERROR display initialization"); return; }
    voiceBackground=static_cast<uint16_t*>(ps_malloc(466*466*sizeof(uint16_t)));
    if(voiceBackground)for(int y=0;y<466;++y)for(int x=0;x<466;++x)voiceBackground[y*466+x]=VoiceScene::backgroundColor(x,y);
    VoiceScene::prepareOrb(voiceOrb,static_cast<VoiceScene::OrbPixel*>(ps_malloc(VoiceScene::orbCapacity*sizeof(VoiceScene::OrbPixel))));
    preferences.begin("round-voice",false);
    brightness=constrain(preferences.getInt("brightness",120),20,255);
    screenIdle.configure(preferences.getUInt("screenDim",120),preferences.getUInt("screenOff",600));
    screenIdle.activity(millis());
    wakeMuted=preferences.getBool("mic_muted",false);
    panel->setBrightness(brightness); canvas->fillScreen(INK); canvas->flush();
    Wire.begin(Board::sda,Board::scl); Wire.setClock(400000);
    touch.setPins(Board::touchReset,Board::touchIrq);
    touchReady=touch.begin(Wire,0x5A,Board::sda,Board::scl);
    if (!touchReady) touchReady=touch.begin(Wire,0x15,Board::sda,Board::scl);
    int chip=readRegister(0x34,0x03);
    pmuReady=chip>=0 && (chip&0xCF)==0x4A;
    updatePower();
    muteButtonReady=prepareMuteButton();
    SD_MMC.setPins(Board::sdClk,Board::sdCmd,Board::sdD0);
    sdReady=SD_MMC.begin("/sdcard",true,false);
    if (sdReady) sdMegabytes=SD_MMC.cardSize()/(1024*1024);
    // No SD writes. The recording is an explicit eight-second RAM test.
    audioBegin();
    savedVolume=constrain(preferences.getInt("volume",1),0,20);
    for (int i=1;i<savedVolume;++i) { audioCommand(AudioCommand::VolumeUp); delay(20); }
    for (int i=1;i>savedVolume;--i) { audioCommand(AudioCommand::VolumeDown); delay(20); }
    uint64_t mac=ESP.getEfuseMac();
    Host.printf("DEVICE mac=%02X:%02X:%02X:%02X:%02X:%02X\n",unsigned(mac&255),unsigned((mac>>8)&255),
        unsigned((mac>>16)&255),unsigned((mac>>24)&255),unsigned((mac>>32)&255),unsigned((mac>>40)&255));
    networkBegin(); report(); draw();
}
void loop() {
    if (!displayReady) { delay(100); return; }
    pollMuteButton();
    receiveHost();
    if (wakeArmed && millis()-wakeHeartbeat>5000) {
        wakeArmed=false; endIntercom(true); cuePending=false; listenUntil=0; voiceResult=""; thinking=false;
        audioRemoteStop();
        audioCommand(AudioCommand::StreamOff); audioCommand(AudioCommand::Stop);
    }
    if (intercom.busy() && millis()-intercom.at>4000)endIntercom(true);
    if (listenUntil && int32_t(millis()-listenUntil)>=0) listenUntil=0;
    homeActionState.tick(millis(),wakeArmed);
    sendMic();
    int16_t rx=0,ry=0;
    bool pressed=touchReady && touch.getPoint(&rx,&ry,1)>0;
    if(pressed && wakeScreen())discardWakeTouch=true;
    if(discardWakeTouch) {
        touchGesture=TouchGesture{};
        if(pressed)wakeReleaseAt=0;
        else if(!wakeReleaseAt)wakeReleaseAt=millis();
        else if(millis()-wakeReleaseAt>=50)discardWakeTouch=false;
        pressed=false;
    }
    if(pressed && !touchGesture.tracking())touchPage=page;
    auto gesture=touchGesture.update(pressed,constrain(465-rx,0,465),constrain(465-ry,0,465),millis());
    // Incoming wake/music/physical-key navigation invalidates the old surface.
    if(touchPage!=page)gesture.kind=TouchGesture::Kind::None;
    bool swiped=gesture.kind==TouchGesture::Kind::Left || gesture.kind==TouchGesture::Kind::Right;
    if(swiped && !intercom.busy())page=ControlScene::swipePage(page,gesture.kind==TouchGesture::Kind::Left);
    bool touchBegan=gesture.kind==TouchGesture::Kind::Tap;
    if (touchBegan) {
        int x=gesture.x,y=gesture.y;
        auto s=audioStatus();
        if (y>=333 && y<=375) {
            if(intercom.busy())return;
            if (page==Page::Voice && VoiceScene::busy(VoiceScene::resolve(voiceInput(s)))) {
                if(!TouchTargets::navTalk.contains(x,y)) return;
                audioRemoteStop(); audioCommand(AudioCommand::Stop); cuePending=false; listenUntil=0; thinking=false;
                Host.println("EVENT cancelled=1");
            } else if (TouchTargets::navHome.contains(x,y)) { page=Page::Home; homeResult=""; }
            else if (TouchTargets::navMusic.contains(x,y)) page=Page::Music;
            else if (TouchTargets::navTalk.contains(x,y)) { page=Page::Voice; if (!wakeMuted && wakeArmed && s.micReady) Host.println("EVENT talk=1"); }
        } else if (y>=382 && y<=424 && ((x>=154 && x<=199) || (x>=267 && x<=312))) {
            audioCommand(x<233?AudioCommand::VolumeDown:AudioCommand::VolumeUp); preferenceAt=millis();
        } else if (page==Page::Intercom) {
            if(intercom.busy()) {
                if(y>=275 && y<=317 && x>=239 && x<=371)endIntercom();
                else if(y>=275 && y<=317 && x>=95 && x<=227 && !wakeMuted) {
                    if(intercom.phase==IntercomState::Incoming && intercom.authorize(intercom.id))Host.printf("EVENT intercom_action=answer id=%s\n",intercom.id);
                    else if(intercom.phase==IntercomState::Active)muteIntercom();
                }
            } else if(!intercom.enabled) {
                if(y>=275 && y<=317 && x>=125 && x<=341 && wakeArmed && !wakeMuted){intercom.enabled=true;Host.println("EVENT intercom_enabled=1");}
            } else if(y>=274 && y<=316) {
                if(x>=183 && x<=283)endIntercom(true);
                else if(x>=95 && x<=177 && intercom.offset>0)intercom.offset-=2;
                else if(x>=289 && x<=371 && intercom.offset+2<intercom.count)intercom.offset+=2;
            } else if(x>=95 && x<=371 && y>=164 && y<254 && (y-164)%48<42 && intercom.ready && millis()-intercom.at<3000) {
                unsigned index=intercom.offset+(y-164)/48;
                if(index<intercom.count && (intercom.received&(1u<<index)) && (intercom.available&(1u<<index))) {
                    char id[33];snprintf(id,sizeof(id),"%08lx%08lx%08lx%08lx",(unsigned long)esp_random(),(unsigned long)esp_random(),(unsigned long)esp_random(),(unsigned long)esp_random());
                    if(intercom.authorize(id)) {
                        intercom.state(id,IntercomState::Outgoing,true,millis());strcpy(intercom.room,intercom.rooms[index]);
                        intercom.awaiting=true;intercom.requestedAt=millis();
                        audioCommand(AudioCommand::StreamOff);
                        Host.printf("EVENT intercom_call=%u binding=%s id=%s\n",index,intercom.binding,id);
                    }
                }
            }
        } else if (page==Page::Home) {
            if (TouchTargets::homeThermostat.contains(x,y)) page=Page::Thermostat;
            else if (TouchTargets::homeBose.contains(x,y)) page=Page::Soundbar;
            else if (TouchTargets::homeLights.contains(x,y)) page=Page::Lights;
            else if (TouchTargets::homeWeather.contains(x,y)) page=Page::Weather;
            else if (TouchTargets::homeTimers.contains(x,y)) page=Page::Timer;
            else if (TouchTargets::homeSettings.contains(x,y)) page=Page::Settings;
        } else if (page==Page::Lights && wakeArmed && lightsAt && millis()-lightsAt<20000) {
            const char* rooms[]={"bedroom","living_room","dining_room","patio"};
            for(int j=0;j<4;++j)if(TouchTargets::roomLights[j].contains(x,y) && (lightsReady&(1u<<j)) && homeActionState.begin(millis())) {
                Host.printf("EVENT light_action=%s:%s request=%lu binding=%s\n",rooms[j],lightsOn&(1u<<j)?"off":"on",(unsigned long)homeActionState.request,lightsBinding);
                break;
            }
        } else if (page==Page::Weather && y>=287 && y<=329 && x>=125 && x<=341) {
            page=Page::Home;
        } else if (page==Page::Thermostat) {
            if (y>=275 && y<=317 && x>=142 && x<=324 && modesFresh() && tempModes) page=Page::ThermostatMode;
            else if (y>=226 && y<=268 && homeFresh() && strcmp(tempMode,"heat_cool")!=0) {
                if (x>=125 && x<=205 && tempTarget>tempMin) homeAction("temp_down");
                else if (x>=261 && x<=341 && tempTarget<tempMax) homeAction("temp_up");
            }
        } else if (page==Page::ThermostatMode && y>=125 && y<=311 && (y-125)%48<=42) {
            int column=x>=95 && x<=227?0:x>=239 && x<=371?1:-1;
            if (column>=0) {
                int index=((y-125)/48)*2+column;
                if (index==7) page=Page::Thermostat;
                else if (modesFresh() && (tempModes&(1u<<index)) && !homeActionState.pending()) {
                    String action="mode_"+String(modeNames[index]); homeAction(action.c_str()); page=Page::Thermostat;
                }
            }
        } else if (page==Page::Soundbar) {
            if (y>=96 && y<=138 && x>=83 && x<383) {page=Page::SpeakerPicker;speakerOffset=max(0,speakerSelected/3*3);}
            else if (soundFresh() && y>=273 && y<=315 && x>=132 && x<=334) page=Page::SoundbarVolume;
            else if (soundFresh() && y>=220 && y<=262) {
                bool playing=strcmp(soundState,"playing")==0,on=strcmp(soundState,"off")!=0;
                if (x>=95 && x<=223 && (soundFeatures&(playing?1:16384))) homeAction(playing?"sound_pause":"sound_play");
                else if (x>=243 && x<=371 && (soundFeatures&(on?256:128))) homeAction(on?"sound_off":"sound_on");
            }
        } else if (page==Page::SpeakerPicker) {
            if(y>=282 && y<=324) {
                if(x>=181 && x<285)page=Page::Soundbar;
                else if(x>=90 && x<173 && speakerOffset>0)speakerOffset-=3;
                else if(x>=293 && x<376 && speakerOffset+3<speakerCount)speakerOffset+=3;
            } else if(x>=83 && x<383 && y>=142 && y<276 && (y-142)%46<42 && wakeArmed && speakerListAt && millis()-speakerListAt<20000) {
                int index=speakerOffset+(y-142)/46;
                if(index<speakerCount && (speakerReceived&(1u<<index)) && homeActionState.begin(millis())) {
                    Host.printf("EVENT speaker_select=%d request=%lu binding=%s\n",index,(unsigned long)homeActionState.request,speakerRevision);
                    page=Page::Soundbar;
                }
            }
        } else if (page==Page::SoundbarVolume) {
            if (y>=265 && y<=307 && x>=239 && x<=371) page=Page::Soundbar;
            else if (soundFresh()) {
                if (y>=207 && y<=249 && soundVolume>=0 && (soundFeatures&4)) {
                    if (x>=125 && x<=205 && soundVolume>0) homeAction("sound_down");
                    else if (x>=261 && x<=341 && soundVolume<100) homeAction("sound_up");
                } else if (y>=265 && y<=307 && x>=95 && x<=227 && soundMuted>=0 && (soundFeatures&8)) homeAction(soundMuted?"sound_unmute":"sound_mute");
            }
        } else if (page==Page::Settings) {
            if (y>=280 && y<=322 && x>=90 && x<181) page=Page::Screen;
            else if (y>=280 && y<=322 && x>=188 && x<279) page=Page::Network;
            else if (y>=280 && y<=322 && x>=286 && x<377) page=Page::Intercom;
            else if (TouchTargets::microphone.contains(x,y)) setWakeMuted(!wakeMuted);
            else if (TouchTargets::brightnessDown.contains(x,y) || TouchTargets::brightnessUp.contains(x,y)) {
                brightness=constrain(brightness+(x<233?-20:20),ControlScene::brightnessMinimum,ControlScene::brightnessMaximum);
                applyScreenBrightness(); preferences.putInt("brightness",brightness);
            }
        } else if (page==Page::Screen) {
            if(y>=287 && y<329 && x>=239 && x<371)page=Page::Settings;
            else if(y>=287 && y<329 && x>=95 && x<227){screenIdle.sleep();applyScreenBrightness();}
            else if(x>=99 && x<367 && ((y>=165 && y<207)||(y>=214 && y<256))) {
                const unsigned times[]={0,60,120,300,600,900};
                bool dim=y<207;unsigned current=dim?screenIdle.dimSeconds:screenIdle.offSeconds;
                int index=0;for(int i=0;i<6;++i)if(times[i]==current)index=i;
                for(int n=1;n<=6;++n) {
                    unsigned next=times[(index+n)%6];
                    if(screenIdle.configure(dim?next:screenIdle.dimSeconds,dim?screenIdle.offSeconds:next))break;
                }
                preferences.putUInt("screenDim",screenIdle.dimSeconds);preferences.putUInt("screenOff",screenIdle.offSeconds);
            }
        } else if (page==Page::Music && y>=282 && y<=324 && wakeArmed && millis()-musicAt<5000) {
            auto state=MusicUi::resolve(true,musicState.c_str());
            const char* action=TouchTargets::musicPrevious.contains(x,y) && MusicUi::canSkip(state)?"previous":TouchTargets::musicNext.contains(x,y) && MusicUi::canSkip(state)?"next":TouchTargets::musicToggle.contains(x,y) && MusicUi::canToggle(state)?"toggle":nullptr;
            if(action)Host.printf("EVENT music_action=%s\n",action);
        } else if (page==Page::Timer && timersFresh()) {
            if (y>=287 && y<=329 && x>=125 && x<=341 && timerCount<16) {
                timerResult=""; page=Page::NewTimer;
            } else if (y>=239 && y<=281 && timerCount && x>=100 && x<=366) {
                timerResult="";
                if (x<228 || (x>=240 && timerCount>1)) Host.printf("EVENT timer_action=%s\n",x<233?"dismiss":"next");
            }
        } else if (page==Page::NewTimer) {
            if (y>=287 && y<=329 && x>=239 && x<=371) page=Page::Timer;
            else if (!timerBusy) {
                if (y>=190 && y<=232) {
                    if (x>=95 && x<=227) timerMinutes=max(1,timerMinutes-1);
                    else if (x>=239 && x<=371) timerMinutes=min(120,timerMinutes+1);
                } else if (y>=239 && y<=281) {
                    if (x>=95 && x<=179) timerMinutes=5;
                    else if (x>=191 && x<=275) timerMinutes=15;
                    else if (x>=287 && x<=371) timerMinutes=30;
                } else if (y>=287 && y<=329 && x>=95 && x<=227 && timersFresh() && timerCount<16) {
                    timerBusy=true; timerRequestAt=millis();
                    Host.printf("EVENT timer_start=%d\n",timerMinutes*60);
                }
            }
        }
    }
    if (timerBusy && (millis()-timerRequestAt>20000 || !wakeArmed)) {
        timerBusy=false;timerResult="Check timer status";timerResultAt=millis();
        if (page==Page::NewTimer) page=Page::Timer;
    }
    if (preferenceAt && millis()-preferenceAt>=1000) {
        savedVolume=audioStatus().volume; preferences.putInt("volume",savedVolume); preferenceAt=0;
    }
    if (millis()-lastPower>=5000) { lastPower=millis(); updatePower(); }
    auto currentAudio=audioStatus();
    bool engaged=cuePending || listenUntil || thinking || intercom.busy() || currentAudio.mode==AudioMode::Recording || currentAudio.mode==AudioMode::Chime || currentAudio.mode==AudioMode::Playback || (currentAudio.mode==AudioMode::Remote && !remoteIsMusic);
    screenIdle.update(millis(),engaged);applyScreenBrightness();
    // Full-frame QSPI flushes are expensive; leave USB enough time to refill
    // 48 kHz output. Touch still runs on every loop and gets an immediate frame.
    if (touchBegan || swiped || millis()-lastFrame>=100) { lastFrame=millis(); draw(); }
    if (millis()-lastReport>=5000) { lastReport=millis(); report(); }
    delay(2);
}
