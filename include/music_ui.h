#pragma once
#include <string.h>

// Shared presentation and touch policy. This does not operate the receiver.
namespace MusicUi {
enum class State { Offline, Disabled, Setup, Unavailable, Discoverable, Connected, Playing, Paused, Stopped, Unknown };
inline State resolve(bool fresh,const char* status) {
    if(!fresh)return State::Offline;
    if(strcmp(status,"not_configured")==0)return State::Disabled;
    if(strcmp(status,"runtime_missing")==0)return State::Setup;
    if(strcmp(status,"unavailable")==0 || strcmp(status,"disconnected")==0)return State::Unavailable;
    if(strcmp(status,"discoverable")==0)return State::Discoverable;
    if(strcmp(status,"connected")==0)return State::Connected;
    if(strcmp(status,"playing")==0)return State::Playing;
    if(strcmp(status,"paused")==0)return State::Paused;
    if(strcmp(status,"stopped")==0)return State::Stopped;
    return State::Unknown;
}
inline bool canSkip(State state) { return state==State::Playing || state==State::Paused || state==State::Stopped; }
inline bool canToggle(State state) { return canSkip(state) || state==State::Connected; }
inline const char* subtitle(State state) {
    switch(state) {
        case State::Offline:return "Host disconnected";
        case State::Disabled:return "Spotify is not set up";
        case State::Setup:return "Spotify needs setup";
        case State::Unavailable:return "Spotify unavailable";
        case State::Discoverable:return "Ready to connect";
        case State::Connected:return "Spotify connected";
        case State::Unknown:return "Music status unavailable";
        default:return "Spotify";
    }
}
inline const char* detail(State state,int volume) {
    switch(state) {
        case State::Offline:return "Connect your local host";
        case State::Disabled:return "Enable Spotify on your host";
        case State::Setup:return "Complete setup on your host";
        case State::Unavailable:return "Check Spotify on your host";
        case State::Discoverable:return "Select Round Voice in Spotify";
        case State::Connected:return "Tap Play to listen here";
        case State::Playing:return volume?"Playing":"Playing / sound off";
        case State::Paused:return "Paused";
        case State::Stopped:return "Stopped";
        default:return "Waiting for Spotify status";
    }
}
}
