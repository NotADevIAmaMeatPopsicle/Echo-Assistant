#pragma once
#include <stdint.h>
#include <string.h>

// Presentation times are microseconds on the device's monotonic clock, never
// wall time. Late samples are discarded instead of making the room fall behind.
namespace TimedAudio {
constexpr uint32_t rate=48000, frames=256, capacity=256;
constexpr int64_t blockNs=int64_t(frames)*1000000000LL/rate;

class Queue {
    int16_t* pcm=nullptr;
    uint64_t deadlines[capacity]{};
    uint64_t previous=0;
    uint32_t touched=0xffffffff;
public:
    uint32_t received=0,consumed=0,missing=0,late=0;
    void storage(int16_t* value){pcm=value;}
    void reset(){received=consumed=missing=late=0;previous=0;touched=0xffffffff;}
    bool push(const int16_t* samples,uint32_t sequence,uint64_t at,uint64_t now){
        if(!pcm||sequence!=received||received-consumed>=capacity||!at||
           (at<now&&now-at>2000000)||(at>now&&at-now>2000000)||
           (received&&at<=previous))return false;
        memcpy(pcm+(received%capacity)*frames,samples,frames*sizeof(int16_t));
        deadlines[received%capacity]=at;previous=at;++received;return true;
    }
    void render(int16_t* out,uint64_t presentation){
        for(uint32_t i=0;i<frames;++i){
            out[i]=0;
            const int64_t target=int64_t(presentation)*rate+int64_t(i)*1000000;
            while(consumed<received){
                const int64_t delta=target-int64_t(deadlines[consumed%capacity])*rate;
                if(delta<int64_t(frames)*1000000)break;
                if(touched!=consumed)++late;
                ++consumed;
            }
            if(consumed==received){if(received)++missing;continue;}
            const int64_t delta=target-int64_t(deadlines[consumed%capacity])*rate;
            if(delta<0)continue;
            touched=consumed;
            const uint32_t index=uint32_t(delta/1000000),fraction=uint32_t(delta%1000000);
            const int16_t a=pcm[(consumed%capacity)*frames+index];
            int16_t b=a;
            if(index+1<frames)b=pcm[(consumed%capacity)*frames+index+1];
            else if(consumed+1<received&&deadlines[(consumed+1)%capacity]>=deadlines[consumed%capacity]+5332&&deadlines[(consumed+1)%capacity]<=deadlines[consumed%capacity]+5334)
                b=pcm[((consumed+1)%capacity)*frames];
            out[i]=int16_t(int32_t(a)+(int64_t(int32_t(b)-a)*fraction)/1000000);
        }
    }
};

// The legacy I2S driver recycles a completed DMA descriptor. With eight
// descriptors, its next block reaches the codec seven blocks after acquisition.
// Predict the next acquisition from the preceding blocking write. Small task
// wake jitter is filtered; a missed deadline invalidates this estimate until
// eight fresh writes have passed. Codec/acoustic delay is calibrated separately.
class DmaClock {
    int64_t nextNs=0;
    uint32_t stable=0;
public:
    bool ready(uint64_t now)const{return stable>=8&&int64_t(now)*1000-nextNs<blockNs;}
    uint64_t presentation(uint64_t now)const{return ready(now)?uint64_t((nextNs+7*blockNs)/1000):0;}
    void wrote(uint64_t now){
        const int64_t value=int64_t(now)*1000,error=value-nextNs;
        if(!nextNs||error>blockNs||error<-blockNs){nextNs=value+blockNs;stable=0;return;}
        nextNs+=blockNs+error/16;if(stable<8)++stable;
    }
};
}
