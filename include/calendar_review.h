#pragma once
#include <stdint.h>
#include <string.h>
#include <stdio.h>

struct CalendarReview {
    static constexpr unsigned capacity=128,width=24,perPage=4;
    char id[33]{},rows[capacity][width+1]{};
    bool received[capacity]{};
    unsigned count=0,page=0;
    uint32_t checksum=0,started=0,ttl=0,seen=0;
    bool allowed=false,ready=false,confirming=false,pending=false;
    enum Result { None, Accepted, Rejected, Unconfirmed } result=None;
    static bool identifier(const char* value){return strlen(value)==32 && strspn(value,"0123456789abcdef")==32;}
    void clear(){id[0]=0;count=page=seen=0;allowed=ready=confirming=pending=false;result=None;memset(received,0,sizeof(received));}
    bool begin(const char* value,unsigned total,unsigned enable,unsigned seconds,uint32_t digest,uint32_t now){
        if(!identifier(value)||!total||total>capacity||enable>1||!seconds||seconds>900)return false;
        clear();strcpy(id,value);count=total;allowed=enable;ttl=seconds*1000;checksum=digest;started=now;return true;
    }
    bool row(const char* value,unsigned index,const char* text){
        if(ready||!id[0]||strcmp(id,value)||index>=count||strlen(text)>width)return false;
        for(const char* c=text;*c;++c)if(*c<32||*c>126)return false;
        strcpy(rows[index],text);received[index]=true;return true;
    }
    bool commit(const char* value){
        if(!id[0]||strcmp(value,id)||ready)return false;
        uint32_t digest=2166136261u;
        auto byte=[&](char c){digest=(digest^uint8_t(c))*16777619u;};
        byte(allowed?'1':'0');byte('\n');
        for(unsigned i=0;i<count;++i){if(!received[i])return false;for(const char* c=rows[i];*c;++c)byte(*c);byte('\n');}
        if(digest!=checksum)return false;
        ready=true;seen=1;return true;
    }
    unsigned pages()const{return (count+perPage-1)/perPage;}
    bool reviewed()const{return ready && seen==(pages()==32?0xffffffffu:(1u<<pages())-1);}
    bool valid(uint32_t now)const{return id[0] && uint32_t(now-started)<ttl;}
    void move(bool next){if(!ready||confirming||pending||result!=None)return;if(next&&page+1<pages())++page;else if(!next&&page)--page;seen|=1u<<page;}
    bool confirm(){if(!ready||!allowed||!reviewed()||pending||result!=None)return false;confirming=true;return true;}
    bool submit(){if(!confirming||!reviewed()||pending||result!=None)return false;pending=true;return true;}
};
