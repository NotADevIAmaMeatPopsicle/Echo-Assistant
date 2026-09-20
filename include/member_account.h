#pragma once
#include <stdint.h>
#include <string.h>
#include <stdio.h>
struct MemberAccount {
    char ids[16][33]{},names[16][25]{},code[9]{},message[33]="Loading accounts";
    unsigned count=0,received=0,offset=0,digits=0;int selected=-1;
    bool pending=false;uint32_t at=0;
    void inputClear(){memset(code,0,sizeof(code));digits=0;}
    void clear(){*this=MemberAccount{};}
    bool begin(unsigned n){if(n>16)return false;clear();count=n;strcpy(message,n?"Choose your account":"Ask owner to share an account");return true;}
    bool item(unsigned index,const char* id,const char* name){
        if(index>=count||strlen(id)!=32||strspn(id,"0123456789abcdef")!=32||!name[0]||strlen(name)>24)return false;
        for(const char* c=name;*c;++c)if(*c<32||*c>126)return false;
        for(unsigned i=0;i<count;++i)if(i!=index&&(received&(1u<<i))&&strcmp(ids[i],id)==0)return false;
        strcpy(ids[index],id);strcpy(names[index],name);received|=1u<<index;return true;
    }
    bool choose(unsigned index,uint32_t now){
        if(pending||index>=count||!(received&(1u<<index)))return false;
        inputClear();selected=int(index);at=now;message[0]=0;return true;
    }
    void digit(unsigned value,uint32_t now){if(pending||selected<0||value>9||digits>=8)return;code[digits++]=char('0'+value);code[digits]=0;at=now;}
    void backspace(uint32_t now){if(!pending&&digits){code[--digits]=0;at=now;}}
    bool submit(uint32_t now){if(pending||selected<0||digits!=8)return false;pending=true;at=now;strcpy(message,"Signing in...");return true;}
    void error(const char* value){inputClear();pending=false;snprintf(message,sizeof(message),"%s",value);}
    void tick(uint32_t now){if((digits||pending||selected>=0)&&now-at>60000){inputClear();selected=-1;pending=false;strcpy(message,"Choose your account");}}
};
