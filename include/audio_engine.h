#pragma once
#include <stdint.h>
enum class AudioMode : uint8_t { Idle, Recording, Playback, Chime, Remote };
enum class AudioCommand : uint8_t { Record, Stop, Playback, Chime, VolumeUp, VolumeDown, StreamOn, StreamOff, MonitorOn, MonitorOff, DuplexOn };
struct AudioStatus {
    AudioMode mode=AudioMode::Idle;
    bool ready=false, micReady=false, speakerReady=false;
    uint32_t recordedSamples=0, errors=0;
    uint16_t peak=0;
    int volume=1;
    bool streaming=false;
    uint32_t streamDrops=0;
    uint32_t cueCompletions=0;
};
struct MicBlock { int16_t samples[256], reference[256]; uint32_t generation; uint16_t count; bool duplex; };
struct RemoteStatus {
    bool active=false, ended=false;
    uint32_t received=0, consumed=0, underruns=0;
};
constexpr uint32_t remoteCapacity=256;
bool audioRemoteBegin(bool intercom=false);
bool audioRemoteWrite(const int16_t* samples, uint16_t count, uint32_t sequence);
void audioRemoteEnd();
void audioRemoteStop();
RemoteStatus audioRemoteStatus();
bool audioReadMic(MicBlock& block, bool consume=true);
bool audioBegin();
void audioCommand(AudioCommand command);
AudioStatus audioStatus();
