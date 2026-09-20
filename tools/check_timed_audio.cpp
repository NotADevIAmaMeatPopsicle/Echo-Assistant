#include "../include/timed_audio.h"
#include <cassert>
#include <cmath>
#include <cstdio>
#include <vector>

int main(){
    std::vector<int16_t> storage(TimedAudio::capacity*TimedAudio::frames);
    TimedAudio::Queue q;q.storage(storage.data());
    int16_t a[256],b[256],out[256];
    for(int i=0;i<256;++i){a[i]=int16_t(i*100-12000);b[i]=int16_t(13600-i*100);}
    assert(q.push(a,0,1000000,900000));assert(q.push(b,1,1005333,900000));
    q.render(out,990000);for(auto value:out)assert(value==0);
    assert(q.consumed==0);q.render(out,1000000);
    for(int i=0;i<256;++i)assert(out[i]==a[i]);
    q.render(out,1005334);assert(q.consumed==1&&q.late==0);assert(std::abs(int(out[0])-b[0])<=5);
    q.reset();assert(q.push(a,0,1000000,900000));assert(q.push(b,1,1005333,900000));
    q.render(out,1007000);assert(q.late==1&&q.consumed>=1);assert(std::abs(int(out[0])-b[80])<=5);
    q.reset();assert(!q.push(a,1,1000000,900000));assert(!q.push(a,0,4000000,900000));
    assert(!q.push(a,0,1,4000000));assert(!q.push(a,0,UINT64_MAX,900000));
    for(unsigned i=0;i<TimedAudio::capacity;++i)assert(q.push(a,i,1000000+(uint64_t(i)*256*1000000)/48000,900000));
    assert(!q.push(a,256,2400000,900000));
    q.render(out,2450000);assert(q.consumed==256);for(auto value:out)assert(value==0);
    q.reset();assert(q.push(a,0,1000000,900000));q.render(out,1000010);
    assert(std::abs(int(out[0])-(-11952))<=1); // Half-sample interpolation, not whole-block drift correction.
    TimedAudio::DmaClock clock;
    assert(!clock.ready(1000000));
    for(unsigned i=0;i<12;++i)clock.wrote(1000000+(uint64_t(i)*256*1000000)/48000);
    assert(clock.ready(1058666));auto scheduled=clock.presentation(1058666);
    assert(scheduled>1090000&&scheduled<1110000);
    assert(!clock.ready(1150000));clock.wrote(1150000);assert(!clock.ready(1150000));
    std::puts("PASS: timestamped PCM, silence before due time, fractional sampling, late discard, bounded queue and DMA-clock recovery. No audio device.");
}
