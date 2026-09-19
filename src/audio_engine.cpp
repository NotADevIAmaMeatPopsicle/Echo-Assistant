#include <Arduino.h>
#include <driver/i2s.h>
#include <esp_heap_caps.h>
#include <math.h>
#include "board.h"
#include "audio_engine.h"
#include "es7210.h"
#include "es8311.h"
#include "activation_dong.h"
#include "mic_filter.h"

namespace {
constexpr size_t framesPerBlock=256, captureCapacity=Board::voiceRate*8;
int16_t* capture=nullptr;
int16_t* remotePcm=nullptr;
RemoteStatus remote;
uint32_t remoteGeneration=0;
uint32_t remotePrebuffer=32;
portMUX_TYPE remoteLock=portMUX_INITIALIZER_UNLOCKED;
QueueHandle_t commands=nullptr;
QueueHandle_t micBlocks=nullptr;
struct MicControl { bool streaming=false,monitor=false,duplex=false; uint32_t generation=0; } micControl;
portMUX_TYPE micLock=portMUX_INITIALIZER_UNLOCKED;
MicControl requestedMic() {
    portENTER_CRITICAL(&micLock); auto value=micControl; portEXIT_CRITICAL(&micLock); return value;
}
portMUX_TYPE statusLock=portMUX_INITIALIZER_UNLOCKED;
AudioStatus shared;
void publish(const AudioStatus& status) {
    portENTER_CRITICAL(&statusLock); shared=status; portEXIT_CRITICAL(&statusLock);
}
void worker(void*) {
    AudioStatus state=audioStatus();
    int16_t tx[framesPerBlock*2]{}, rx[framesPerBlock*2]{};
    int16_t referenceTx[framesPerBlock]{};
    uint32_t position=0, tailFrames=0;
    // Leave the amp enabled until the queued audio has crossed all eight DMA
    // descriptors. Otherwise the final ~128 ms is cut off at every natural end.
    constexpr uint32_t drainFrames=framesPerBlock*9;
    bool amp=false;
    bool remoteStarted=false, buffering=false;
    bool monitorOutput=false, duplexOutput=false;
    uint32_t generation=0;
    float micHistory[63]{};
    float referenceHistory[63]{};
    uint32_t micIndex=0,micPhase=0;
    MicBlock micPending{};
    uint32_t micGeneration=0;
    while (true) {
        // Capture control cannot be dropped behind a full playback/control
        // queue. Discard frames from the preceding mute/connection epoch.
        auto requested=requestedMic();
        if (requested.generation!=micGeneration) {
            micGeneration=requested.generation;
            state.streaming=requested.streaming;
            monitorOutput=requested.monitor; duplexOutput=requested.duplex;
            micPending.count=0; xQueueReset(micBlocks);
        }
        AudioCommand command;
        while (xQueueReceive(commands,&command,0)==pdTRUE) {
            if (command==AudioCommand::Record && state.micReady) {
                state.recordedSamples=0; position=0; tailFrames=0; state.mode=AudioMode::Recording;
            } else if (command==AudioCommand::Stop) { audioRemoteStop(); state.mode=AudioMode::Idle; }
            else if (command==AudioCommand::Playback && state.recordedSamples && state.speakerReady) {
                state.mode=AudioMode::Playback; position=0; tailFrames=0;
            } else if (command==AudioCommand::Chime && state.speakerReady) {
                state.mode=AudioMode::Chime; position=0; tailFrames=0;
                micPending.count=0; xQueueReset(micBlocks);
            } else if (command==AudioCommand::VolumeUp) state.volume=min(state.volume+1,20);
            else if (command==AudioCommand::VolumeDown) state.volume=max(state.volume-1,0);
        }
        portENTER_CRITICAL(&remoteLock);
        if (generation!=remoteGeneration) {
            generation=remoteGeneration; remoteStarted=false; buffering=false; tailFrames=0;
        }
        if (remote.active) state.mode=AudioMode::Remote;
        else if (state.mode==AudioMode::Remote) state.mode=AudioMode::Idle;
        portEXIT_CRITICAL(&remoteLock);
        bool output=(state.mode==AudioMode::Playback || state.mode==AudioMode::Chime || state.mode==AudioMode::Remote) && state.volume;
        if (output!=amp) { amp=output; digitalWrite(Board::ampEnable,amp?HIGH:LOW); }
        state.peak=0;
        size_t bytes=0;
        if (i2s_read(I2S_NUM_0,rx,sizeof(rx),&bytes,0)!=ESP_OK) ++state.errors;
        for (size_t i=0;i<bytes/4;++i) {
            micHistory[micIndex]=rx[i*2];
            // Pair the previous render block with RX at the capture clock.
            // Reference is BEFORE final volume attenuation: at 1% the rendered
            // signal falls below WebRTC's render activity threshold. The AEC
            // estimates speaker gain plus DMA/codec/acoustic delay itself.
            referenceHistory[micIndex]=referenceTx[i];
            micIndex=(micIndex+1)%63;
            if (++micPhase<3) continue;
            micPhase=0;
            float filtered=0,referenceFiltered=0;
            for (int tap=0;tap<63;++tap) {
                uint32_t index=(micIndex+62-tap)%63;
                filtered+=micFilter[tap]*micHistory[index];
                if (duplexOutput) referenceFiltered+=micFilter[tap]*referenceHistory[index];
            }
            int16_t sample=constrain(int(filtered),-32768,32767);
            state.peak=max(state.peak,static_cast<uint16_t>(abs(static_cast<int>(sample))));
            if (state.mode==AudioMode::Recording && state.recordedSamples<captureCapacity) capture[state.recordedSamples++]=sample;
            // Monitoring requires explicit host negotiation. StreamOff,
            // including software mute/heartbeat loss, disables both modes.
            if (state.streaming && (state.mode==AudioMode::Idle || (monitorOutput && state.mode==AudioMode::Remote))) {
                micPending.reference[micPending.count]=constrain(int(referenceFiltered),-32768,32767);
                micPending.samples[micPending.count++]=sample;
                if (micPending.count==256) {
                    micPending.duplex=duplexOutput && state.mode==AudioMode::Remote;
                    micPending.generation=micGeneration;
                    if (xQueueSend(micBlocks,&micPending,0)!=pdTRUE) ++state.streamDrops;
                    micPending.count=0;
                }
            } else micPending.count=0;
        }
        if (state.mode==AudioMode::Recording && state.recordedSamples==captureCapacity) state.mode=AudioMode::Idle;
        int16_t remoteBlock[framesPerBlock]{};
        if (state.mode==AudioMode::Remote) {
            portENTER_CRITICAL(&remoteLock);
            uint32_t queued=remote.received-remote.consumed;
            if (!remoteStarted && (queued>=remotePrebuffer || remote.ended)) remoteStarted=true;
            if (buffering && (queued>=remotePrebuffer || remote.ended)) buffering=false;
            if (remoteStarted && !buffering && queued) {
                memcpy(remoteBlock,remotePcm+(remote.consumed%remoteCapacity)*framesPerBlock,sizeof(remoteBlock));
                ++remote.consumed; tailFrames=0;
            } else if (remoteStarted && !queued && remote.ended) {
                tailFrames+=framesPerBlock;
                if (tailFrames>=drainFrames) { remote.active=false; state.mode=AudioMode::Idle; }
            } else if (remoteStarted && !queued && !buffering) {
                ++remote.underruns; buffering=true;
            }
            portEXIT_CRITICAL(&remoteLock);
        }
        for (size_t i=0;i<framesPerBlock;++i) {
            int sample=0;
            referenceTx[i]=(state.mode==AudioMode::Remote && state.volume)?remoteBlock[i]:0;
            if (state.mode==AudioMode::Remote) sample=remoteBlock[i]*state.volume/100;
            else if (state.mode==AudioMode::Playback) {
                if (position<state.recordedSamples*3) sample=capture[position++/3]*state.volume/100;
                else if (++tailFrames>=drainFrames) state.mode=AudioMode::Idle;
            } else if (state.mode==AudioMode::Chime) {
                constexpr uint32_t length=sizeof(activationDong)/sizeof(activationDong[0]);
                if (position<length*3) {
                    sample=activationDong[position++/3]*min(state.volume,2)/100;
                } else if (++tailFrames>=drainFrames) { state.mode=AudioMode::Idle; ++state.cueCompletions; }
            }
            tx[i*2]=tx[i*2+1]=sample;
        }
        bytes=0;
        if (i2s_write(I2S_NUM_0,tx,sizeof(tx),&bytes,pdMS_TO_TICKS(100))!=ESP_OK || bytes!=sizeof(tx)) ++state.errors;
        publish(state);
    }
}
}

AudioStatus audioStatus() {
    portENTER_CRITICAL(&statusLock); AudioStatus result=shared; portEXIT_CRITICAL(&statusLock); return result;
}
RemoteStatus audioRemoteStatus() {
    portENTER_CRITICAL(&remoteLock); RemoteStatus result=remote; portEXIT_CRITICAL(&remoteLock); return result;
}
bool audioRemoteBegin(bool intercom) {
    if (!remotePcm || !audioStatus().speakerReady) return false;
    portENTER_CRITICAL(&remoteLock);
    remote=RemoteStatus{}; remote.active=true; remotePrebuffer=intercom?8:32; ++remoteGeneration;
    portEXIT_CRITICAL(&remoteLock); return true;
}
bool audioRemoteWrite(const int16_t* samples,uint16_t count,uint32_t sequence) {
    portENTER_CRITICAL(&remoteLock);
    bool ok=remote.active && !remote.ended && count==framesPerBlock && sequence==remote.received && remote.received-remote.consumed<remoteCapacity;
    if (ok) { memcpy(remotePcm+(remote.received%remoteCapacity)*framesPerBlock,samples,framesPerBlock*2); ++remote.received; }
    portEXIT_CRITICAL(&remoteLock); return ok;
}
void audioRemoteEnd() { portENTER_CRITICAL(&remoteLock); remote.ended=true; portEXIT_CRITICAL(&remoteLock); }
void audioRemoteStop() { portENTER_CRITICAL(&remoteLock); remote.active=false; ++remoteGeneration; portEXIT_CRITICAL(&remoteLock); }
void audioCommand(AudioCommand command) {
    if (command==AudioCommand::StreamOn || command==AudioCommand::StreamOff ||
        command==AudioCommand::MonitorOn || command==AudioCommand::MonitorOff || command==AudioCommand::DuplexOn) {
        portENTER_CRITICAL(&micLock);
        if (command==AudioCommand::StreamOn) micControl.streaming=true;
        else if (command==AudioCommand::StreamOff) micControl.streaming=micControl.monitor=micControl.duplex=false;
        else if (command==AudioCommand::MonitorOff) micControl.monitor=micControl.duplex=false;
        else if (micControl.streaming) {
            micControl.monitor=true; micControl.duplex=command==AudioCommand::DuplexOn;
        }
        ++micControl.generation;
        portEXIT_CRITICAL(&micLock);
        return;
    }
    if (commands) xQueueSend(commands,&command,0);
}
bool audioReadMic(MicBlock& block, bool consume) {
    auto requested=requestedMic();
    for (int n=0;n<12 && micBlocks && xQueuePeek(micBlocks,&block,0)==pdTRUE;++n) {
        if (requested.streaming && block.generation==requested.generation) {
            if (consume) xQueueReceive(micBlocks,&block,0);
            return true;
        }
        xQueueReceive(micBlocks,&block,0); // Discard only obsolete capture generations.
    }
    return false;
}
bool audioBegin() {
    pinMode(Board::ampEnable,OUTPUT); digitalWrite(Board::ampEnable,LOW);
    capture=static_cast<int16_t*>(heap_caps_malloc(captureCapacity*sizeof(int16_t),MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT));
    remotePcm=static_cast<int16_t*>(heap_caps_malloc(remoteCapacity*framesPerBlock*2,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT));
    commands=xQueueCreate(8,sizeof(AudioCommand));
    micBlocks=xQueueCreate(12,sizeof(MicBlock));
    if (!capture || !remotePcm || !commands || !micBlocks) return false;
    // One clock master for RX and TX. Use the proven legacy driver to avoid the
    // pinned Arduino/IDF new-driver PSRAM callback-context bug documented in Harness.
    i2s_config_t config{};
    config.mode=static_cast<i2s_mode_t>(I2S_MODE_MASTER|I2S_MODE_RX|I2S_MODE_TX);
    config.sample_rate=Board::sampleRate;
    config.bits_per_sample=I2S_BITS_PER_SAMPLE_16BIT;
    config.channel_format=I2S_CHANNEL_FMT_RIGHT_LEFT;
    config.communication_format=I2S_COMM_FORMAT_STAND_I2S;
    config.intr_alloc_flags=ESP_INTR_FLAG_LEVEL1;
    config.dma_desc_num=8; config.dma_frame_num=framesPerBlock;
    config.mclk_multiple=I2S_MCLK_MULTIPLE_256; config.tx_desc_auto_clear=true;
    if (i2s_driver_install(I2S_NUM_0,&config,0,nullptr)!=ESP_OK) return false;
    i2s_pin_config_t pins{};
    pins.mck_io_num=Board::audioMclk; pins.bck_io_num=Board::audioBclk; pins.ws_io_num=Board::audioWs;
    pins.data_out_num=Board::audioOut; pins.data_in_num=Board::audioIn;
    if (i2s_set_pin(I2S_NUM_0,&pins)!=ESP_OK) { i2s_driver_uninstall(I2S_NUM_0); return false; }
    i2s_zero_dma_buffer(I2S_NUM_0);
    AudioStatus initial;
    initial.micReady=es7210_init();
    auto codec=es8311_create(0,ES8311_ADDRESS_0);
    es8311_clock_config_t clock{};
    clock.mclk_from_mclk_pin=true; clock.mclk_frequency=Board::sampleRate*256; clock.sample_frequency=Board::sampleRate;
    initial.speakerReady=codec && es8311_init(codec,&clock,ES8311_RESOLUTION_16,ES8311_RESOLUTION_16)==ESP_OK;
    // The attached speaker was too loud at 8% with the DAC at full gain.
    // The codec's register scale is logarithmic: "60%" heavily attenuates an
    // already quiet 2% PCM signal. Keep a useful DAC range and small PCM steps.
    if (initial.speakerReady) initial.speakerReady=es8311_voice_volume_set(codec,90,nullptr)==ESP_OK;
    initial.ready=initial.micReady || initial.speakerReady;
    publish(initial);
    if (xTaskCreatePinnedToCore(worker,"round-audio",8192,nullptr,4,nullptr,0)!=pdPASS) {
        initial.ready=false; publish(initial); i2s_driver_uninstall(I2S_NUM_0); return false;
    }
    return initial.ready;
}
