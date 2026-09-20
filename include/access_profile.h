#pragma once
#include <stdint.h>
#include <string.h>
struct MiniAccess {
    bool guest=false,conversation=true,temperature=true,speaker=true;
    unsigned lights=15;uint32_t revision=0;char name[25]="Household";
    bool configure(uint32_t rev,unsigned limited,unsigned talk,const char* label){
        if(limited>1||talk>1||!label[0]||strlen(label)>24)return false;
        for(const char* c=label;*c;++c)if(*c<32||*c>126)return false;
        revision=rev;guest=limited;conversation=talk;strcpy(name,label);
        temperature=speaker=!guest;lights=guest?0:15;return true;
    }
    bool permissions(unsigned climate,unsigned sound,unsigned rooms){
        if(climate>1||sound>1||rooms>15)return false;
        temperature=climate;speaker=sound;lights=rooms;return true;
    }
    bool home(const char* action)const{return strncmp(action,"sound_",6)==0?speaker:temperature;}
};
